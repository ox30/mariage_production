"""Résolution du projet actif et des chemins du volume.

Point d'entrée unique pour tout ce qui touche au système de fichiers.
L'application ne connaît qu'un seul chemin, celui désigné par
`projet-actif.txt` (EX-PRJ-01) ; changer de projet consiste à modifier ce
pointeur et à redémarrer.

Deux principes gouvernent ce fichier :

1. **Un échec au démarrage vaut mieux qu'un repli silencieux.** Le 17 août,
   une base s'est écrite dans le conteneur au lieu du volume et un simple
   ajout de variable a tout effacé. `EXIGER_VOLUME=1` transforme cette perte
   en refus de démarrer (EX-ARC-17).
2. **Rien n'est recopié automatiquement.** Un `questions.yaml` recopié une
   fois puis jamais rafraîchi a fait tourner l'application des heures sur une
   configuration périmée, sans message d'erreur (EX-ARC-19). Un fichier
   manquant provoque donc une erreur qui nomme la commande à taper, jamais une
   copie de complaisance.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pathlib
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

RACINE_DEPOT = pathlib.Path(__file__).resolve().parent

# Repli de développement, utilisé uniquement quand le volume est absent *et*
# qu'EXIGER_VOLUME ne l'interdit pas. Nommé, ignoré par Git, et annoncé à
# chaque démarrage : un repli qui ne se voit pas est un repli qui tue.
RACINE_DEVELOPPEMENT = RACINE_DEPOT / "donnees-locales"

POINTEUR = "projet-actif.txt"
TYPES_DE_PROJET = ("preparation", "production")


# L'environnement est lu à l'appel et non à l'import. Une constante de module
# se fige avant que quiconque puisse la poser : la variable devient alors
# inopérante partout où le module est importé tôt — et intestable.
def racine_configuree() -> pathlib.Path:
    """Emplacement du volume persistant Railway (EX-ARC-04)."""
    return pathlib.Path(os.environ.get("RACINE_DONNEES") or "/data")


def nom_zone_affichage() -> str:
    """EX-GEN-04 — stocké en UTC, affiché en heure locale."""
    return os.environ.get("ZONE_AFFICHAGE") or "Europe/Zurich"


class ErreurConfiguration(RuntimeError):
    """Défaut de configuration détecté au démarrage, jamais en cours de route."""


def maintenant() -> datetime:
    """Horodatage conscient du fuseau, en UTC (EX-GEN-04)."""
    return datetime.now(timezone.utc)


@functools.lru_cache(maxsize=1)
def zone_affichage() -> zoneinfo.ZoneInfo:
    """Fuseau d'affichage, vérifié plutôt que supposé.

    Windows n'a pas de base de fuseaux système, et les images Debian *slim*
    n'en embarquent pas non plus : `ZoneInfo("Europe/Zurich")` y lève
    `ZoneInfoNotFoundError`. Le paquet `tzdata` de `requirements.txt` la
    fournit. Mieux vaut le constater ici qu'au moment d'afficher un
    horodatage au tableau de bord.
    """
    nom = nom_zone_affichage()
    try:
        return zoneinfo.ZoneInfo(nom)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise ErreurConfiguration(
            f"fuseau « {nom} » introuvable : {exc}\n"
            "Aucune base de fuseaux n'est disponible. C'est le cas de Windows "
            "et des images Debian « slim ».\n"
            "Remède : le paquet `tzdata` doit figurer dans requirements.txt, "
            "puis `pip install -r requirements.txt`."
        ) from exc


def en_heure_locale(instant: datetime) -> datetime:
    """UTC en base, heure d'Europe/Zurich à l'écran (EX-GEN-04)."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(zone_affichage())


def empreinte(chemin: pathlib.Path) -> str:
    """Douze caractères de SHA-256, pour reconnaître un fichier d'un coup d'œil.

    Sert au résumé de démarrage : c'est la seule chose qui aurait distingué le
    `questions.yaml` périmé du 17 août de celui qu'on croyait avoir déposé.
    """
    if not chemin.is_file():
        return "absent"
    return hashlib.sha256(chemin.read_bytes()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class Projet:
    """Le projet actif et tous ses chemins.

    Gelé : le type d'un projet est immuable (EX-PRJ-04) et n'est pas
    modifiable depuis l'administration (EX-PRJ-05). Le refuser en mémoire
    évite d'avoir à le refuser dans dix écrans.
    """

    identifiant: str
    nom: str
    date: str | None
    type: str
    langue: str
    dossier: pathlib.Path
    chemin_configuration: pathlib.Path | None
    chemin_questions: pathlib.Path
    chemin_base: pathlib.Path
    dossier_medias: pathlib.Path
    dossier_exports: pathlib.Path
    dossier_logs: pathlib.Path
    dossier_instantanes: pathlib.Path
    est_developpement: bool
    configuration: dict

    @property
    def est_production(self) -> bool:
        return self.type == "production"

    def refuser_si_production(self, operation: str) -> None:
        """EX-PRJ-06 — toute opération destructive est refusée par le serveur.

        Le refus vit ici et non dans l'interface : masquer un bouton n'est pas
        une protection (EX-SEC-04).
        """
        if self.est_production:
            raise PermissionError(
                f"« {operation} » est refusée sur un projet de production "
                f"({self.identifiant}). Cette opération n'existe qu'en "
                f"préparation (EX-PRJ-06)."
            )


# --------------------------------------------------------------------------- #
# Résolution du volume
# --------------------------------------------------------------------------- #

def _exiger_volume() -> bool:
    return os.environ.get("EXIGER_VOLUME", "").strip() == "1"


def _verifier_ecriture(dossier: pathlib.Path) -> None:
    """Un volume monté en lecture seule passe tous les tests d'existence.

    Le seul contrôle qui vaille est d'écrire. Le défaut du 17 août était
    l'absence de volume ; monté au mauvais endroit ou en lecture seule, il
    aurait produit une panne plus tardive et plus difficile à lire.
    """
    sonde = dossier / ".sonde-ecriture"
    try:
        sonde.write_text("ok", encoding="utf-8")
        sonde.unlink()
    except OSError as exc:
        raise ErreurConfiguration(
            f"{dossier} n'est pas accessible en écriture : {exc}\n"
            "Un volume monté en lecture seule laisse croire que tout va bien "
            "jusqu'à la première contribution."
        ) from exc


def racine_donnees() -> pathlib.Path:
    """Le volume, ou le repli de développement s'il est permis."""
    racine = racine_configuree()
    if racine.is_dir():
        _verifier_ecriture(racine)
        return racine

    if _exiger_volume():
        raise ErreurConfiguration(
            f"EXIGER_VOLUME=1 mais {racine} est absent : aucun volume "
            "persistant n'est monté.\n"
            "Railway → service → Volumes → New Volume, point de montage "
            f"{racine}.\n"
            "Le démarrage échoue volontairement : sans volume, la base "
            "s'écrirait dans le conteneur et le prochain redéploiement — un "
            "simple ajout de variable suffit — l'effacerait sans avertissement "
            "(EX-ARC-17)."
        )

    RACINE_DEVELOPPEMENT.mkdir(parents=True, exist_ok=True)
    _verifier_ecriture(RACINE_DEVELOPPEMENT)
    return RACINE_DEVELOPPEMENT


# --------------------------------------------------------------------------- #
# Résolution du projet actif
# --------------------------------------------------------------------------- #

def _lire_pointeur(racine: pathlib.Path) -> str | None:
    """Contenu de `projet-actif.txt`, première ligne non vide (EX-PRJ-01)."""
    fichier = racine / POINTEUR
    if not fichier.is_file():
        return None
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            return ligne
    return None


def _avertissements_nom(identifiant: str) -> list[str]:
    """EX-PRJ-02 demande `AAAA-MM-JJ-identifiant`.

    Un avertissement, jamais un refus : l'exemple de la section 4.5 du cahier
    des charges est lui-même `2026-08-repetition`, sans jour. Bloquer le
    démarrage sur une convention de nommage le 4 septembre à 21 h serait la
    pire façon de faire respecter une règle cosmétique.
    """
    import re
    if re.match(r"^\d{4}-\d{2}-\d{2}-.+$", identifiant):
        return []
    return [f"le dossier « {identifiant} » ne suit pas la forme "
            f"AAAA-MM-JJ-identifiant attendue par EX-PRJ-02"]


def _charger_configuration(chemin: pathlib.Path) -> dict:
    brut = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    if not isinstance(brut, dict):
        raise ErreurConfiguration(f"{chemin} ne contient pas un dictionnaire YAML")
    return brut


def _projet_du_volume(racine: pathlib.Path, identifiant: str) -> Projet:
    dossier = racine / "projets" / identifiant
    if not dossier.is_dir():
        disponibles = sorted(
            d.name for d in (racine / "projets").glob("*") if d.is_dir()
        ) if (racine / "projets").is_dir() else []
        raise ErreurConfiguration(
            f"{POINTEUR} désigne « {identifiant} », mais {dossier} n'existe "
            f"pas.\nProjets présents : "
            f"{', '.join(disponibles) if disponibles else 'aucun'}.\n"
            "Le démarrage échoue plutôt que de retomber sur un autre projet : "
            "travailler sans le savoir dans le mauvais dossier serait pire "
            "qu'une panne (EX-PRJ-01)."
        )

    chemin_configuration = dossier / "config.yaml"
    if not chemin_configuration.is_file():
        raise ErreurConfiguration(
            f"{chemin_configuration} est absent.\n"
            "Rien n'est créé automatiquement : un fichier de configuration "
            "engendré en silence est un fichier que personne ne relit "
            "(EX-ARC-19). Contenu minimal attendu :\n\n"
            "projet:\n"
            f"  identifiant: {identifiant}\n"
            f"  nom: \"{identifiant}\"\n"
            "  date: 2026-09-05\n"
            "  type: preparation      # ou production, immuable ensuite\n"
            "  langue: fr\n"
        )

    configuration = _charger_configuration(chemin_configuration)
    bloc = configuration.get("projet") or {}

    type_projet = str(bloc.get("type", "")).strip()
    if type_projet not in TYPES_DE_PROJET:
        raise ErreurConfiguration(
            f"{chemin_configuration} : `projet.type` vaut "
            f"« {type_projet or '(vide)'} », attendu "
            f"{' ou '.join(TYPES_DE_PROJET)}.\n"
            "Ce champ commande le refus des opérations destructives "
            "(EX-PRJ-06) : il n'a pas de valeur par défaut, parce qu'une "
            "valeur par défaut serait forcément la mauvaise dans un sens ou "
            "dans l'autre."
        )

    # EX-PRJ-12 — `questions.yaml` vit dans le dossier de projet, sur le
    # volume, pour qu'un libellé incompréhensible découvert à 21 h se corrige
    # sans redéployer.
    chemin_questions = dossier / "questions.yaml"
    if not chemin_questions.is_file():
        raise ErreurConfiguration(
            f"{chemin_questions} est absent.\n"
            "Le contenu éditorial du questionnaire vit dans le dossier de "
            "projet, jamais dans le dépôt (EX-PRJ-12). Déposer la copie de "
            "référence du dépôt à cet emplacement, puis redémarrer.\n"
            "Aucune copie n'est faite automatiquement : elle deviendrait "
            "périmée au premier changement du dépôt, sans que rien ne le dise."
        )

    return Projet(
        identifiant=str(bloc.get("identifiant") or identifiant),
        nom=str(bloc.get("nom") or identifiant),
        date=str(bloc["date"]) if bloc.get("date") else None,
        type=type_projet,
        langue=str(bloc.get("langue") or "fr"),
        dossier=dossier,
        chemin_configuration=chemin_configuration,
        chemin_questions=chemin_questions,
        chemin_base=dossier / "app.db",
        dossier_medias=dossier / "medias",
        dossier_exports=dossier / "exports",
        dossier_logs=dossier / "logs",
        dossier_instantanes=dossier / "instantanes",
        est_developpement=False,
        configuration=configuration,
    )


def _projet_de_developpement(racine: pathlib.Path) -> Projet:
    """Projet synthétique, sans fichier de configuration sur le disque.

    `questions.yaml` est lu **directement dans le dépôt**, sans copie : une
    copie locale se serait figée au premier changement du dépôt, reproduisant
    exactement le piège du 17 août sur la machine de développement. Le type
    est forcé à `preparation`, si bien que les opérations destructives restent
    permises en local et refusées en production sans condition (EX-PRJ-06).
    """
    dossier = racine / "projets" / "dev"
    return Projet(
        identifiant="dev",
        nom="Développement local",
        date=None,
        type="preparation",
        langue="fr",
        dossier=dossier,
        chemin_configuration=None,
        chemin_questions=RACINE_DEPOT / "questions.yaml",
        chemin_base=dossier / "app.db",
        dossier_medias=dossier / "medias",
        dossier_exports=dossier / "exports",
        dossier_logs=dossier / "logs",
        dossier_instantanes=dossier / "instantanes",
        est_developpement=True,
        configuration={},
    )


def _creer_arborescence(projet: Projet) -> None:
    """Section 4.5 — l'arborescence existe avant que quoi que ce soit y écrive."""
    dossiers = [
        projet.dossier, projet.dossier_exports, projet.dossier_logs,
        projet.dossier_instantanes,
    ]
    for portee in ("photos_invites", "photos_tables"):
        for variante in ("originaux", "web", "vignettes"):
            dossiers.append(projet.dossier_medias / portee / variante)
    for dossier in dossiers:
        dossier.mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def projet() -> Projet:
    """Le projet actif. Résolu une fois, au premier appel."""
    racine = racine_donnees()
    identifiant = _lire_pointeur(racine)

    if identifiant is None:
        if _exiger_volume():
            raise ErreurConfiguration(
                f"{racine / POINTEUR} est absent ou vide.\n"
                "Ce fichier texte contient le seul nom du dossier de projet "
                "actif, par exemple :\n\n    2026-09-05-court-mariage\n\n"
                "L'application ne connaît aucun autre moyen de savoir où "
                "écrire (EX-PRJ-01)."
            )
        resolu = _projet_de_developpement(racine)
    else:
        resolu = _projet_du_volume(racine, identifiant)

    _creer_arborescence(resolu)
    return resolu


def oublier() -> None:
    """Vide les caches. Réservé aux tests, qui changent d'environnement."""
    projet.cache_clear()
    zone_affichage.cache_clear()


# --------------------------------------------------------------------------- #
# Résumé de démarrage
# --------------------------------------------------------------------------- #

def resume_demarrage() -> str:
    """Les quelques lignes à écrire au journal au `lifespan`.

    L'empreinte de `questions.yaml` y figure parce qu'elle est la seule chose
    qui aurait révélé, le 17 août, que l'application tournait sur une
    configuration périmée. Une ligne au démarrage contre plusieurs heures de
    recherche.
    """
    p = projet()
    lignes = [
        f"projet actif    : {p.identifiant} ({p.nom})",
        f"type            : {p.type}"
        + ("  — opérations destructives refusées (EX-PRJ-06)"
           if p.est_production else ""),
        f"dossier         : {p.dossier}",
        f"base            : {p.chemin_base}",
        f"questions.yaml  : {p.chemin_questions}  [{empreinte(p.chemin_questions)}]",
        f"fuseau affiché  : {nom_zone_affichage()}"
        f"  ({en_heure_locale(maintenant()):%Y-%m-%d %H:%M})",
    ]
    if p.est_developpement:
        lignes.append(
            "ATTENTION       : repli de développement — aucun volume "
            f"persistant sur {racine_configuree()}. Les données vivent dans "
            f"{RACINE_DEVELOPPEMENT}, hors du dépôt. Poser EXIGER_VOLUME=1 en "
            "ligne pour interdire ce repli (EX-ARC-17)."
        )
    for avertissement in (_avertissements_nom(p.identifiant)
                          if not p.est_developpement else []):
        lignes.append(f"avertissement   : {avertissement}")
    return "\n".join(lignes)
