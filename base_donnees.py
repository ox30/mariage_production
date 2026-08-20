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
            # Le lieu est figé à la première validation : une reprise réécrit
            # le texte, jamais l'assignation (EX-IA-08).
            existante.reponses_json = json.dumps(reponses, ensure_ascii=False)
            existante.etat = etat
            seance.commit()
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
        chronique.etage = 2 if reponses_bonus else 1
        chronique.validee = False
        chronique.etat = "en_attente"
        seance.commit()
