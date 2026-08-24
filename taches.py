"""File de tâches persistée et worker (EX-ARC-09 à EX-ARC-14).

La file est le **régulateur de débit** (EX-IA-24) : le nombre de fils borne
mécaniquement les appels simultanés. Elle absorbe, elle ne rejette jamais —
aucun invité ne doit lire « revenez plus tard » (EX-IA-25).

Quatre propriétés gouvernent ce module.

**Le réessai vit ici, et nulle part ailleurs** (EX-ARC-13). Le client d'API
fait une tentative et lève une exception typée ; c'est le worker qui décide
s'il faut recommencer et quand. Une boucle interne composée avec celle-ci
produirait jusqu'à trente appels facturés là où trois sont prévus.

**Une limitation de débit ralentit tous les fils** (EX-ARC-21). Sans barrière
globale, huit fils se cognent chacun à leur tour au même mur 429 et consomment
le quota pour rien.

**Le nombre de fils se règle sans redéployer** (EX-ARC-20). `EX-SAU-09` gèle
les déploiements pendant toute la soirée : un nombre figé dans l'image serait
irréglable au moment précis où le réglage compte.

**Une tâche réclamée consomme une tentative**, même si le conteneur meurt
ensuite. C'est ce qui empêche une tâche empoisonnée de faire boucler le
service indéfiniment après chaque redémarrage.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

import sqlalchemy as sa

import base_donnees as bd
import config
from modeles import Tache

# Plafond de fils démarrés. La limite effective, elle, se lit dans
# `config.yaml` et s'ajuste à chaud (EX-ARC-20) ; ces boucles-ci dorment tant
# que leur rang la dépasse.
FILS_MAX = 16
FILS_DEFAUT = 8

# Repos entre deux tentatives de réclamation quand la file est vide. Court
# assez pour que l'invité ne sente pas d'attente inutile, long assez pour ne
# pas marteler la base.
REPOS_S = 0.5

PRIORITES = {
    "generation_chronique": Tache.PRIORITE_GENERATION,
    "conversion_image": Tache.PRIORITE_CONVERSION,
    "copie_stockage_objet": Tache.PRIORITE_COPIE,
}


class EchecDefinitif(Exception):
    """Levée par un traitant quand réessayer ne servirait à rien.

    Le worker passe l'objet en échec sans user ses trois tentatives contre un
    mur — une clé d'API refusée ne deviendra pas valide en trente secondes.
    """

    def __init__(self, message: str, reprendre_apres_s: float | None = None,
                 suspendre_tout_s: float | None = None):
        super().__init__(message)
        self.reprendre_apres_s = reprendre_apres_s
        self.suspendre_tout_s = suspendre_tout_s


class EchecTemporaire(Exception):
    """Levée par un traitant quand la tâche mérite une nouvelle tentative.

    `reprendre_apres_s` porte le délai lu dans `retry-after` ; à défaut, le
    worker applique une attente croissante. `suspendre_tout_s` demande en plus
    la barrière globale — réservé au 429, propre au compte (EX-IA-22).
    """

    def __init__(self, message: str, reprendre_apres_s: float | None = None,
                 suspendre_tout_s: float | None = None):
        super().__init__(message)
        self.reprendre_apres_s = reprendre_apres_s
        self.suspendre_tout_s = suspendre_tout_s


@dataclass(frozen=True, slots=True)
class TacheReclamee:
    uuid: str
    type: str
    objet_uuid: str
    tentatives: int


# --------------------------------------------------------------------------- #
# Traitants
# --------------------------------------------------------------------------- #

_traitants: dict[str, Callable[[str], None]] = {}


def enregistrer_traitant(type_tache: str, fonction: Callable[[str], None]) -> None:
    """Associe un type de tâche à la fonction qui l'exécute.

    L'inversion est délibérée : `taches` ne connaît ni `ia`, ni les gabarits,
    ni le contenu de `questions.yaml`. C'est `main` qui déclare ce qu'il sait
    faire, ce qui évite un import circulaire et garde la file générique.
    """
    _traitants[type_tache] = fonction


# --------------------------------------------------------------------------- #
# Barrière globale de débit (EX-ARC-21)
# --------------------------------------------------------------------------- #

_verrou = threading.Lock()
_barriere_jusqua = 0.0          # horloge monotone


def suspendre_reclamations(secondes: float) -> None:
    """Interdit à **tous** les fils de réclamer avant l'échéance.

    Un 429 est propre au compte (EX-IA-22) : le délai vaut pour l'ensemble du
    service, pas pour la seule tâche qui l'a rencontré. Un 529 ne passe pas
    par ici — la saturation du fournisseur se traite tâche par tâche.
    """
    global _barriere_jusqua
    with _verrou:
        _barriere_jusqua = max(_barriere_jusqua, time.monotonic() + max(0.0, secondes))


def secondes_de_suspension() -> float:
    with _verrou:
        return max(0.0, _barriere_jusqua - time.monotonic())


def lever_suspension() -> None:
    """Réservé aux tests, qui ne doivent pas hériter de la barrière précédente."""
    global _barriere_jusqua
    with _verrou:
        _barriere_jusqua = 0.0


# --------------------------------------------------------------------------- #
# Mise en file et réclamation
# --------------------------------------------------------------------------- #

def mettre_en_file(type_tache: str, objet_uuid: str,
                   priorite: int | None = None) -> str | None:
    """Ajoute une tâche. Renvoie `None` si une équivalente est déjà vivante.

    EX-IA-43 — l'index unique partiel refuse une seconde génération non
    terminée pour la même chronique. On s'appuie sur lui plutôt que de
    vérifier d'abord : entre la vérification et l'écriture, un double appui
    sur 4G lente a tout le temps de passer.
    """
    tache = Tache(type=type_tache, objet_uuid=objet_uuid,
                  priorite=PRIORITES.get(type_tache, Tache.PRIORITE_GENERATION)
                  if priorite is None else priorite)
    with bd.Seance() as seance:
        seance.add(tache)
        try:
            seance.commit()
        except sa.exc.IntegrityError as exc:
            seance.rollback()
            # N'absorber QUE le doublon d'EX-IA-43. Un type inconnu, une
            # contrainte de valeur violée ou une clé étrangère absente sont des
            # défauts de programmation : les faire passer pour « une tâche
            # existe déjà » les rendrait invisibles jusqu'au jour où la file
            # cesserait de se remplir sans que rien ne le dise.
            #
            # SQLite ne nomme pas l'index partiel dans son message — il dit
            # « UNIQUE constraint failed: tache.objet_uuid ». C'est donc sur ce
            # texte qu'on discrimine, et non sur le nom de l'index. Une
            # violation de CHECK dit « CHECK constraint failed: … » et remonte.
            message = str(getattr(exc, "orig", exc))
            if not ("UNIQUE constraint failed" in message
                    and "tache.objet_uuid" in message):
                raise
            return None
        return tache.uuid


_RECLAMER = sa.text("""
    UPDATE tache
       SET etat = 'en_cours',
           demarree_le = :maintenant,
           tentatives = tentatives + 1
     WHERE uuid = (
        SELECT uuid FROM tache
         WHERE etat = 'en_attente'
           AND (reprendre_apres IS NULL OR reprendre_apres <= :maintenant)
         ORDER BY priorite, creee_le
         LIMIT 1)
 RETURNING uuid, type, objet_uuid, tentatives
""").bindparams(sa.bindparam("maintenant", type_=sa.DateTime))


def reclamer() -> TacheReclamee | None:
    """Prend la tâche la plus urgente, en une seule instruction.

    `UPDATE … RETURNING` rend la prise **atomique** : huit fils peuvent la
    lancer en même temps, un seul obtiendra chaque tâche. Un `SELECT` suivi
    d'un `UPDATE` laisserait une fenêtre où deux fils traitent la même.

    La tentative est décomptée à la prise, non à l'échec : une tâche réclamée
    puis perdue dans un redémarrage a bien coûté un essai, et sans ce
    décompte une tâche empoisonnée relancerait le service à chaque démarrage.
    """
    maintenant = config.maintenant()
    with bd.Seance() as seance:
        ligne = seance.execute(_RECLAMER, {"maintenant": maintenant}).first()
        seance.commit()
    if ligne is None:
        return None
    return TacheReclamee(uuid=ligne[0], type=ligne[1], objet_uuid=ligne[2],
                         tentatives=ligne[3])


def terminer(uuid_tache: str) -> None:
    with bd.Seance() as seance:
        tache = seance.get(Tache, uuid_tache)
        if tache is not None:
            tache.etat = "terminee"
            tache.terminee_le = config.maintenant()
            tache.derniere_erreur = None
            seance.commit()


def differer(uuid_tache: str, erreur: str, secondes: float) -> None:
    """Remet la tâche en attente, prête à repartir après le délai."""
    with bd.Seance() as seance:
        tache = seance.get(Tache, uuid_tache)
        if tache is not None:
            tache.etat = "en_attente"
            tache.derniere_erreur = erreur[:500]
            tache.reprendre_apres = config.maintenant() + timedelta(seconds=secondes)
            tache.demarree_le = None
            seance.commit()


def echouer(uuid_tache: str, erreur: str) -> None:
    with bd.Seance() as seance:
        tache = seance.get(Tache, uuid_tache)
        if tache is not None:
            tache.etat = "echouee"
            tache.derniere_erreur = erreur[:500]
            tache.terminee_le = config.maintenant()
            seance.commit()


def reprendre_interrompues() -> int:
    """EX-ARC-11 — toute tâche restée `en_cours` repasse en `en_attente`.

    C'est ce qui rend un redéploiement inoffensif : le conteneur meurt au
    milieu d'une génération, et la tâche repart au démarrage suivant. Les
    tentatives déjà décomptées, elles, ne sont pas rendues.
    """
    with bd.Seance() as seance:
        resultat = seance.execute(
            sa.update(Tache).where(Tache.etat == "en_cours")
            .values(etat="en_attente", demarree_le=None))
        seance.commit()
        return resultat.rowcount or 0


# --------------------------------------------------------------------------- #
# Ce que l'invité voit (EX-IA-25, EX-IA-32)
# --------------------------------------------------------------------------- #

def position(objet_uuid: str) -> int | None:
    """Rang de la tâche dans l'ordre de service, 1 pour la prochaine servie.

    `None` si aucune tâche vivante ne concerne cet objet. Les tâches déjà en
    cours comptent : elles occupent un fil, donc elles précèdent.
    """
    with bd.Seance() as seance:
        mienne = seance.scalar(
            sa.select(Tache).where(Tache.objet_uuid == objet_uuid,
                                   Tache.etat.in_(("en_attente", "en_cours")))
            .order_by(Tache.priorite, Tache.creee_le).limit(1))
        if mienne is None:
            return None
        if mienne.etat == "en_cours":
            return 1
        devant = seance.scalar(
            sa.select(sa.func.count()).select_from(Tache)
            .where(Tache.etat.in_(("en_attente", "en_cours")),
                   sa.tuple_(Tache.priorite, Tache.creee_le)
                   < sa.tuple_(mienne.priorite, mienne.creee_le)))
        return (devant or 0) + 1


def duree_moyenne_s(defaut: float = 32.0, echantillon: int = 20) -> float:
    """Durée moyenne des dernières générations réussies.

    Une constante mentirait : trois portraits mesurés vont de 16 à 49
    secondes. Ce qu'on affiche à l'invité doit suivre la soirée réelle.
    """
    with bd.Seance() as seance:
        durees = [
            (fin - debut).total_seconds()
            for debut, fin in seance.execute(
                sa.select(Tache.demarree_le, Tache.terminee_le)
                .where(Tache.type == "generation_chronique",
                       Tache.etat == "terminee",
                       Tache.demarree_le.is_not(None),
                       Tache.terminee_le.is_not(None))
                .order_by(Tache.terminee_le.desc()).limit(echantillon))
        ]
    return round(sum(durees) / len(durees), 1) if durees else defaut


def attente_estimee_s(objet_uuid: str) -> float | None:
    """Ordre de grandeur, jamais une promesse (EX-IA-25)."""
    rang = position(objet_uuid)
    if rang is None:
        return None
    return round(max(1, rang) / max(1, fils_actifs()) * duree_moyenne_s())


def secondes_depuis_mise_en_file(objet_uuid: str) -> float | None:
    """EX-IA-32 — temps réellement écoulé depuis la validation.

    File d'attente et tentatives échouées comprises : quelqu'un qui a patienté
    quatre-vingt-dix secondes ne doit pas lire « 35 s ».
    """
    with bd.Seance() as seance:
        creee = seance.scalar(
            sa.select(sa.func.min(Tache.creee_le))
            .where(Tache.objet_uuid == objet_uuid,
                   Tache.etat.in_(("en_attente", "en_cours"))))
    if creee is None:
        return None
    return round((config.maintenant() - creee).total_seconds())


# --------------------------------------------------------------------------- #
# Le worker
# --------------------------------------------------------------------------- #

_executeur: ThreadPoolExecutor | None = None
_arret = threading.Event()


def fils_actifs() -> int:
    """Nombre de fils autorisés, relu à chaud dans `config.yaml` (EX-ARC-20)."""
    valeur = config.parametre("worker.fils", FILS_DEFAUT)
    try:
        return max(1, min(FILS_MAX, int(valeur)))
    except (TypeError, ValueError):
        return FILS_DEFAUT


def _executer(tache: TacheReclamee) -> None:
    """Exécute une tâche et décide de sa suite. Trois tentatives (EX-ARC-13)."""
    traitant = _traitants.get(tache.type)
    if traitant is None:
        echouer(tache.uuid, f"aucun traitant pour « {tache.type} »")
        return
    try:
        traitant(tache.objet_uuid)
    except EchecTemporaire as exc:
        if exc.suspendre_tout_s:
            suspendre_reclamations(exc.suspendre_tout_s)
        if tache.tentatives >= 3:
            echouer(tache.uuid, f"abandon après {tache.tentatives} tentatives : {exc}")
            return
        # Le délai lu dans `retry-after` prime sur l'attente croissante : lui
        # seul dit quand le fournisseur acceptera de nouveau.
        delai = exc.reprendre_apres_s
        if delai is None:
            delai = 2 ** tache.tentatives
        differer(tache.uuid, str(exc), delai)
    except EchecDefinitif as exc:
        if exc.suspendre_tout_s:
            suspendre_reclamations(exc.suspendre_tout_s)
        echouer(tache.uuid, str(exc))
    except Exception as exc:  # défaut du traitant, pas du fournisseur
        if tache.tentatives >= 3:
            echouer(tache.uuid, f"{type(exc).__name__} — {exc}")
        else:
            differer(tache.uuid, f"{type(exc).__name__} — {exc}",
                     2 ** tache.tentatives)
    else:
        terminer(tache.uuid)


def traiter_une() -> bool:
    """Réclame et exécute une tâche, ici et maintenant. Renvoie `False` si vide.

    Même chemin que le worker, sans la boucle ni les fils. Les tests s'en
    servent pour piloter la file **sans dormir** : une attente arbitraire
    produit des tests qui passent une fois sur deux, et un test intermittent
    finit toujours par être ignoré.
    """
    tache = reclamer()
    if tache is None:
        return False
    _executer(tache)
    return True


def _boucle(rang: int) -> None:
    """Un fil de service. Dort tant que son rang dépasse la limite courante."""
    while not _arret.is_set():
        try:
            if rang >= fils_actifs():
                _arret.wait(2.0)
                continue
            suspension = secondes_de_suspension()
            if suspension > 0:
                # EX-ARC-21 — tous les fils patientent, pas seulement celui
                # qui a rencontré le 429.
                _arret.wait(min(suspension, 5.0))
                continue
            tache = reclamer()
            if tache is None:
                _arret.wait(REPOS_S)
                continue
            _executer(tache)
        except Exception:
            # Un fil ne meurt jamais : il ralentit. Un worker qui perd ses
            # fils un par un cesse de servir sans que rien ne le dise.
            _arret.wait(1.0)


def demarrer() -> int:
    """Lance le worker au `lifespan` (EX-ARC-10). Renvoie le nombre de fils.

    `WORKER_ACTIF=0` l'inhibe : les tests entrent dans le cycle de vie et ne
    doivent pas se mettre à consommer des appels d'API.
    """
    global _executeur
    if os.environ.get("WORKER_ACTIF", "1").strip() == "0":
        return 0
    if _executeur is not None:
        return FILS_MAX
    reprises = reprendre_interrompues()
    if reprises:
        print(f"file            : {reprises} tâche(s) interrompue(s) remise(s) "
              f"en attente (EX-ARC-11)", flush=True)
    _arret.clear()
    _executeur = ThreadPoolExecutor(max_workers=FILS_MAX,
                                    thread_name_prefix="tache")
    for rang in range(FILS_MAX):
        _executeur.submit(_boucle, rang)
    return FILS_MAX


def arreter(attendre: float = 5.0) -> None:
    global _executeur
    _arret.set()
    if _executeur is not None:
        _executeur.shutdown(wait=True, cancel_futures=True)
        _executeur = None
