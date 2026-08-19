"""Résolution du projet actif. Lancer : python test_config.py

Couvre EX-PRJ-01 (pointeur unique), EX-PRJ-02 (nom de dossier), EX-PRJ-04 à
EX-PRJ-06 (type immuable, refus en production), EX-PRJ-12 (`questions.yaml`
dans le dossier de projet), EX-ARC-17 (refus de démarrer sans volume) et
EX-GEN-04 (UTC en base, heure locale à l'écran).

L'essentiel de ce fichier porte sur les **chemins d'échec** : la valeur de
`config.py` n'est pas de trouver le bon dossier, c'est de refuser de démarrer
quand il ne le trouve pas.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

RACINE = pathlib.Path(__file__).parent
sys.path.insert(0, str(RACINE))

CONFIG_MINIMALE = """\
projet:
  identifiant: {identifiant}
  nom: "Essai"
  date: 2026-09-05
  type: {type}
  langue: fr
"""


def demarrer(**environnement) -> subprocess.CompletedProcess:
    """Démarre config.py dans un processus neuf.

    Un sous-processus et non un rechargement de module : `projet()` est mis en
    cache et l'essentiel de ce qu'on éprouve se produit une seule fois, au
    démarrage. Le rejouer dans le même interpréteur ne prouverait rien.
    """
    milieu = {k: v for k, v in os.environ.items()
              if k not in ("EXIGER_VOLUME", "RACINE_DONNEES", "ZONE_AFFICHAGE")}
    milieu.update({k: str(v) for k, v in environnement.items()})
    return subprocess.run(
        [sys.executable, "-c",
         "import config; print(config.resume_demarrage())"],
        cwd=RACINE, env=milieu, capture_output=True, text=True)


def echoue_avec(fragment: str, **environnement) -> str:
    resultat = demarrer(**environnement)
    assert resultat.returncode != 0, \
        f"démarrage réussi alors qu'il devait échouer :\n{resultat.stdout}"
    assert "ErreurConfiguration" in resultat.stderr, resultat.stderr[-600:]
    assert fragment in resultat.stderr, \
        f"message attendu « {fragment} » absent de :\n{resultat.stderr[-800:]}"
    return resultat.stderr


def reussit(**environnement) -> str:
    resultat = demarrer(**environnement)
    assert resultat.returncode == 0, resultat.stderr[-800:]
    return resultat.stdout


# --------------------------------------------------------------------------- #
volume = pathlib.Path(tempfile.mkdtemp(prefix="volume-"))
projets = volume / "projets"
NOM = "2026-09-05-court-mariage"
dossier = projets / NOM

# --- EX-ARC-17 : le défaut du 17 août -------------------------------------
message = echoue_avec("aucun volume persistant n'est monté",
                      EXIGER_VOLUME=1, RACINE_DONNEES="/volume-inexistant")
assert "EX-ARC-17" in message, "le message doit citer l'exigence"
assert "point de montage" in message, "le message doit dire quoi faire"

# --- EX-PRJ-01 : le pointeur est le seul moyen de savoir où écrire ---------
echoue_avec("est absent ou vide", EXIGER_VOLUME=1, RACINE_DONNEES=volume)

(volume / "projet-actif.txt").write_text(f"# commentaire ignoré\n\n{NOM}\n",
                                         encoding="utf-8")
echoue_avec("n'existe pas", EXIGER_VOLUME=1, RACINE_DONNEES=volume)

# Un pointeur fautif ne doit pas retomber sur le projet voisin : travailler
# sans le savoir dans le mauvais dossier est pire qu'une panne.
autre = projets / "2026-08-repetition"
autre.mkdir(parents=True)
(autre / "config.yaml").write_text(
    CONFIG_MINIMALE.format(identifiant=autre.name, type="preparation"),
    encoding="utf-8")
shutil.copy(RACINE / "questions.yaml", autre / "questions.yaml")
message = echoue_avec("n'existe pas", EXIGER_VOLUME=1, RACINE_DONNEES=volume)
assert "2026-08-repetition" in message, \
    "le message doit énumérer les projets réellement présents"

# --- EX-ARC-19 : rien n'est créé automatiquement ---------------------------
dossier.mkdir(parents=True)
message = echoue_avec("config.yaml est absent",
                      EXIGER_VOLUME=1, RACINE_DONNEES=volume)
assert "projet:" in message and "type: preparation" in message, \
    "le message doit donner le contenu minimal à écrire"
assert not (dossier / "config.yaml").exists(), \
    "config.py ne doit rien avoir créé"

# --- EX-PRJ-04 : le type n'a pas de valeur par défaut ---------------------
(dossier / "config.yaml").write_text(
    'projet:\n  identifiant: x\n  nom: "x"\n  langue: fr\n', encoding="utf-8")
echoue_avec("`projet.type` vaut", EXIGER_VOLUME=1, RACINE_DONNEES=volume)

(dossier / "config.yaml").write_text(
    CONFIG_MINIMALE.format(identifiant=NOM, type="repetition"),
    encoding="utf-8")
echoue_avec("attendu preparation ou production",
            EXIGER_VOLUME=1, RACINE_DONNEES=volume)

# --- EX-PRJ-12 : questions.yaml vit dans le dossier de projet -------------
(dossier / "config.yaml").write_text(
    CONFIG_MINIMALE.format(identifiant=NOM, type="production"),
    encoding="utf-8")
message = echoue_avec("questions.yaml est absent",
                      EXIGER_VOLUME=1, RACINE_DONNEES=volume)
assert "EX-PRJ-12" in message
assert not (dossier / "questions.yaml").exists(), \
    "aucune copie automatique : elle se figerait au premier changement du dépôt"

print("TOUT PASSE — refus de démarrer sur configuration incomplète")

# --------------------------------------------------------------------------- #
# --- Production complète --------------------------------------------------
shutil.copy(RACINE / "questions.yaml", dossier / "questions.yaml")
sortie = reussit(EXIGER_VOLUME=1, RACINE_DONNEES=volume)
assert NOM in sortie
assert "type            : production" in sortie
assert "EX-PRJ-06" in sortie, "le résumé doit signaler le régime de production"
assert "repli de développement" not in sortie
assert str(dossier / "app.db") in sortie, "la base vit dans le dossier de projet"

# L'empreinte de questions.yaml figure au résumé : c'est la seule chose qui
# aurait révélé la configuration périmée du 17 août.
import config  # noqa: E402  — après les essais en sous-processus

empreinte_depot = config.empreinte(RACINE / "questions.yaml")
assert f"[{empreinte_depot}]" in sortie, "empreinte absente du résumé"

(dossier / "questions.yaml").write_text("lieux: []\n", encoding="utf-8")
sortie_modifiee = reussit(EXIGER_VOLUME=1, RACINE_DONNEES=volume)
assert f"[{empreinte_depot}]" not in sortie_modifiee, \
    "l'empreinte doit changer quand le fichier change — sinon elle ne sert à rien"
shutil.copy(RACINE / "questions.yaml", dossier / "questions.yaml")

# Section 4.5 — l'arborescence existe avant que quoi que ce soit y écrive.
for attendu in ("exports", "logs", "instantanes",
                "medias/photos_invites/originaux", "medias/photos_invites/web",
                "medias/photos_invites/vignettes",
                "medias/photos_tables/originaux", "medias/photos_tables/web",
                "medias/photos_tables/vignettes"):
    assert (dossier / attendu).is_dir(), f"{attendu} non créé (section 4.5)"

# --- EX-PRJ-02 : avertissement, jamais refus ------------------------------
(volume / "projet-actif.txt").write_text("2026-08-repetition\n", encoding="utf-8")
sortie = reussit(EXIGER_VOLUME=1, RACINE_DONNEES=volume)
assert "AAAA-MM-JJ-identifiant" in sortie, "le nom non conforme doit être signalé"
assert "avertissement" in sortie, "et rester un avertissement"
(volume / "projet-actif.txt").write_text(f"{NOM}\n", encoding="utf-8")

print("TOUT PASSE — projet de production résolu et arborescence créée")

# --------------------------------------------------------------------------- #
# --- Volume monté en lecture seule ----------------------------------------
# Un volume monté au mauvais endroit ou en lecture seule passe tous les tests
# d'existence : seule une écriture réelle le révèle.
lecture_seule = pathlib.Path(tempfile.mkdtemp(prefix="lecture-seule-"))
os.chmod(lecture_seule, 0o500)
if os.geteuid() == 0:
    print("      (sonde d'écriture non vérifiable en root, qui ignore les "
          "bits de permission — vérifiée à la main sur un montage ro)")
else:
    echoue_avec("n'est pas accessible en écriture",
                EXIGER_VOLUME=1, RACINE_DONNEES=lecture_seule)
os.chmod(lecture_seule, 0o700)
shutil.rmtree(lecture_seule)

# --- Repli de développement : permis, mais annoncé ------------------------
sortie = reussit(RACINE_DONNEES="/volume-inexistant")
assert "repli de développement" in sortie, "un repli qui ne se voit pas tue"
assert "EX-ARC-17" in sortie, "le résumé doit dire comment l'interdire"
assert "type            : preparation" in sortie, \
    "le projet de développement est forcément en préparation (EX-PRJ-06)"
assert str(RACINE / "questions.yaml") in sortie, \
    "en développement, questions.yaml est lu dans le dépôt, sans copie"

print("TOUT PASSE — repli de développement annoncé, sonde d'écriture")

# --------------------------------------------------------------------------- #
# --- EX-PRJ-05 et EX-PRJ-06 : le type est immuable et refuse ---------------
os.environ["EXIGER_VOLUME"] = "1"
os.environ["RACINE_DONNEES"] = str(volume)
config.oublier()
p = config.projet()
assert p.type == "production" and p.est_production

try:
    object.__setattr__  # le dataclass est gelé : aucune écriture n'est offerte
    p.type = "preparation"
except Exception as exc:
    assert type(exc).__name__ in ("FrozenInstanceError", "AttributeError"), exc
else:
    raise AssertionError("le type doit être immuable (EX-PRJ-04, EX-PRJ-05)")

try:
    p.refuser_si_production("remise à zéro")
except PermissionError as exc:
    assert "EX-PRJ-06" in str(exc) and "remise à zéro" in str(exc)
else:
    raise AssertionError("une opération destructive doit être refusée")

# En préparation, la même opération passe.
(volume / "projet-actif.txt").write_text("2026-08-repetition\n", encoding="utf-8")
config.oublier()
config.projet().refuser_si_production("remise à zéro")
(volume / "projet-actif.txt").write_text(f"{NOM}\n", encoding="utf-8")

print("TOUT PASSE — type immuable, opérations destructives refusées en production")

# --------------------------------------------------------------------------- #
# --- EX-GEN-04 : UTC en base, Europe/Zurich à l'écran ---------------------
instant = config.maintenant()
assert instant.tzinfo is not None and instant.utcoffset().total_seconds() == 0, \
    "les horodatages sont stockés en UTC"

# 5 septembre 2026, 22 h à Court : heure d'été suisse, UTC+2.
soiree = datetime(2026, 9, 5, 20, 0, tzinfo=timezone.utc)
locale = config.en_heure_locale(soiree)
assert (locale.hour, locale.minute) == (22, 0), locale
assert locale.utcoffset().total_seconds() == 7200, "UTC+2 en heure d'été"

# Un horodatage naïf est lu comme de l'UTC, jamais comme de l'heure locale :
# l'inverse décalerait tout d'une ou deux heures selon la saison.
naif = datetime(2026, 9, 5, 20, 0)
assert config.en_heure_locale(naif).hour == 22

# Le fuseau est vérifié au démarrage plutôt que supposé : sans base de fuseaux,
# Windows et les images Debian « slim » lèvent ZoneInfoNotFoundError.
resultat = demarrer(EXIGER_VOLUME=1, RACINE_DONNEES=volume,
                    ZONE_AFFICHAGE="Terre/Du-Milieu")
assert resultat.returncode != 0 and "tzdata" in resultat.stderr, \
    "un fuseau introuvable doit nommer le remède"

assert "tzdata" in (RACINE / "requirements.txt").read_text(encoding="utf-8"), \
    "tzdata doit figurer dans requirements.txt (EX-GEN-04)"

print("TOUT PASSE — UTC en base, heure locale à l'écran")

shutil.rmtree(volume)
