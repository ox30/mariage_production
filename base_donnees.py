"""Persistance SQLite — **reprise du banc d'essai, en attente de migration**.

Ce module utilise `sqlite3` de la bibliothèque standard, alors que la section
4.2 du cahier des charges impose SQLAlchemy 2.0 + Alembic. C'est l'écart n° 2
du briefing : un choix tenable pour une table, intenable pour dix.

Il sera remplacé à l'étape suivante du socle par les dix entités de la
section 5.1. La table `participation` ci-dessous n'existe que pour garder le
parcours invité fonctionnel jusque-là.
"""

import json
import os
import random
import sqlite3
import uuid
from datetime import datetime, timezone

import config
import noms

# Le chemin et le garde-fou de volume vivent désormais dans config.py : un seul
# endroit décide où l'application écrit (EX-PRJ-01, EX-ARC-17).
CHEMIN = str(config.projet().chemin_base)

SCHEMA = """
CREATE TABLE IF NOT EXISTS participation (
    uuid              TEXT PRIMARY KEY,
    prenom            TEXT NOT NULL,
    nom               TEXT NOT NULL,
    genre             TEXT,
    lieu              TEXT NOT NULL,
    reponses_json     TEXT NOT NULL,
    etage             INTEGER NOT NULL DEFAULT 1,
    nom_fictif        TEXT,
    peuple            TEXT,
    portrait          TEXT,
    indice            TEXT,
    fuites_noms       TEXT,
    modele            TEXT,
    duree_s           REAL,
    jetons_entree     INTEGER,
    jetons_sortie     INTEGER,
    nb_generations    INTEGER NOT NULL DEFAULT 0,
    nb_tentatives     INTEGER NOT NULL DEFAULT 0,
    etat              TEXT NOT NULL DEFAULT 'en_attente',
    derniere_erreur   TEXT,
    validee           INTEGER NOT NULL DEFAULT 0,
    creee_le          TEXT NOT NULL,
    modifiee_le       TEXT NOT NULL
);
"""


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connexion() -> sqlite3.Connection:
    cnx = sqlite3.connect(CHEMIN, timeout=15.0)
    cnx.row_factory = sqlite3.Row
    cnx.execute("PRAGMA journal_mode=WAL")
    cnx.execute("PRAGMA foreign_keys=ON")
    return cnx


# Un échec technique ne coûte rien à l'invité, mais il ne doit pas non plus
# autoriser une boucle infinie d'appels payants. Deux compteurs distincts :
# `nb_generations` = portraits réellement obtenus, débité du quota ;
# `nb_tentatives`  = appels tentés, garde-fou technique.
MAX_TENTATIVES = 10


def initialiser() -> None:
    with connexion() as cnx:
        cnx.executescript(SCHEMA)
        # Migration légère : ajouter une colonne à une base existante plutôt que
        # d'exiger sa suppression. L'application réelle utilisera Alembic.
        colonnes = {c["name"] for c in cnx.execute("PRAGMA table_info(participation)")}
        for nom_colonne, definition in (("genre", "TEXT"),):
            if nom_colonne not in colonnes:
                cnx.execute(f"ALTER TABLE participation ADD COLUMN {nom_colonne} {definition}")
        colonnes = {r["name"] for r in cnx.execute("PRAGMA table_info(participation)")}
        if "nb_tentatives" not in colonnes:
            cnx.execute("ALTER TABLE participation ADD COLUMN "
                        "nb_tentatives INTEGER NOT NULL DEFAULT 0")


def assigner_lieu(cnx: sqlite3.Connection, lieux: list[str]) -> str:
    """Le lieu le moins peuplé ; tirage au sort en cas d'égalité.

    Aucune considération de la table réelle : les grappes fortuites sont
    voulues, elles brouillent la reconstitution du plan de table.
    """
    effectifs = {lieu: 0 for lieu in lieux}
    for ligne in cnx.execute("SELECT lieu, COUNT(*) n FROM participation GROUP BY lieu"):
        if ligne["lieu"] in effectifs:
            effectifs[ligne["lieu"]] = ligne["n"]
    minimum = min(effectifs.values())
    return random.choice([lieu for lieu, n in effectifs.items() if n == minimum])


def creer(prenom: str, nom: str, reponses: dict, lieux: list[str],
          etat: str = "en_attente", genre: str | None = None) -> str:
    # Capitalisé une fois, à l'entrée : ce qui est stocké est ce qui sera montré
    # aux mariés, et c'est aussi ce qui alimente la liste des noms interdits.
    prenom, nom = noms.capitaliser(prenom), noms.capitaliser(nom)
    identifiant = str(uuid.uuid4())
    horodatage = maintenant()
    with connexion() as cnx:
        lieu = assigner_lieu(cnx, lieux)
        cnx.execute(
            """INSERT INTO participation
               (uuid, prenom, nom, genre, lieu, reponses_json, etat, creee_le, modifiee_le)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (identifiant, prenom, nom, genre or None, lieu,
             json.dumps(reponses, ensure_ascii=False), etat, horodatage, horodatage),
        )
    return identifiant


def lire(identifiant: str) -> sqlite3.Row | None:
    with connexion() as cnx:
        return cnx.execute("SELECT * FROM participation WHERE uuid = ?", (identifiant,)).fetchone()


def lister(seulement_validees: bool = False) -> list[sqlite3.Row]:
    requete = "SELECT * FROM participation"
    if seulement_validees:
        requete += " WHERE validee = 1 AND portrait IS NOT NULL"
    requete += " ORDER BY lieu, creee_le"
    with connexion() as cnx:
        return cnx.execute(requete).fetchall()


def tous_les_prenoms() -> list[str]:
    with connexion() as cnx:
        lignes = cnx.execute("SELECT prenom, nom FROM participation").fetchall()
    mots: list[str] = []
    for ligne in lignes:
        mots += ligne["prenom"].split() + ligne["nom"].split()
    return mots


def noms_fictifs_pris(sauf: str | None = None) -> list[str]:
    """Les noms fictifs déjà attribués, pour éviter deux homonymes sur la carte."""
    with connexion() as cnx:
        lignes = cnx.execute(
            "SELECT uuid, nom_fictif FROM participation WHERE nom_fictif IS NOT NULL"
        ).fetchall()
    return [l["nom_fictif"] for l in lignes if l["uuid"] != sauf]


def enregistrer_portrait(identifiant: str, portrait: dict) -> None:
    with connexion() as cnx:
        cnx.execute(
            """UPDATE participation SET
                 nom_fictif=?, peuple=?, portrait=?, indice=?, fuites_noms=?,
                 modele=?, duree_s=?, jetons_entree=?, jetons_sortie=?,
                 nb_generations = nb_generations + 1,
                 nb_tentatives = nb_tentatives + 1,
                 etat='prete', derniere_erreur=NULL, modifiee_le=?
               WHERE uuid=?""",
            (portrait["nom_fictif"], portrait["peuple"], portrait["portrait"],
             portrait["indice"], json.dumps(portrait.get("fuites_noms", []), ensure_ascii=False),
             portrait.get("modele"), portrait.get("duree_s"), portrait.get("jetons_entree"),
             portrait.get("jetons_sortie"), maintenant(), identifiant),
        )


def enregistrer_echec(identifiant: str, erreur: str) -> None:
    with connexion() as cnx:
        cnx.execute(
            """UPDATE participation
               SET etat='echouee', derniere_erreur=?,
                   nb_tentatives = nb_tentatives + 1,
                   modifiee_le=?
               WHERE uuid=?""",
            (erreur[:500], maintenant(), identifiant),
        )


def marquer_en_cours(identifiant: str) -> None:
    with connexion() as cnx:
        cnx.execute(
            "UPDATE participation SET etat='en_cours', modifiee_le=? WHERE uuid=?",
            (maintenant(), identifiant),
        )


def valider(identifiant: str) -> None:
    with connexion() as cnx:
        cnx.execute(
            "UPDATE participation SET validee=1, modifiee_le=? WHERE uuid=?",
            (maintenant(), identifiant),
        )


def ajouter_bonus(identifiant: str, reponses_bonus: dict) -> None:
    """Fusionne les réponses complémentaires et remet l'objet en attente.

    Sans réponse complémentaire — l'invité a choisi de passer — l'étage reste
    à 1 : le tableau de bord doit dire la vérité sur ce qui a été donné.
    """
    with connexion() as cnx:
        ligne = cnx.execute(
            "SELECT reponses_json FROM participation WHERE uuid=?", (identifiant,)
        ).fetchone()
        reponses = json.loads(ligne["reponses_json"])
        reponses.update(reponses_bonus)
        etage = 2 if reponses_bonus else 1
        cnx.execute(
            """UPDATE participation
               SET reponses_json=?, etage=?, validee=0, etat='en_attente',
                   modifiee_le=?
               WHERE uuid=?""",
            (json.dumps(reponses, ensure_ascii=False), etage, maintenant(), identifiant),
        )
