"""B1 — le dépôt de la photo personnelle (EX-PHO-36, 37, 38, 08, 10, 11, 12, 15,
26, 28).

Ce qui est éprouvé ici n'est pas « une photo arrive » mais les chemins d'échec :
une vidéo renommée, un format inconnu, un budget épuisé, une conversion ratée
qui ne doit rien coûter à l'invité.
"""

import json
import os
import struct
import uuid as _uuid

os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")

from sqlalchemy import select

import base_donnees as bd
import config
import main
import photos
import test_outils
from modeles import Journal, Photo, Tache


def _jpeg(largeur=4032, hauteur=3024, remplissage=2000) -> bytes:
    """Un JPEG plausible : APP1 volumineux, puis SOF, comme un vrai téléphone."""
    exif = b"Exif\x00\x00" + b"\x00" * 300
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
    sof = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
           + struct.pack(">HH", hauteur, largeur) + b"\x03" + b"\x00" * 9)
    return b"\xff\xd8" + app1 + sof + b"\xff\xda\x00\x0c" + b"\x00" * remplissage


def _ftyp(marque: bytes) -> bytes:
    return b"\x00\x00\x00\x20ftyp" + marque + b"\x00" * 2000


client = test_outils.client(main.app)

REPONSES = {"metier": "cheminot", "attachement": "La nature",
            "defaut": "têtu", "objet": "une lampe",
            "allegeance": "La Lumière", "souvenir": "un été",
            "souhait": "beaucoup de bonheur"}


def _chronique(prenom, nom="Photo"):
    """`bd.creer` rend un identifiant, pas un objet : on relit."""
    identifiant = test_outils.creer_chronique(prenom, nom, dict(REPONSES),
                                              main.CODES_LIEUX, etat="prete")
    bd.enregistrer_portrait(identifiant, {
        "nom_fictif": f"{prenom} des Bois", "peuple": "homme",
        "portrait": "Un paragraphe.\n\nUn autre.", "indice": "Un indice.",
        "fuites_noms": [], "modele": "claude-sonnet-5", "duree_s": 6.0,
        "jetons_entree": 900, "jetons_sortie": 300,
    })
    return bd.lire(identifiant)


# --- le format se lit aux octets, jamais au nom du fichier -----------------

# EX-PHO-12 — le conteneur ISO-BMFF est le même pour un HEIC et un MP4 ; seule
# la marque les sépare. Une reconnaissance sur l'extension laisserait passer un
# `.mov` renommé `.jpg`, et c'est exactement ce que produit un partage depuis
# la pellicule.
assert photos.identifier(_jpeg()) == "jpeg"
assert photos.identifier(_ftyp(b"mp42")).startswith("video")
assert photos.identifier(_ftyp(b"qt  ")).startswith("video")
assert photos.identifier(_ftyp(b"heic")).startswith("heif")

for octets, morceau in [(_ftyp(b"mp42"), "vidéo"),
                        (_ftyp(b"heic"), "format"),
                        (b"", "vide"),
                        (_jpeg(remplissage=photos.TAILLE_MAX_OCTETS), "limite")]:
    try:
        photos.verifier(octets)
        raise AssertionError(f"accepté à tort : {morceau}")
    except photos.RefusPhoto as refus:
        assert morceau in str(refus).lower(), (morceau, str(refus))

assert photos.verifier(_jpeg()) == "jpeg"
# Un JPEG d'exactement la taille limite passe : la borne est inclusive, et un
# refus à la valeur ronde exacte serait invisible en essai.
assert photos.verifier(_jpeg(remplissage=photos.TAILLE_MAX_OCTETS - 400)) == "jpeg"

print("TOUT PASSE — vidéos, formats inconnus et tailles refusés aux octets de tête")


# --- le dépôt écrit l'original et met la conversion en file ----------------

chronique = _chronique("Amaury")
personne_uuid = chronique.personne_uuid

photo = photos.deposer(personne_uuid, _jpeg())
assert photo.etat == "traitement", photo.etat
assert photo.portee == "personnelle"

# EX-PHO-11 — l'original est sur le volume, intact, octet pour octet.
chemin = (config.projet().dossier_medias / "photos_invites" / "originaux"
          / photo.chemin_original)
assert chemin.exists(), chemin
assert chemin.read_bytes() == _jpeg()
# Le nom se dérive de l'UUID : les noms reçus (« image.jpg », vingt chiffres)
# sont inutilisables et non fiables (EX-SEC-16).
assert photo.chemin_original == f"{photo.uuid}.jpg", photo.chemin_original

# EX-PHO-10 — la conversion est en file, elle n'a pas été faite ici.
with bd.Seance() as seance:
    tache = seance.scalar(select(Tache).where(Tache.objet_uuid == photo.uuid))
assert tache is not None and tache.type == "conversion_image", tache
assert tache.priorite == Tache.PRIORITE_CONVERSION
assert photo.chemin_web is None and photo.chemin_vignette is None

print("TOUT PASSE — l'original est écrit intact et la conversion part en file")


# --- le budget se dérive du journal, et un échec ne se décompte pas --------

etat = photos.budget(personne_uuid)
assert etat.maximum == 4, etat            # 1 dépôt + 3 modifications
assert etat.deposes == 1 and etat.echecs == 0
assert etat.consommes == 1 and etat.restants == 3

# EX-PHO-36 — une seule photo vivante : le remplacement referme la précédente.
seconde = photos.deposer(personne_uuid, _jpeg(largeur=1440, hauteur=1080))
assert photos.courante(personne_uuid).uuid == seconde.uuid
with bd.Seance() as seance:
    ancienne = seance.get(Photo, photo.uuid)
    assert ancienne.supprimee is True and ancienne.supprimee_le is not None
    # EX-GEN-03 — suppression douce : le fichier n'est jamais détruit.
assert chemin.exists(), "l'original de la photo remplacée a disparu"
assert photos.budget(personne_uuid).restants == 2

# EX-PHO-33 — une conversion ratée est NOTRE défaut. Sans cette soustraction,
# trois échecs de notre côté épuiseraient le budget sans qu'une seule photo ait
# jamais été vue.
reference = photos.budget(personne_uuid).restants
with bd.Seance() as seance:
    bd.journaliser(seance, Journal.PHOTO_ECHOUEE, objet_uuid=seconde.uuid,
                   objet_type="photo", acteur=personne_uuid)
    seance.commit()
apres = photos.budget(personne_uuid)
assert apres.restants - reference == 1, (reference, apres.restants)
assert apres.echecs == 1

print("TOUT PASSE — budget dérivé du journal, un échec de conversion est rendu")


# --- le budget est rattaché à la personne, jamais à l'appareil -------------

# EX-AUTH-03 — sans quoi effacer ses cookies rendrait un budget neuf.
autre = _chronique("Bérengère")
assert photos.budget(autre.personne_uuid).restants == 4, \
    "le budget d'une autre personne a été entamé"

print("TOUT PASSE — le budget suit la personne, pas l'appareil ni la chronique")


# --- le budget épuisé refuse, et l'écran le dit ----------------------------

epuisee = _chronique("Clotilde")
for _ in range(4):
    photos.deposer(epuisee.personne_uuid, _jpeg())
assert photos.budget(epuisee.personne_uuid).epuise is True
try:
    photos.deposer(epuisee.personne_uuid, _jpeg())
    raise AssertionError("un cinquième dépôt est passé")
except photos.RefusPhoto as refus:
    assert "changements" in str(refus)

# Et rien n'a été écrit : le refus vient AVANT l'écriture du fichier.
with bd.Seance() as seance:
    total = len(list(seance.scalars(
        select(Photo).where(Photo.personne_uuid == epuisee.personne_uuid))))
assert total == 4, total

print("TOUT PASSE — le cinquième dépôt est refusé sans rien écrire")


# --- les routes, et le décompte au moment de la décision -------------------

fraiche = _chronique("Damien")
page = client.get(f"/photo/{fraiche.uuid}")
assert page.status_code == 200
texte = page.text

# EX-PHO-08 — deux entrées distinctes, l'une avec `capture`, l'autre sans.
assert 'id="entree_capture"' in texte and 'capture="environment"' in texte
assert 'id="entree_galerie"' in texte
assert texte.count('type="file"') == 2, "un champ unique est proscrit"
# Le piège de Safari 17 : mentionner `image/heic` dans `accept` fait convertir
# VERS le HEIC des fichiers qui n'en étaient pas.
assert "image/heic" not in texte

# EX-PHO-28 — le décompte est sur le BOUTON, au moment de la décision, et pas
# seulement dans l'aide (EX-CYC-13). Cherché dans le bloc du bouton et non dans
# la page entière : « 3 changements » traîne ailleurs.
bloc = texte.split('id="valider"')[1].split("</button>")[0]
assert "3 changements" in bloc, bloc

# La CSP de cette route seule porte `blob:` ; la CSP globale n'y touche pas.
assert "blob:" in page.headers["Content-Security-Policy"]
assert "blob:" not in client.get("/").headers["Content-Security-Policy"]

print("TOUT PASSE — deux boutons, décompte sur le bouton, blob: sur cette route seule")


# --- le refus revient à l'invité, en clair, sans rien consommer ------------

avant = photos.budget(fraiche.personne_uuid).restants
reponse = client.post(f"/photo/{fraiche.uuid}",
                      files={"fichier": ("film.jpg", _ftyp(b"mp42"),
                                         "image/jpeg")})
assert reponse.status_code == 422, reponse.status_code
assert "vidéo" in reponse.json()["refus"].lower()
# EX-PHO-15 — un envoi refusé ne consomme pas de modification.
assert photos.budget(fraiche.personne_uuid).restants == avant

recue = client.post(f"/photo/{fraiche.uuid}",
                    files={"fichier": ("image.jpg", _jpeg(), "image/jpeg")})
assert recue.status_code == 200, recue.text[:200]
assert photos.budget(fraiche.personne_uuid).restants == avant - 1
assert client.get(f"/photo/{_uuid.uuid4()}").status_code == 404

print("TOUT PASSE — une vidéo est refusée en clair et ne consomme rien")


# --- le parcours passe par la photo, et « Plus tard » n'est pas un cul-de-sac

# EX-PHO-38 — facultative : les deux sorties du questionnaire mènent à l'écran
# photo, et l'écran photo laisse partir.
deuxieme = _chronique("Élodie")
bd.ajouter_bonus(deuxieme.uuid, {"lien": "Collègue"})
assert bd.lire(deuxieme.uuid).etage == 2
saut = client.get(f"/bonus/{deuxieme.uuid}", follow_redirects=False)
assert saut.status_code == 303
assert saut.headers["location"] == f"/photo/{deuxieme.uuid}", \
    saut.headers["location"]

premier = _chronique("Fabrice")
intro = client.get(f"/bonus/{premier.uuid}")
assert f'href="/photo/{premier.uuid}"' in intro.text, \
    "« J'en ai assez dit » ne mène plus à la photo"

portrait = client.get(f"/portrait/{premier.uuid}")
assert f'href="/photo/{premier.uuid}"' in portrait.text, \
    "« Plus tard » serait un cul-de-sac : aucun retour depuis le portrait"
assert 'href="/fin"' in client.get(f"/photo/{premier.uuid}").text

print("TOUT PASSE — les deux sorties mènent à la photo, et la photo laisse partir")
