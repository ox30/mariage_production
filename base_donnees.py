"""Persistance — SQLAlchemy 2.0, migrations Alembic, SQLite en WAL.

Remplace la persistance `sqlite3` du banc d'essai. L'écart n° 2 du briefing
est levé.

Deux propriétés gouvernent ce module.

**Aucun compteur n'est stocké.** `nb_generations` et `nb_tentatives` se
comptent dans le journal à chaque lecture (EX-GEN-07, EX-IA-21). Deux entrées
distinctes : une *tentative* est un appel émis, une *génération* un portrait
valide reçu. Un échec technique ne peut donc pas débiter le quota — non parce
qu'on y prend garde, mais parce qu'il n'existe aucun compteur à incrémenter
par mégarde.

**Le lieu est un code stable.** Tout ce module raisonne sur `lieu_01`…
`lieu_10` ; le libellé n'apparaît qu'à l'affichage (EX-IA-28, EX-IA-42).
"""

from __future__ import annotations

import json
import random
from datetime import datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

import config
import modeles
import noms
from modeles import Chronique, Journal, Personne

CHEMIN = str(config.projet().chemin_base)

# Garde-fou technique contre la boucle d'appels payants. Il ne s'agit pas d'un
# quota : le quota de l'invité est le nombre de portraits obtenus, et un échec
# ne le débite jamais (EX-IA-21).
MAX_TENTATIVES = 10


def maintenant() -> datetime:
    return config.maintenant()


# --------------------------------------------------------------------------- #
# Moteur et session
# --------------------------------------------------------------------------- #

moteur = create_engine(
    f"sqlite+pysqlite:///{CHEMIN}",
    # Le worker écrira depuis plusieurs fils ; les sessions, elles, ne sont
    # jamais partagées entre fils.
    connect_args={"check_same_thread": False, "timeout": 15.0},
    future=True,
)

Seance = sessionmaker(bind=moteur, expire_on_commit=False, future=True)


@event.listens_for(moteur, "connect")
def _pragmas(connexion, _):
    curseur = connexion.cursor()
    # EX-SAU-07 — WAL : les lecteurs ne bloquent pas l'écrivain, et le fichier
    # se copie tel quel.
    curseur.execute("PRAGMA journal_mode=WAL")
    # `synchronous=FULL` et non `NORMAL` : la base est la seule chose non
    # régénérable du projet (EX-GEN-08). En WAL, `NORMAL` peut perdre les
    # dernières transactions à l'arrêt brutal d'un conteneur. Le surcoût est
    # d'un `fsync` par validation, soit quelques centaines sur la soirée.
    curseur.execute("PRAGMA synchronous=FULL")
    curseur.execute("PRAGMA foreign_keys=ON")
    curseur.execute("PRAGMA busy_timeout=15000")
    curseur.close()


def initialiser() -> None:
    """Applique les migrations jusqu'à la dernière révision.

    Au démarrage et non par une commande séparée : le service tourne en une
    seule instance (EX-ARC-05), il n'y a donc aucune course possible, et une
    migration qu'on peut oublier de lancer est une migration qu'on oubliera.
    """
    parametres = Config(str(config.RACINE_DEPOT / "alembic.ini"))
    parametres.set_main_option("script_location",
                              str(config.RACINE_DEPOT / "alembic"))
    command.upgrade(parametres, "head")


# --------------------------------------------------------------------------- #
# Compteurs dérivés
# --------------------------------------------------------------------------- #

def _compter(seance: Session, chronique_uuid: str, action: str) -> int:
    return seance.scalar(
        select(func.count()).select_from(Journal)
        .where(Journal.objet_uuid == chronique_uuid, Journal.action == action)
    ) or 0


def compteurs(seance: Session, chronique_uuid: str) -> tuple[int, int]:
    """(portraits obtenus, appels tentés), comptés dans le journal.

    Le premier consomme le quota de l'invité, le second est un garde-fou
    technique. Les deux sont dérivés : aucune colonne ne les porte
    (EX-GEN-07, EX-IA-21).
    """
    return (_compter(seance, chronique_uuid, Journal.CHRONIQUE_GENEREE),
            _compter(seance, chronique_uuid, Journal.CHRONIQUE_TENTEE))


def _garnir(seance: Session, chronique: Chronique | None) -> Chronique | None:
    """Attache les compteurs dérivés à l'objet renvoyé.

    Ce sont des attributs Python posés à la lecture, jamais des colonnes : ils
    ne peuvent pas dériver de la réalité, puisqu'ils sont recalculés à chaque
    fois. Les gabarits continuent d'écrire `p.nb_generations` sans savoir d'où
    la valeur vient.
    """
    if chronique is None:
        return None
    obtenus, tentees = compteurs(seance, chronique.uuid)
    chronique.nb_generations = obtenus
    chronique.nb_tentatives = tentees
    chronique.fuites_noms = json.loads(chronique.fuites_noms_json or "[]")
    return chronique


def journaliser(seance: Session, action: str, *, objet_uuid: str | None = None,
                objet_type: str | None = None, acteur: str | None = None,
                pour_le_compte_de: str | None = None,
                details: dict | None = None) -> None:
    """EX-GEN-05 — trace des actions sensibles, et source des consommations."""
    seance.add(Journal(
        action=action, objet_uuid=objet_uuid, objet_type=objet_type,
        acteur_personne_uuid=acteur, agit_pour_le_compte_de=pour_le_compte_de,
        details_json=json.dumps(details, ensure_ascii=False) if details else None,
        horodatage=maintenant(),
    ))


# --------------------------------------------------------------------------- #
# Personnes
# --------------------------------------------------------------------------- #

def _cle_nom(prenom: str, nom: str) -> tuple[str, str]:
    return noms.capitaliser(prenom), noms.capitaliser(nom)


def personne_par_nom(seance: Session, prenom: str, nom: str) -> Personne | None:
    prenom, nom = _cle_nom(prenom, nom)
    return seance.scalar(
        select(Personne).where(Personne.prenom == prenom, Personne.nom == nom)
    )


def creer_personne(seance: Session, prenom: str, nom: str,
                   genre: str | None = None,
                   source: str = "saisie_libre") -> Personne:
    """EX-AUTH-21 — le nom est capitalisé une fois, à la création.

    C'est la forme normalisée qui est stockée, montrée aux mariés et versée à
    la liste des noms interdits.
    """
    prenom, nom = _cle_nom(prenom, nom)
    personne = Personne(prenom=prenom, nom=nom, source=source,
                        genre=genre if genre in ("masculin", "feminin") else None)
    seance.add(personne)
    seance.flush()
    return personne


# --------------------------------------------------------------------------- #
# Assignation du lieu
# --------------------------------------------------------------------------- #

def assigner_lieu(seance: Session, codes_lieux: list[str]) -> str:
    """Le lieu le moins peuplé ; tirage au sort en cas d'égalité (EX-IA-06).

    L'équilibrage porte sur le **code** et non sur le libellé (EX-IA-42) :
    renommer une région en pleine soirée ne doit rien déplacer.

    Aucune considération de la table réelle n'entre ici (EX-IA-07). Les
    grappes fortuites sont voulues : une répartition trop régulière serait
    elle-même un indice, alors qu'une grappe due au hasard est indiscernable
    d'un plan de table.
    """
    effectifs = {code: 0 for code in codes_lieux}
    for code, total in seance.execute(
        select(Chronique.lieu, func.count())
        .where(Chronique.supprimee.is_(False))
        .group_by(Chronique.lieu)
    ):
        if code in effectifs:
            effectifs[code] = total
    minimum = min(effectifs.values())
    return random.choice([c for c, n in effectifs.items() if n == minimum])


# --------------------------------------------------------------------------- #
# Chroniques
# --------------------------------------------------------------------------- #

def creer(prenom: str, nom: str, reponses: dict, codes_lieux: list[str],
          etat: str = "en_attente", genre: str | None = None) -> str:
    """Crée la personne si nécessaire, puis sa chronique.

    EX-IA-26 — **une seule chronique par personne.** Une deuxième tentative de
    création reconduit vers la chronique existante, qui se modifie et se
    régénère dans la limite des trois générations. Deux chroniques
    produiraient deux marqueurs sur la carte, dont un que les mariés ne
    pourraient jamais deviner.

    Le rapprochement se fait sur le couple (prénom, nom) normalisé. La
    détection de doublon approximative avec confirmation (EX-AUTH-05) et la
    sélection dans la liste importée (EX-AUTH-19) viennent à l'étape 2 : d'ici
    là, deux homonymes réels seraient confondus.
    """
    with Seance() as seance:
        personne = personne_par_nom(seance, prenom, nom)
        if personne is None:
            personne = creer_personne(seance, prenom, nom, genre=genre)
        elif genre in ("masculin", "feminin") and personne.genre != genre:
            personne.genre = genre

        existante = seance.scalar(
            select(Chronique).where(Chronique.personne_uuid == personne.uuid,
                                    Chronique.supprimee.is_(False)))
        if existante is not None:
            # « Reconduit vers », et non « écrase ». Rien n'est touché : ni les
            # réponses, ni l'étage, ni le quota. Les réponses sont la seule
            # chose irremplaçable du projet (EX-GEN-08) ; les remplacer parce
            # que quelqu'un a ressaisi son nom serait la pire des portes
            # dérobées.
            #
            # Défaut constaté le 20 août : un second passage sous le même nom
            # avait effacé sept réponses et cinq complémentaires, consommé une
            # génération sur trois, et laissé `etage` à 2 alors qu'il ne
            # restait aucune réponse complémentaire.
            return existante.uuid

        chronique = Chronique(
            personne_uuid=personne.uuid,
            lieu=assigner_lieu(seance, codes_lieux),
            reponses_json=json.dumps(reponses, ensure_ascii=False),
            etat=etat,
        )
        seance.add(chronique)
        seance.commit()
        return chronique.uuid


def chronique_de(prenom: str, nom: str) -> str | None:
    """L'identifiant de la chronique de cette personne, si elle en a une.

    Interrogée dès la saisie du nom, pour reconduire l'invité vers son
    personnage au lieu de lui faire répondre sept questions qui seraient
    ensuite ignorées (EX-IA-26). L'écran à deux entrées d'EX-AUTH-09 et la
    confirmation de doublon d'EX-AUTH-05 viennent à l'étape 2 ; d'ici là,
    cette reconduction est ce qui protège les réponses déjà données.
    """
    if not prenom.strip() or not nom.strip():
        return None
    with Seance() as seance:
        personne = personne_par_nom(seance, prenom, nom)
        if personne is None:
            return None
        return seance.scalar(
            select(Chronique.uuid).where(
                Chronique.personne_uuid == personne.uuid,
                Chronique.supprimee.is_(False)))


# Renseigné au démarrage par main.py, seul module qui lit questions.yaml.
# `base_donnees` n'a pas à connaître le contenu éditorial du questionnaire.
CLES_SECOND_ETAGE: set[str] = set()


def etage_des_reponses(reponses: dict) -> int:
    """L'étage se **déduit** des réponses présentes ; il ne se déclare pas.

    Une valeur dérivée ne peut pas se désynchroniser de ce qu'elle décrit —
    même raisonnement que pour les compteurs de génération (EX-GEN-07). Et
    comme les réponses ne sont jamais que fusionnées, jamais retirées, l'étage
    ne peut mécaniquement pas redescendre.

    Défaut de la version précédente : `etage = 2 if reponses_bonus else 1`
    faisait retomber à 1 un invité déjà au second étage qui repassait par le
    formulaire complémentaire et l'envoyait vide, alors que ses cinq réponses
    restaient en base. Le tableau de bord mentait alors sur ce qui avait été
    donné, et la proposition du second étage se rouvrait (EX-QUE-11).
    """
    return 2 if any(reponses.get(cle) for cle in CLES_SECOND_ETAGE) else 1


def lire(identifiant: str) -> Chronique | None:
    with Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        if chronique is None:
            return None
        personne = seance.get(Personne, chronique.personne_uuid)
        chronique.prenom = personne.prenom
        chronique.nom = personne.nom
        chronique.genre = personne.genre
        return _garnir(seance, chronique)


def lister(seulement_validees: bool = False) -> list[Chronique]:
    with Seance() as seance:
        requete = (select(Chronique, Personne)
                   .join(Personne, Personne.uuid == Chronique.personne_uuid)
                   .where(Chronique.supprimee.is_(False)))
        if seulement_validees:
            requete = requete.where(Chronique.validee.is_(True),
                                    Chronique.portrait.is_not(None))
        sortie = []
        for chronique, personne in seance.execute(
                requete.order_by(Chronique.lieu, Chronique.creee_le)):
            chronique.prenom = personne.prenom
            chronique.nom = personne.nom
            chronique.genre = personne.genre
            sortie.append(_garnir(seance, chronique))
        return sortie


def tous_les_prenoms() -> list[str]:
    """Les mots interdits en sortie du modèle (EX-IA-13)."""
    with Seance() as seance:
        mots: list[str] = []
        for prenom, nom in seance.execute(select(Personne.prenom, Personne.nom)):
            mots += prenom.split() + nom.split()
        return mots


def noms_fictifs_pris(sauf: str | None = None) -> list[str]:
    """EX-IA-31 — deux personnages homonymes seraient indiscernables."""
    with Seance() as seance:
        return [n for identifiant, n in seance.execute(
            select(Chronique.uuid, Chronique.nom_fictif)
            .where(Chronique.nom_fictif.is_not(None),
                   Chronique.supprimee.is_(False)))
            if identifiant != sauf]


def enregistrer_portrait(identifiant: str, portrait: dict) -> None:
    """Portrait valide reçu : une tentative **et** une génération."""
    with Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        if chronique is None:
            return
        chronique.nom_fictif = portrait["nom_fictif"]
        chronique.peuple = portrait["peuple"]
        chronique.portrait = portrait["portrait"]
        chronique.indice = portrait["indice"]
        chronique.fuites_noms_json = json.dumps(
            portrait.get("fuites_noms", []), ensure_ascii=False)
        chronique.modele = portrait.get("modele")
        chronique.duree_s = portrait.get("duree_s")
        chronique.jetons_entree = portrait.get("jetons_entree")
        chronique.jetons_sortie = portrait.get("jetons_sortie")
        chronique.etat = "prete"
        chronique.derniere_erreur = None
        details = {"modele": portrait.get("modele"),
                   "duree_s": portrait.get("duree_s"),
                   "jetons_entree": portrait.get("jetons_entree"),
                   "jetons_sortie": portrait.get("jetons_sortie")}
        journaliser(seance, Journal.CHRONIQUE_TENTEE, objet_uuid=identifiant,
                    objet_type="chronique", acteur=chronique.personne_uuid)
        journaliser(seance, Journal.CHRONIQUE_GENEREE, objet_uuid=identifiant,
                    objet_type="chronique", acteur=chronique.personne_uuid,
                    details=details)
        seance.commit()


def enregistrer_echec(identifiant: str, erreur: str) -> None:
    """Échec : une tentative, aucune génération.

    C'est ici que se joue EX-IA-21. Le quota de l'invité suit les portraits
    obtenus ; une surcharge de l'API à 22 h ne lui retire rien.
    """
    with Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        if chronique is None:
            return
        chronique.etat = "echouee"
        chronique.derniere_erreur = erreur[:500]
        journaliser(seance, Journal.CHRONIQUE_TENTEE, objet_uuid=identifiant,
                    objet_type="chronique", acteur=chronique.personne_uuid,
                    details={"erreur": erreur[:300]})
        seance.commit()


def marquer_en_cours(identifiant: str) -> None:
    with Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        if chronique is not None:
            chronique.etat = "en_cours"
            seance.commit()


def valider(identifiant: str) -> None:
    with Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        if chronique is not None:
            chronique.validee = True
            seance.commit()


def reprendre_reponses(identifiant: str, reponses: dict) -> None:
    """EX-IA-05 — l'invité modifie ses réponses après lecture de son portrait.

    **Fusion, jamais remplacement.** Une réponse absente du formulaire est une
    réponse inchangée, pas une réponse effacée : les réponses sont la seule
    chose irremplaçable du projet (EX-GEN-08).

    L'étage se recalcule depuis les réponses fusionnées, donc il ne peut pas
    redescendre. Le décompte de génération, lui, reste au parcours appelant :
    modifier ses réponses puis régénérer consomme la même unité que régénérer
    sans rien changer, parce que du point de vue de l'invité c'est le même
    geste — obtenir un autre texte (EX-IA-04).
    """
    with Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        if chronique is None:
            return
        fusionnees = json.loads(chronique.reponses_json)
        modifiees = sorted(cle for cle, valeur in reponses.items()
                           if valeur and fusionnees.get(cle) != valeur)
        fusionnees.update({c: v for c, v in reponses.items() if v})
        chronique.reponses_json = json.dumps(fusionnees, ensure_ascii=False)
        chronique.etage = etage_des_reponses(fusionnees)
        chronique.validee = False
        chronique.etat = "en_attente"
        journaliser(seance, "reponses_reprises", objet_uuid=identifiant,
                    objet_type="chronique", acteur=chronique.personne_uuid,
                    details={"cles_modifiees": modifiees})
        seance.commit()


def ajouter_bonus(identifiant: str, reponses_bonus: dict) -> None:
    """Fusionne les réponses complémentaires et remet la chronique en attente.

    Sans réponse complémentaire — l'invité a choisi de passer — l'étage reste
    à 1 : le tableau de bord doit dire la vérité sur ce qui a été donné.
    """
    with Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        if chronique is None:
            return
        reponses = json.loads(chronique.reponses_json)
        reponses.update(reponses_bonus)
        chronique.reponses_json = json.dumps(reponses, ensure_ascii=False)
        chronique.etage = etage_des_reponses(reponses)
        chronique.validee = False
        chronique.etat = "en_attente"
        seance.commit()
