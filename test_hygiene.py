"""Hygiène du dépôt et de l'image. Lancer : python test_hygiene.py

Couvre EX-SEC-06 (aucun secret dans le dépôt), EX-SEC-17 (.dockerignore) et
EX-SEC-18 (prénoms des mariés dans aucun fichier versionné).

Ce fichier ne contient volontairement aucun prénom réel : il les lit dans
l'environnement. Les écrire ici serait précisément la faute qu'il surveille.
"""
import os
import pathlib
import re
import subprocess
import sys

RACINE = pathlib.Path(__file__).parent

# Valeurs fictives de `.env.example`, légitimement présentes dans le dépôt.
# Le contrôle d'EX-SEC-18 les exclut ; tout autre prénom trouvé dans
# l'environnement est traité comme le prénom réel.
PRENOMS_FICTIFS = {"Solène", "Gaspard"}

# --- Présence des trois fichiers, et de rien d'autre -----------------------
for nom in (".gitignore", ".dockerignore", ".env.example"):
    assert (RACINE / nom).is_file(), f"{nom} manquant — écart n° 1 du briefing"

assert not (RACINE / ".env").exists(), \
    ".env présent dans l'arborescence de travail : à ne jamais committer"

# --- EX-SEC-06 : ce que .gitignore doit couvrir ---------------------------
gitignore = (RACINE / ".gitignore").read_text(encoding="utf-8")
lignes_git = {l.strip() for l in gitignore.splitlines()}
for motif in (".env", "*.db", "*.db-wal", "*.db-shm", "__pycache__/"):
    assert motif in lignes_git, f".gitignore ne couvre pas {motif} (EX-SEC-06)"

# `.env*` emporterait `.env.example` en silence : la négation doit suivre.
assert "!.env.example" in lignes_git, \
    ".gitignore doit réadmettre .env.example explicitement"
assert gitignore.index(".env.*") < gitignore.index("!.env.example"), \
    "la négation doit venir après le motif, sinon Git l'ignore"

# Les migrations sont du code de production, jamais des artefacts.
assert not re.search(r"^\s*alembic", gitignore, re.M), \
    "alembic/versions/ ne doit jamais être ignoré : le schéma deviendrait " \
    "irreproductible"

# --- EX-SEC-17 : ce que .dockerignore doit couvrir ------------------------
dockerignore = (RACINE / ".dockerignore").read_text(encoding="utf-8")
lignes_docker = {l.strip() for l in dockerignore.splitlines()}
for motif in (".env", "*.db", ".git", "test_*.py"):
    assert motif in lignes_docker, f".dockerignore ne couvre pas {motif} (EX-SEC-17)"

# Le Dockerfile fait bien `COPY . .` : c'est ce qui rend .dockerignore
# nécessaire. Si cette ligne disparaît un jour, le contrôle doit le dire.
dockerfile = (RACINE / "Dockerfile").read_text(encoding="utf-8")
assert "COPY . ." in dockerfile, \
    "le Dockerfile ne fait plus COPY . . — revoir la justification d'EX-SEC-17"

# Ce dont l'image a besoin ne doit pas être exclu par mégarde.
for indispensable in ("requirements.txt", "main.py", "questions.yaml",
                      "templates", "static"):
    assert indispensable not in lignes_docker, \
        f".dockerignore exclut {indispensable}, dont l'image a besoin"

assert "!.env.example" in lignes_docker, \
    ".dockerignore doit réadmettre .env.example : il documente l'environnement"


# --- Les deux fichiers d'exclusion sont éprouvés, pas seulement relus -------
# Lire un motif ne dit pas ce qu'il attrape. `.dockerignore` n'obéit d'ailleurs
# pas aux règles de `.gitignore` : Docker ancre chaque motif à la racine du
# contexte, si bien que `__pycache__/` laisserait passer
# `templates/__pycache__`.
import fnmatch  # noqa: E402  — local à ce contrôle

def _regex_docker(motif: str) -> re.Pattern:
    m = motif.lstrip("!").lstrip("/")
    m = m.replace("**/", "\x00").replace("**", "\x01")
    m = fnmatch.translate(m)
    for brut, remplacement in (("\\x00", "(?:.*/)?"), ("\\x01", ".*"),
                               ("\x00", "(?:.*/)?"), ("\x01", ".*")):
        m = m.replace(brut, remplacement)
    return re.compile(m)

_motifs_docker = [(_regex_docker(l), l.startswith("!"), l)
                  for l in (x.strip() for x in dockerignore.splitlines())
                  if l and not l.startswith("#")]

def exclu_de_l_image(chemin: str) -> bool:
    """Dernier motif qui correspond, comme le fait Docker."""
    verdict = False
    for rx, negation, _ in _motifs_docker:
        segments = chemin.split("/")
        if any(rx.match("/".join(segments[:i + 1])) for i in range(len(segments))):
            verdict = not negation
    return verdict

# Ce que l'image doit recevoir. `alembic/` y figure avant d'exister : c'est
# précisément l'oubli qui rendrait le schéma de Railway irreproductible.
for chemin in ("main.py", "ia.py", "noms.py", "base_donnees.py",
               "questions.yaml", "requirements.txt", "Dockerfile",
               "templates/questionnaire.html", "static/style.css",
               ".env.example", "alembic.ini", "alembic/versions/0001_socle.py"):
    assert not exclu_de_l_image(chemin), \
        f".dockerignore exclut {chemin}, dont l'image a besoin (EX-SEC-17)"

# Ce que l'image ne doit jamais recevoir, à n'importe quelle profondeur.
for chemin in (".env", ".env.local", "sous/dossier/.env", "essai.db",
               "essai.db-wal", "data/projets/2026-09-05/app.db",
               ".git/config", "templates/__pycache__/x.pyc",
               "test_parcours.py", "instantanes/app-2130.db", "logs/x.log"):
    assert exclu_de_l_image(chemin), \
        f".dockerignore laisse passer {chemin} dans l'image (EX-SEC-17)"

# `.gitignore` se vérifie sur la vraie implémentation, quand Git est là.
def _ignore_par_git(chemins: list[str]) -> set[str]:
    resultat = subprocess.run(["git", "check-ignore", "--no-index", *chemins],
                              cwd=RACINE, capture_output=True, text=True)
    return {l.strip() for l in resultat.stdout.splitlines() if l.strip()}

try:
    subprocess.run(["git", "rev-parse", "--git-dir"], cwd=RACINE, check=True,
                   capture_output=True)
except (subprocess.CalledProcessError, FileNotFoundError):
    pass
else:
    a_ignorer = [".env", ".env.local", "essai.db", "essai.db-wal",
                 "data/projets/x/app.db", "instantanes/app.db", "logs/x.log",
                 "__pycache__/main.pyc"]
    a_suivre = [".env.example", "main.py", "questions.yaml", "alembic.ini",
                "alembic/versions/0001_socle.py", "templates/base.html"]
    ignores = _ignore_par_git(a_ignorer + a_suivre)
    for chemin in a_ignorer:
        assert chemin in ignores, f".gitignore laisse passer {chemin} (EX-SEC-06)"
    for chemin in a_suivre:
        assert chemin not in ignores, \
            f".gitignore ignore {chemin}, qui doit être versionné"
    print("exclusions : .gitignore vérifié par git check-ignore, "
          ".dockerignore par simulation des règles Docker")

# --- EX-SEC-18 : aucun prénom réel dans un fichier versionné --------------
def fichiers_versionnes() -> list[pathlib.Path]:
    """`git ls-files` si un dépôt est présent, sinon l'arborescence entière."""
    try:
        sortie = subprocess.run(["git", "ls-files"], cwd=RACINE, check=True,
                                capture_output=True, text=True).stdout
        chemins = [RACINE / l for l in sortie.split("\n") if l.strip()]
        if chemins:
            return [c for c in chemins if c.is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return [c for c in RACINE.rglob("*")
            if c.is_file() and ".git" not in c.parts
            and "__pycache__" not in c.parts and c.suffix not in (".db",)]

reels = {v for cle in ("PRENOM_MARIEE", "PRENOM_MARIE")
         if (v := (os.environ.get(cle) or "").strip())} - PRENOMS_FICTIFS

if reels:
    coupables = []
    for chemin in fichiers_versionnes():
        try:
            texte = chemin.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for prenom in reels:
            if prenom in texte:
                coupables.append(f"{chemin.relative_to(RACINE)} → {prenom}")
    assert not coupables, "EX-SEC-18 violée : " + " ; ".join(coupables)
    print(f"EX-SEC-18 : {len(reels)} prénom(s) réel(s) contrôlé(s), aucune fuite")
else:
    print("EX-SEC-18 : contrôle passé (PRENOM_MARIEE / PRENOM_MARIE non posés "
          "dans l'environnement, ou posés aux valeurs fictives)")

# Les valeurs de `.env.example` doivent être les valeurs fictives, faute de
# quoi la ligne ci-dessus exclurait les vrais prénoms de son propre contrôle.
exemple = (RACINE / ".env.example").read_text(encoding="utf-8")
for cle in ("PRENOM_MARIEE", "PRENOM_MARIE"):
    trouve = re.search(rf"^{cle}=(.+)$", exemple, re.M)
    assert trouve, f"{cle} absente de .env.example"
    assert trouve.group(1).strip() in PRENOMS_FICTIFS, \
        f"{cle} de .env.example n'est pas une valeur fictive connue (EX-SEC-18)"

# --- Dépôt : rien de sensible suivi ---------------------------------------
try:
    suivis = subprocess.run(["git", "ls-files"], cwd=RACINE, check=True,
                            capture_output=True, text=True).stdout.split("\n")
    suivis = [s for s in suivis if s.strip()]
except (subprocess.CalledProcessError, FileNotFoundError):
    suivis = []

if suivis:
    for attendu in (".gitignore", ".dockerignore", ".env.example"):
        assert attendu in suivis, \
            f"{attendu} n'est pas suivi par Git — le dépôt de fichiers de " \
            f"l'interface web laisse les fichiers cachés à la trappe (EX-ARC-19)"
    for chemin in suivis:
        assert chemin != ".env" and not chemin.endswith("/.env"), \
            f"{chemin} est suivi par Git : un secret poussé une fois y demeure"
        assert not chemin.endswith((".db", ".db-wal", ".db-shm")), \
            f"{chemin} est suivi par Git (EX-SEC-06)"
    print(f"dépôt : {len(suivis)} fichiers suivis, aucun secret, aucune base")
else:
    print("dépôt : pas de dépôt Git ici — contrôle `git ls-files` à relancer "
          "sur ta copie de travail", file=sys.stderr)

# --- Étiquettes de bloc uniques -------------------------------------------
# Trois blocs partageaient l'étiquette « (7) » : la sortie annonçait un succès
# sans dire lequel. Un numéro se décale au prochain bloc inséré, un nom non.
for fichier in sorted(RACINE.glob("test_*.py")):
    etiquettes = re.findall(r'print\("TOUT PASSE([^"]*)"',
                            fichier.read_text(encoding="utf-8"))
    doublons = sorted({e.strip(" —") for e in etiquettes
                       if etiquettes.count(e) > 1})
    assert not doublons, \
        f"{fichier.name} : étiquettes de bloc en double → {doublons}"
print(f"étiquettes : uniques dans {len(list(RACINE.glob('test_*.py')))} fichiers "
      f"de test")

print("TOUT PASSE — hygiène du dépôt et de l'image")

# --- Le modèle de config.yaml ne porte aucune valeur réelle ----------------
# Même famille qu'EX-SEC-18 : ce fichier est versionné, et il servira à
# fabriquer le config.yaml de la PRODUCTION. S'il portait le mot de passe de
# la répétition — qui aura circulé pendant tous les essais — le mariage en
# hériterait par recopie, exactement comme l'identifiant de projet du 25 août.
# Un commentaire ne se fait pas respecter tout seul.
import yaml as _yaml

_modele = _yaml.safe_load(
    (RACINE / "exemples" / "config.yaml").read_text(encoding="utf-8"))
import acces as _acces

for _cle in ("mot_de_passe", "mot_de_passe_maries"):
    _valeur = str(_modele.get("acces", {}).get(_cle, ""))
    assert _acces.normaliser(_valeur) == _acces.normaliser(
        _acces.MOT_DE_PASSE_EXEMPLE), (
        f"exemples/config.yaml porte « {_valeur} » en `acces.{_cle}` au lieu "
        f"de « {_acces.MOT_DE_PASSE_EXEMPLE} ». Le filet du démarrage refuse "
        "la valeur d'exemple : y écrire une valeur réelle désarme le filet ET "
        "propage cette valeur au projet de production par recopie.")

# Le fichier doit dire ce qu'il est dès sa première ligne utile : la confusion
# entre ce modèle et le config.yaml du volume a coûté un échange entier.
_entete = (RACINE / "exemples" / "config.yaml").read_text(encoding="utf-8")[:900]
assert "JAMAIS LU PAR L'APPLICATION" in _entete, \
    "l'en-tête doit dire d'emblée que ce fichier n'est pas celui que l'application lit"
print("TOUT PASSE — le modèle de config.yaml ne porte aucune valeur réelle")

# --- Le gabarit d'import ne dérive pas de la spécification -----------------
# EX-ADM-05 fixe sept colonnes, dans cet ordre. Renommer « Prénom » dans le
# gabarit sans toucher à l'import casserait l'import en silence, et un `.xlsx`
# étant binaire, aucun diff ne le montrerait. Le contrôle porte donc sur le
# SCRIPT, qui est du texte — et c'est pour cela qu'il est versionné.
_source = (RACINE / "exemples" / "gabarit_invites.py").read_text(encoding="utf-8")
_attendues = ["Identifiant", "Table", "Prénom", "Nom", "Genre",
              "Responsable", "Marié"]
_position = -1
for _colonne in _attendues:
    _trouve = _source.find(f'("{_colonne}"')
    assert _trouve > 0, f"la colonne « {_colonne} » a disparu du gabarit (EX-ADM-05)"
    assert _trouve > _position, \
        f"« {_colonne} » n'est plus à sa place dans l'ordre d'EX-ADM-05"
    _position = _trouve

# Le classeur produit est versionné à côté : sans lui il faudrait installer
# openpyxl pour simplement remplir la liste des invités.
assert (RACINE / "exemples" / "invites-gabarit.xlsx").is_file(), \
    "le classeur produit doit être versionné à côté de son script"
print("TOUT PASSE — le gabarit d'import porte les sept colonnes d'EX-ADM-05")
