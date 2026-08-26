"""B1 — le dépôt de la photo personnelle (EX-PHO-36, 37, 38, 08, 10, 11, 12, 15,
26, 28).

Ce qui est éprouvé ici n'est pas « une photo arrive » mais les chemins d'échec :
une vidéo renommée, un format inconnu, un budget épuisé, une conversion ratée
qui ne doit rien coûter à l'invité.
"""

import html as html_module
import json
import os
import pathlib
import re
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


def _texte(html: str) -> str:
    """Replie les blancs avant de comparer.

    Jinja coupe les lignes du gabarit là où l'auteur les a coupées : « il vous
    reste 3\n       changements » ne contient pas « 3 changements ». Une
    assertion qui cherche la chaîne telle quelle éprouve la mise en forme du
    gabarit, pas ce qu'il dit. Même famille que `test_identite.texte()`, qui
    déséchappe pour la même raison.
    """
    return re.sub(r"\s+", " ", html_module.unescape(html))


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
bloc = _texte(texte.split('id="valider"')[1].split("</button>")[0])
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


# --- C1 : la quittance, quatre états -------------------------------------- #

# Sans elle, l'invité ne sait pas si sa photo est arrivée, donc il renvoie —
# et un renvoi consomme une modification. Le silence brûlait du budget.

quittance = _chronique("Gwenaëlle")
page = client.get(f"/portrait/{quittance.uuid}").text
assert "Ajouter votre photo" in page
assert "Votre photo est arrivée" not in page

# État `traitement` : reçue, pas encore préparée. C'est la fenêtre qu'EX-PHO-10
# rend inévitable, et celle où l'invité renvoyait.
depot = photos.deposer(quittance.personne_uuid, _jpeg())
page = client.get(f"/portrait/{quittance.uuid}").text
assert "Votre photo est arrivée" in page, "aucune quittance à l'état traitement"
assert "inutile de la renvoyer" in _texte(page)
bloc = _texte(page.split("Votre photo est arrivée")[1].split("</a>")[0])
assert "3 changements" in bloc, bloc          # EX-CYC-13, au moment du geste

# Le fragment interrogé par HTMX porte la même quittance : sans ça, la page
# rafraîchie toute seule pendant la génération l'effacerait.
assert "Votre photo est arrivée" in client.get(
    f"/portrait/{quittance.uuid}/etat").text

# État `prete` : la vignette. Elle ne peut pas venir de /static.
with bd.Seance() as seance:
    ligne_photo = seance.get(Photo, depot.uuid)
    ligne_photo.etat = "prete"
    ligne_photo.chemin_vignette = f"{depot.uuid}.jpg"
    seance.commit()
page = client.get(f"/portrait/{quittance.uuid}").text
assert f'src="/photo/{quittance.uuid}/vignette"' in page, page[-600:]
assert "/static/" not in page.split('class="vignette"')[1][:200]

# Le fichier n'existe pas encore (la conversion arrive en B2) : 404 franc,
# jamais une trace ni une page à moitié rendue.
assert client.get(f"/photo/{quittance.uuid}/vignette").status_code == 404

# Le second garde-fou (`is_file`) couvre le fichier absent ; SEUL le premier
# couvre `chemin_vignette` à None — sinon `dossier / None` lève un TypeError,
# donc un 500 sur une page d'invité en pleine soirée. Deux cas réels : aucune
# photo du tout, et une photo encore en conversion.
sans_photo = _chronique("Hortense")
assert client.get(f"/photo/{sans_photo.uuid}/vignette").status_code == 404, \
    "une chronique sans photo doit rendre 404, jamais une erreur serveur"
en_cours = _chronique("Isaure")
photos.deposer(en_cours.personne_uuid, _jpeg())
assert client.get(f"/photo/{en_cours.uuid}/vignette").status_code == 404, \
    "une photo encore en conversion doit rendre 404, jamais une erreur serveur"

vignettes = config.projet().dossier_medias / "photos_invites" / "vignettes"
vignettes.mkdir(parents=True, exist_ok=True)
(vignettes / f"{depot.uuid}.jpg").write_bytes(_jpeg())
servie = client.get(f"/photo/{quittance.uuid}/vignette")
assert servie.status_code == 200 and servie.content == _jpeg()

# EX-PHO-33 — un échec de CONVERSION le dit, et dit qu'il n'a rien coûté.
with bd.Seance() as seance:
    seance.get(Photo, depot.uuid).etat = "echouee"
    seance.commit()
page = client.get(f"/portrait/{quittance.uuid}").text
assert "n'a pas pu être préparée" in _texte(page)
assert "ne vous a rien coûté" in _texte(page)
assert f'href="/photo/{quittance.uuid}"' in page

print("TOUT PASSE — la quittance couvre les quatre états de la photo")


# --- les photos ne sont jamais servies publiquement ----------------------- #

# Le dossier des médias est sur le volume ; `/static` est monté publiquement.
# Les deux ne doivent jamais se rencontrer.
racine_statique = pathlib.Path(main.RACINE) / "static"
medias = config.projet().dossier_medias.resolve()
assert racine_statique.resolve() not in medias.parents and \
    medias != racine_statique.resolve(), \
    "le dossier des médias est sous /static : les photos seraient publiques"
assert client.get(f"/static/{depot.uuid}.jpg").status_code == 404
assert client.get("/static/../photos_invites/originaux/"
                  f"{depot.uuid}.jpg").status_code in (404, 400)

print("TOUT PASSE — aucune photo n'est atteignable par /static")


# --- la station photo est une offre, pas un péage ------------------------- #

# *Défaut constaté en production le 26 août.* Valider son portrait renvoyait
# vers l'écran de dépôt MÊME après une photo reçue ; le portrait gardant son
# bouton de validation, on tournait en rond sans autre sortie que « Plus tard ».

boucle = _chronique("Jonas")
bd.ajouter_bonus(boucle.uuid, {"lien": "Collègue"})
boucle = bd.lire(boucle.uuid)
assert boucle.etage == 2

# Sans photo, l'offre est faite.
saut = client.get(f"/bonus/{boucle.uuid}", follow_redirects=False)
assert saut.headers["location"] == f"/photo/{boucle.uuid}", saut.headers

# Avec photo, on sort. C'est le tour de boucle qu'on refuse.
photos.deposer(boucle.personne_uuid, _jpeg())
sortie = client.get(f"/bonus/{boucle.uuid}", follow_redirects=False)
assert sortie.headers["location"] == "/fin", \
    f"la station photo est redevenue un péage : {sortie.headers['location']}"

# Même règle au premier étage, décidée au même endroit : deux endroits qui
# tranchent séparément la même chose divergent au premier changement.
premier_etage = _chronique("Katell")
intro = client.get(f"/bonus/{premier_etage.uuid}").text
assert f'href="/photo/{premier_etage.uuid}"' in intro
photos.deposer(premier_etage.personne_uuid, _jpeg())
intro = client.get(f"/bonus/{premier_etage.uuid}").text
assert 'href="/fin"' in intro and f'href="/photo/{premier_etage.uuid}"' not in intro

print("TOUT PASSE — la photo déjà reçue ne se redemande pas : la boucle est fermée")


# --- l'écran de dépôt dit ce qui est déjà là ------------------------------ #

# Le seul chiffre affiché était celui du bouton — « il vous restera N » —, qui
# parle du futur et non de ce qui est déjà arrivé.
vierge = _chronique("Léandre")
page = _texte(client.get(f"/photo/{vierge.uuid}").text)
assert "Elle est facultative" in page
assert "Votre photo est arrivée" not in page
assert "Plus tard" in page

photos.deposer(vierge.personne_uuid, _jpeg())
page = client.get(f"/photo/{vierge.uuid}").text
lu = _texte(page)
assert "Votre photo est arrivée" in lu, "l'écran ne dit rien de la photo reçue"
assert "Il vous reste 3 changements" in lu, lu
# La sortie ne dit plus « Plus tard » quand il n'y a plus rien à remettre.
assert "Terminer" in lu and "Plus tard" not in lu
# Et le bouton dit qu'on remplace, pas qu'on valide.
assert "Remplacer" in _texte(page.split('id="valider"')[1].split("</button>")[0])

print("TOUT PASSE — l'écran de dépôt montre l'état avant le geste")
