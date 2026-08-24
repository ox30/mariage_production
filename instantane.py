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

import os
import pathlib
import threading

import sqlalchemy as sa

import base_donnees as bd
import config
import depot_objet
from modeles import Sauvegarde

PERIODE_S = 180.0

_arret = threading.Event()
_fil: threading.Thread | None = None


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


def un_passage() -> list[depot_objet.Resultat]:
    """Produit un instantané et le pousse sur toutes les destinations."""
    try:
        chemin = produire()
    except Exception as exc:
        _consigner("instantane", False, 0, f"{type(exc).__name__} — {exc}")
        raise

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
