"""B2 — la conversion en tâche de fond (EX-PHO-10, EX-PHO-11, EX-PHO-33).

Le chemin heureux est le moins intéressant. Ce qui compte : qu'un format
illisible fasse passer la photo en `echouee` et **rende le crédit**, qu'une
photo restée en traitement sans tâche vivante reparte, et que l'original ne
soit jamais retouché.
"""

import io
import os

os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")

from PIL import Image
from sqlalchemy import select

import base_donnees as bd
import config
import main
import photos
import taches
import test_outils
from modeles import Journal, Photo, Tache

client = test_outils.client(main.app)


def _image(largeur=4032, hauteur=3024, mode="RGB", orientation=None,
           format="JPEG") -> bytes:
    image = Image.new(mode, (largeur, hauteur), (120, 90, 60)
                      if mode == "RGB" else (120, 90, 60, 255))
    tampon = io.BytesIO()
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation          # Orientation
        image.save(tampon, format, exif=exif)
    else:
        image.save(tampon, format)
    return tampon.getvalue()


def _chronique(prenom):
    identifiant = test_outils.creer_chronique(
        prenom, "Conv", {"metier": "x", "allegeance": "La Lumière"},
        main.CODES_LIEUX, etat="prete")
    bd.enregistrer_portrait(identifiant, {
        "nom_fictif": f"{prenom} le Clair", "peuple": "homme",
        "portrait": "Un paragraphe.", "indice": "Un indice.",
        "fuites_noms": [], "modele": "claude-sonnet-5", "duree_s": 5.0,
        "jetons_entree": 800, "jetons_sortie": 250})
    return bd.lire(identifiant)


def _fichier(variante, nom):
    return config.projet().dossier_medias / "photos_invites" / variante / nom


# --- la conversion produit web et vignette sans toucher l'original -------- #

marc = _chronique("Marceau")
octets = _image()
photo = photos.deposer(marc.personne_uuid, octets)
assert photo.etat == "traitement"

# La file exécute ici et maintenant : une attente arbitraire produit des tests
# qui passent une fois sur deux, et un test intermittent finit par être ignoré.
assert taches.traiter_une() is True

with bd.Seance() as seance:
    apres = seance.get(Photo, photo.uuid)
    assert apres.etat == "prete", apres.etat
    assert apres.chemin_web == f"{photo.uuid}.jpg"
    assert apres.chemin_vignette == f"{photo.uuid}.jpg"

# EX-PHO-11 — l'original est intact, octet pour octet. On le LIT, on n'y écrit
# pas.
assert _fichier("originaux", photo.chemin_original).read_bytes() == octets

web = Image.open(_fichier("web", f"{photo.uuid}.jpg"))
assert max(web.size) == photos.COTE_WEB, web.size
assert web.size == (1600, 1200), web.size          # 4:3 conservé
vignette = Image.open(_fichier("vignettes", f"{photo.uuid}.jpg"))
assert max(vignette.size) == photos.COTE_VIGNETTE, vignette.size
assert web.format == "JPEG" and vignette.format == "JPEG"
# Le dérivé pèse une fraction de l'original : c'est tout l'objet de l'opération.
assert _fichier("web", f"{photo.uuid}.jpg").stat().st_size < len(octets)

print("TOUT PASSE — web et vignette produites, original intact")


# --- une image déjà petite n'est jamais agrandie -------------------------- #

# `thumbnail` ne remonte pas : mesuré au morceau A, la capture Android rendait
# 1440×1080, sous la cible. L'agrandir ajouterait du poids sans un pixel de
# détail.
petite = _chronique("Noé")
p2 = photos.deposer(petite.personne_uuid, _image(1440, 1080))
assert taches.traiter_une() is True
assert Image.open(_fichier("web", f"{p2.uuid}.jpg")).size == (1440, 1080)

print("TOUT PASSE — une image plus petite que la cible n'est pas agrandie")


# --- l'orientation EXIF est appliquée, et son absence ne gêne pas --------- #

# Orientation 6 = rotation d'un quart de tour. Sans `exif_transpose`, la photo
# arrive couchée sur le téléphone des mariés.
couchee = _chronique("Ondine")
p3 = photos.deposer(couchee.personne_uuid, _image(4000, 3000, orientation=6))
assert taches.traiter_une() is True
tournee = Image.open(_fichier("web", f"{p3.uuid}.jpg"))
assert tournee.size[1] > tournee.size[0], f"non redressée : {tournee.size}"

# Mesuré au morceau A : la photo de galerie Android ne portait AUCUN EXIF. Ne
# jamais dépendre de sa présence.
sans_exif = _chronique("Pacôme")
p4 = photos.deposer(sans_exif.personne_uuid, _image(2000, 1125))
assert taches.traiter_une() is True
assert Image.open(_fichier("web", f"{p4.uuid}.jpg")).size == (1600, 900)

# Effet de bord voulu : les dérivés partent SANS EXIF, donc sans GPS ni modèle
# d'appareil. C'est la version web qui circulera dans le recueil.
assert not Image.open(_fichier("web", f"{p3.uuid}.jpg")).getexif(), \
    "la version web emporte l'EXIF de l'original — donc le GPS"

print("TOUT PASSE — orientation redressée, EXIF absent toléré et non recopié")


# --- un format illisible échoue définitivement ET rend le crédit ---------- #

# *Défaut du 26 août : aucun traitant n'existait, la tâche échouait aussitôt,
# et la photo restait « en traitement » à vie — l'écran affirmait qu'on la
# préparait alors que personne ne préparait rien.*

quentin = _chronique("Quentin")
avant = photos.budget(quentin.personne_uuid).restants
faux = photos.deposer(quentin.personne_uuid,
                      b"\x89PNG\r\n\x1a\n" + b"n'importe quoi" * 40)
assert photos.budget(quentin.personne_uuid).restants == avant - 1
assert taches.traiter_une() is True

with bd.Seance() as seance:
    assert seance.get(Photo, faux.uuid).etat == "echouee"
    tache = seance.scalar(select(Tache).where(Tache.objet_uuid == faux.uuid))
    assert tache.etat == "echouee", tache.etat
    # Définitif, pas différé : un format illisible ne le sera pas davantage au
    # troisième essai, et trois tours pour rien retardent les vraies photos.
    assert tache.tentatives == 1, tache.tentatives

# EX-PHO-33 — c'est NOTRE défaut. Le crédit est rendu.
assert photos.budget(quentin.personne_uuid).restants == avant, \
    "l'échec de conversion a été décompté à l'invité"

# Idempotent : rejouer le crochet ne rend pas un second crédit.
photos.marquer_echec(faux.uuid, "rejoué")
assert photos.budget(quentin.personne_uuid).restants == avant
with bd.Seance() as seance:
    lignes = list(seance.scalars(
        select(Journal).where(Journal.objet_uuid == faux.uuid,
                              Journal.action == Journal.PHOTO_ECHOUEE)))
assert len(lignes) == 1, len(lignes)

print("TOUT PASSE — un format illisible échoue net et rend le crédit")


# --- l'échec remonte même quand AUCUN traitant n'existe ------------------- #

# C'est exactement le cas du 26 août : la tâche échoue avant tout traitant, et
# l'objet doit quand même l'apprendre.
rachel = _chronique("Rachel")
p5 = photos.deposer(rachel.personne_uuid, _image())
credit = photos.budget(rachel.personne_uuid).restants
traitant = taches._traitants.pop("conversion_image")
try:
    assert taches.traiter_une() is True
finally:
    taches._traitants["conversion_image"] = traitant

with bd.Seance() as seance:
    assert seance.get(Photo, p5.uuid).etat == "echouee", \
        "sans traitant, la photo reste en traitement à vie"
assert photos.budget(rachel.personne_uuid).restants == credit + 1

print("TOUT PASSE — sans traitant, l'échec remonte quand même jusqu'à la photo")


# --- une conversion perdue repart au démarrage ---------------------------- #

sylvain = _chronique("Sylvain")
p6 = photos.deposer(sylvain.personne_uuid, _image(2400, 1800))
# On simule un redémarrage en plein travail : la tâche disparaît, la photo
# reste en traitement. Sans reprise, elle y resterait jusqu'au 5 septembre.
with bd.Seance() as seance:
    for t in seance.scalars(select(Tache).where(Tache.objet_uuid == p6.uuid)):
        seance.delete(t)
    seance.commit()

# La reprise est appelée AU DÉMARRAGE : éprouver la fonction sans son appel
# laisserait passer le seul défaut qui compte — celui où on l'oublie dans le
# cycle de vie, et où la photo reste en traitement jusqu'au 5 septembre.
test_outils.client(main.app)          # rentre à nouveau dans le cycle de vie
with bd.Seance() as seance:
    remise = seance.scalar(select(Tache).where(
        Tache.objet_uuid == p6.uuid,
        Tache.etat.in_(("en_attente", "en_cours"))))
assert remise is not None, \
    "le démarrage n'a pas repris la conversion perdue"

assert taches.traiter_une() is True
with bd.Seance() as seance:
    assert seance.get(Photo, p6.uuid).etat == "prete"

# Ne boucle pas : une photo prête ou échouée n'est plus reprise.
assert photos.reprendre_conversions_perdues() == 0

print("TOUT PASSE — une conversion perdue repart, et la reprise ne boucle pas")


# --- une photo remplacée pendant l'attente n'écrase pas la nouvelle ------- #

# La tâche de l'ancienne peut survivre au remplacement : la convertir
# écraserait les fichiers de la nouvelle, qui portent son propre UUID — mais
# la ligne, elle, ne doit pas repasser à `prete`.
tristan = _chronique("Tristan")
ancienne = photos.deposer(tristan.personne_uuid, _image())
photos.deposer(tristan.personne_uuid, _image(2000, 1500))   # remplace
photos.convertir(ancienne.uuid)
with bd.Seance() as seance:
    assert seance.get(Photo, ancienne.uuid).etat == "traitement", \
        "la photo remplacée est repassée à prête"
    assert seance.get(Photo, ancienne.uuid).supprimee is True

print("TOUT PASSE — convertir une photo remplacée ne la ressuscite pas")


# --- l'invité voit enfin sa vignette -------------------------------------- #

vue = client.get(f"/portrait/{marc.uuid}").text
assert f'src="/photo/{marc.uuid}/vignette?v=' in vue
servie = client.get(f"/photo/{marc.uuid}/vignette")
assert servie.status_code == 200
assert servie.content == _fichier("vignettes", f"{photo.uuid}.jpg").read_bytes()

print("TOUT PASSE — la vignette arrive jusqu'à l'écran de l'invité")
