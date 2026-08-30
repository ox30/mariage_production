"""Test de fumée du morceau A — la page de mesure jetable.

Une page jetable mérite quand même trois assertions, parce que celle qui compte
n'est pas ce qu'elle mesure mais ce qu'elle ne fait pas : servir quand on a
oublié de la retirer, et écrire sur le volume de la répétition.

À supprimer avec `mesure_photo.py` et `templates/mesure.html`.
"""

import os
import struct

os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")

import mesure_photo


# --- la route est éteinte par défaut ---------------------------------------

# `main` est importé SANS `MESURE_PHOTO` dans l'environnement : c'est l'état
# de la production. La route ne doit pas exister.
assert os.environ.get("MESURE_PHOTO") != "1", \
    "ce test doit s'exécuter sans MESURE_PHOTO, sinon il n'éprouve rien"

import main

chemins = {getattr(r, "path", None) for r in main.app.routes}
assert "/mesure" not in chemins, \
    f"la route de mesure est servie sans MESURE_PHOTO=1 : {sorted(c for c in chemins if c)}"
assert "/mesure/duree" not in chemins

# Et dans les deux sens : le drapeau commande bien quelque chose.
assert mesure_photo.actif() is False
os.environ["MESURE_PHOTO"] = "1"
assert mesure_photo.actif() is True
os.environ["MESURE_PHOTO"] = "0"
assert mesure_photo.actif() is False, "seule la valeur « 1 » active la page"
del os.environ["MESURE_PHOTO"]

print("TOUT PASSE — la page de mesure est éteinte par défaut")


# --- le format se lit aux octets, jamais au nom du fichier -----------------

def _ftyp(marque: bytes) -> bytes:
    return b"\x00\x00\x00\x20" + b"ftyp" + marque + b"\x00" * 16


cas = [
    (b"\xff\xd8\xff\xe0" + b"\x00" * 20, "jpeg"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "png"),
    (b"GIF89a" + b"\x00" * 20, "gif"),
    (b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 12, "webp"),
    (b"II*\x00" + b"\x00" * 20, "tiff"),
    (_ftyp(b"heic"), "heif (heic)"),
    (_ftyp(b"mif1"), "heif (mif1)"),
    (_ftyp(b"avif"), "avif (avif)"),
    # EX-PHO-12 — une vidéo partage le conteneur du HEIC ; seule la marque les
    # sépare. Une reconnaissance sur l'extension laisserait passer un .mov
    # renommé.
    (_ftyp(b"qt  "), "VIDÉO (qt  )"),
    (_ftyp(b"mp42"), "VIDÉO (mp42)"),
    (b"ceci n'est pas une image du tout" + b"\x00" * 8, "inconnu"),
]
for octets, attendu in cas:
    obtenu = mesure_photo.identifier(octets)
    assert obtenu == attendu, f"{attendu!r} attendu, {obtenu!r} obtenu"

# Un HEIC et un MP4 ne se distinguent QUE par leur marque : si la table des
# marques vidéo était vide, celui-ci passerait pour une image.
assert mesure_photo.identifier(_ftyp(b"mp42")).startswith("VIDÉO")
assert not mesure_photo.identifier(_ftyp(b"heic")).startswith("VIDÉO")

print("TOUT PASSE — le format réel se lit aux octets de tête")


# --- les dimensions se lisent sans bibliothèque d'image --------------------

png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
       + struct.pack(">II", 4032, 3024) + b"\x08\x02\x00\x00\x00")
assert mesure_photo.dimensions(png, "png") == (4032, 3024)

# JPEG : le SOF est précédé d'un APP1 volumineux, comme sur une vraie photo de
# téléphone. Un cas sans APP1 passerait même avec une lecture à décalage fixe,
# donc il n'éprouverait pas le parcours des segments.
exif = b"Exif\x00\x00" + b"\x00" * 3000
app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
sof = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
       + struct.pack(">HH", 3024, 4032) + b"\x03" + b"\x00" * 9)
jpeg = b"\xff\xd8" + app1 + sof + b"\xff\xda\x00\x0c" + b"\x00" * 10
assert mesure_photo.dimensions(jpeg, "jpeg") == (4032, 3024), \
    mesure_photo.dimensions(jpeg, "jpeg")
assert mesure_photo.porte_exif(jpeg) is True

# Le SOF placé APRÈS le début des données n'existe pas : rendre None plutôt
# qu'un couple d'octets pris au hasard dans l'image.
tronque = b"\xff\xd8" + b"\xff\xda\x00\x0c" + b"\x00" * 40
assert mesure_photo.dimensions(tronque, "jpeg") is None

# Un HEIF n'est pas lisible sans décodeur, et c'est la réponse attendue : la
# mesure aura déjà dit qu'il faut un décodeur.
assert mesure_photo.dimensions(_ftyp(b"heic"), "heif (heic)") is None
assert mesure_photo.porte_exif(b"\xff\xd8\xff" + b"\x00" * 100) is False

print("TOUT PASSE — dimensions et EXIF lus sans dépendance nouvelle")


# --- rien n'est écrit hors mémoire -----------------------------------------

source = open(mesure_photo.__file__, encoding="utf-8").read()
for interdit in ("open(", "Path(", "write_text", "write_bytes", "shutil",
                 "depot_objet", "base_donnees", "Seance"):
    assert interdit not in source, \
        f"la page de mesure touche à « {interdit} » : elle doit rester sans trace"

print("TOUT PASSE — la page de mesure n'écrit ni fichier ni ligne en base")
