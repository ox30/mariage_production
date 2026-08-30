"""Instantané de la base, poussé vers le stockage objet (EX-SAU-13 à EX-SAU-18).

La perte de la base n'effacerait pas des JPEG orphelins : elle effacerait
**toutes les réponses**, seule chose non régénérable du projet (EX-GEN-08).
C'est ce qui justifie qu'`EX-PLA-05` place ce module avant le module Photo.

Trois propriétés gouvernent ce fichier.

**L'instantané n'est pas une tâche de la file** (EX-SAU-18). Mis en file, il
attendrait derrière cent générations au moment précis où il compte le plus.
Il tourne dans une boucle périodique dédiée, indépendante du worker.

**La connexion est en autocommit** (EX-SAU-17). Le pilote `sqlite3` ouvre une
transaction implicite et `VACUUM INTO` échoue alors avec « cannot VACUUM from
within a transaction ». En autocommit, l'instruction s'exécute pendant qu'une
autre connexion tient une transaction ouverte, et la transaction non validée
est correctement exclue du fichier produit.

**Aucun instantané n'est purgé pendant la soirée** (EX-SAU-14, modifié v3.13).
Vingt-quatre instantanés à trois minutes ne couvrent que 72 minutes, alors que
la soirée en dure trois cents : une corruption découverte à minuit n'aurait
plus aucun antécédent sain. Mesuré : cent instantanés tiennent dans 300 Mo.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import sqlite3
import threading

import sqlalchemy as sa

import base_donnees as bd
import config
import depot_objet
from modeles import Sauvegarde

PERIODE_S = 180.0

# Plancher : même sans le moindre changement, un dépôt toutes les six heures.
# Sans lui, dix jours de calme seraient indiscernables d'une panne silencieuse
# des deux dépôts — et personne ne s'en apercevrait avant d'en avoir besoin.
PLANCHER_S = 6 * 3600.0

# Tables exclues de l'empreinte de contenu. `sauvegarde` d'abord, et c'est
# l'essentiel : écrire la ligne d'un dépôt modifie la base, donc l'instantané
# suivant diffère, donc il se redépose, et la boucle se nourrit d'elle-même.
# `tache` ensuite : une tentative qui s'incrémente n'est pas une donnée à
# préserver, et `EX-ARC-11` la rattrape de toute façon au redémarrage.
TABLES_HORS_EMPREINTE = {"sauvegarde", "tache"}

FICHIER_EMPREINTE = ".derniere-empreinte-deposee"

_arret = threading.Event()
_fil: threading.Thread | None = None


def empreinte_contenu(chemin: pathlib.Path) -> str:
    """Empreinte du **contenu métier** d'un instantané.

    Porte sur toutes les lignes de toutes les tables sauf celles de
    `TABLES_HORS_EMPREINTE`. Pas sur une sélection de compteurs et de dates :
    une colonne oubliée dans une telle liste produirait un changement invisible,
    donc une sauvegarde qui n'a pas lieu — exactement le défaut qu'on cherche à
    ne pas créer.

    Les lignes sont triées en Python plutôt que par la base : `VACUUM` peut
    renuméroter les `rowid` des tables sans clé entière, ce qui rendrait
    l'ordre de stockage instable et l'empreinte fausse.
    """
    empreinte = hashlib.sha256()
    connexion = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        tables = sorted(
            nom for (nom,) in connexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")
            if nom not in TABLES_HORS_EMPREINTE)
        for table in tables:
            empreinte.update(table.encode("utf-8"))
            lignes = [repr(ligne) for ligne in connexion.execute(f"SELECT * FROM {table}")]
            for ligne in sorted(lignes):
                empreinte.update(ligne.encode("utf-8"))
    finally:
        connexion.close()
    return empreinte.hexdigest()


def _chemin_empreinte() -> pathlib.Path:
    return config.projet().dossier_instantanes / FICHIER_EMPREINTE


def _derniere_deposee() -> tuple[str | None, float]:
    """(empreinte, horodatage) du dernier dépôt réussi. Survit au redémarrage.

    Dans un fichier plutôt qu'en mémoire : sans cela, chaque redéploiement
    reverserait un instantané identique, et il y en aura plusieurs d'ici au
    5 septembre.
    """
    chemin = _chemin_empreinte()
    if not chemin.is_file():
        return None, 0.0
    try:
        empreinte, instant = chemin.read_text(encoding="utf-8").split(None, 1)
        return empreinte, float(instant)
    except (ValueError, OSError):
        return None, 0.0


def _memoriser_depot(empreinte: str) -> None:
    chemin = _chemin_empreinte()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(f"{empreinte} {config.maintenant().timestamp()}",
                      encoding="utf-8")


def produire(destination: pathlib.Path | None = None) -> pathlib.Path:
    """Écrit un instantané cohérent de `app.db` et renvoie son chemin.

    `VACUUM INTO` est la manière recommandée de copier une base SQLite en
    service : le fichier produit est compact, cohérent, et lisible tel quel.
    """
    projet = config.projet()
    if destination is None:
        # Millisecondes comprises : à la seconde près, deux instantanés
        # rapprochés porteraient le même nom et le second effacerait le
        # premier sans bruit. La période est de trois minutes, mais une
        # relance manuelle ou un test rapproché suffisent à provoquer le cas.
        instant = config.maintenant()
        horodatage = f"{instant:%Y%m%dT%H%M%S}-{instant.microsecond // 1000:03d}Z"
        destination = projet.dossier_instantanes / f"app-{horodatage}.db"
    destination.parent.mkdir(parents=True, exist_ok=True)
    # `VACUUM INTO` refuse d'écraser : un fichier homonyme ferait échouer
    # l'instantané, pas seulement le renommer.
    if destination.exists():
        destination.unlink()

    # EX-SAU-17 — sans AUTOCOMMIT, « cannot VACUUM from within a transaction ».
    moteur = bd.moteur.execution_options(isolation_level="AUTOCOMMIT")
    with moteur.connect() as connexion:
        connexion.exec_driver_sql("VACUUM INTO ?", (str(destination),))
    return destination


def _consigner(cible: str, succes: bool, octets: int, erreur: str | None) -> None:
    """EX-SAU-05 et EX-SAU-15 — une ligne par destination et par passage.

    Par destination et non globalement : avec deux dépôts, un horodatage
    unique masquerait une moitié en panne — on lirait « dernier instantané il
    y a deux minutes » alors qu'un des deux n'aurait plus rien reçu depuis
    20 h.
    """
    with bd.Seance() as seance:
        seance.add(Sauvegarde(cible=cible, succes=succes, nb_objets=1 if succes else 0,
                              octets=octets, erreur=(erreur or None),
                              horodatage=config.maintenant()))
        seance.commit()


def un_passage(forcer: bool = False) -> list[depot_objet.Resultat]:
    """Produit un instantané et le pousse — **si le contenu a changé**.

    Deux instantanés d'une base inchangée sont identiques au bit près :
    vérifié. Sans ce contrôle, dix jours d'attente avant l'événement
    déposeraient 4 800 fois le même fichier, soit 788 Mo pour zéro
    information. La boucle tourne toujours toutes les trois minutes ; c'est le
    dépôt qui est conditionnel, pas la production.

    Aucun interrupteur : une sauvegarde qu'on peut éteindre est une sauvegarde
    qui sera éteinte le jour où elle compte (EX-SAU-13). Ici le comportement
    suit la réalité — rien ne change, rien ne part ; la soirée fait changer
    quelque chose toutes les trois minutes, tout part.
    """
    try:
        chemin = produire()
    except Exception as exc:
        _consigner("instantane", False, 0, f"{type(exc).__name__} — {exc}")
        raise

    empreinte = empreinte_contenu(chemin)
    precedente, dernier_depot = _derniere_deposee()
    age = config.maintenant().timestamp() - dernier_depot
    if not forcer and empreinte == precedente and age < PLANCHER_S:
        # Rien n'a bougé et le plancher n'est pas atteint. L'instantané reste
        # sur le volume — une copie de plus ne coûte rien — mais il ne part pas.
        return []

    contenu = chemin.read_bytes()
    resultats = depot_objet.deposer_partout(f"instantanes/{chemin.name}", contenu)
    if not resultats:
        # Aucune destination : l'instantané local existe quand même. Le dire,
        # pour que le tableau de bord ne laisse pas croire à une sauvegarde
        # hors site qui n'a pas eu lieu.
        _consigner("local", True, len(contenu), None)
        return []
    for resultat in resultats:
        _consigner(resultat.destination, resultat.succes, resultat.octets,
                   resultat.erreur)
    # L'empreinte n'est mémorisée qu'après un dépôt RÉUSSI quelque part :
    # sinon un échec des deux dépôts serait pris pour un succès et le contenu
    # ne repartirait jamais.
    if any(r.succes for r in resultats):
        _memoriser_depot(empreinte)
    return resultats


def dernier_par_destination() -> dict[str, dict]:
    """EX-SAU-15 — l'état de chaque destination, pour le tableau de bord."""
    with bd.Seance() as seance:
        lignes = seance.execute(
            sa.select(Sauvegarde.cible, Sauvegarde.horodatage, Sauvegarde.succes,
                      Sauvegarde.erreur)
            .order_by(Sauvegarde.horodatage.desc())).all()
    dernier: dict[str, dict] = {}
    for cible, horodatage, succes, erreur in lignes:
        etat = dernier.setdefault(cible, {"reussite": None, "echec": None})
        if succes and etat["reussite"] is None:
            etat["reussite"] = horodatage
        if not succes and etat["echec"] is None:
            etat["echec"] = {"horodatage": horodatage, "erreur": erreur}
    return dernier


def _boucle() -> None:
    while not _arret.is_set():
        try:
            un_passage()
        except Exception:
            # La boucle ne meurt jamais : une base momentanément verrouillée ou
            # un disque plein ne doivent pas arrêter les sauvegardes suivantes.
            pass
        _arret.wait(PERIODE_S)


def demarrer() -> bool:
    """Lance la boucle au `lifespan`. `INSTANTANE_ACTIF=0` l'inhibe.

    Un fil dédié, jamais le `ThreadPoolExecutor` du worker (EX-SAU-18).
    """
    global _fil
    if os.environ.get("INSTANTANE_ACTIF", "1").strip() == "0":
        return False
    if _fil is not None and _fil.is_alive():
        return True
    _arret.clear()
    _fil = threading.Thread(target=_boucle, name="instantane", daemon=True)
    _fil.start()
    return True


def arreter() -> None:
    global _fil
    _arret.set()
    if _fil is not None:
        _fil.join(timeout=5.0)
        _fil = None
