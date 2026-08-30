"""D1 — le Gardien des chroniques perdues (EX-CDT-12 à EX-CDT-19).

Ce qui est éprouvé ici, au-delà de « le bouton apparaît » : que le rôle se
dérive et ne se déclare pas, qu'un marié ne devienne jamais Gardien par une
coche oubliée, qu'aucun Gardien ne puisse lire les enluminures d'une autre
table, et qu'un échec de conversion rende le crédit **au budget qui a payé**.
"""

import html as html_module
import io
import os
import re

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
from modeles import Chronique, Journal, Personne, Photo, TableGroupe

ADMIN = ("admin", os.environ.get("MOT_DE_PASSE_ADMIN", "essai-admin"))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", ADMIN[1])

client = test_outils.client(main.app)


def _texte(page: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(page))


def _img(largeur=900, hauteur=700) -> bytes:
    tampon = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), (60, 80, 100)).save(tampon, "JPEG")
    return tampon.getvalue()


def _table(code, nom):
    with bd.Seance() as seance:
        table = TableGroupe(code=code, nom=nom, ordre=int(code))
        seance.add(table)
        seance.commit()
        return table.uuid


def _invite(prenom, table_uuid=None, responsable=False, marie=False):
    """Une personne, puis sa chronique — l'ordre compte, la seconde cite la
    première."""
    with bd.Seance() as seance:
        personne = Personne(prenom=prenom, nom="Gardien", genre="masculin",
                            table_uuid=table_uuid, est_responsable=responsable,
                            est_marie=marie, source="import")
        seance.add(personne)
        seance.commit()
        personne_uuid = personne.uuid
    identifiant = test_outils.creer_chronique(
        prenom, "Gardien", {"metier": "x", "allegeance": "La Lumière"},
        main.CODES_LIEUX, etat="prete")
    with bd.Seance() as seance:
        chronique = seance.get(Chronique, identifiant)
        orpheline = chronique.personne_uuid
        chronique.personne_uuid = personne_uuid
        seance.commit()
    bd.enregistrer_portrait(identifiant, {
        "nom_fictif": f"{prenom} le Veilleur", "peuple": "homme",
        "portrait": "Un paragraphe.", "indice": "Un indice.",
        "fuites_noms": [], "modele": "claude-sonnet-5", "duree_s": 5.0,
        "jetons_entree": 800, "jetons_sortie": 250})
    return bd.lire(identifiant)


table_a = _table("3", "Andúril")
table_b = _table("4", "Narsil")

gardien = _invite("Alaric", table_a, responsable=True)
ordinaire = _invite("Blaise", table_a)
autre_gardien = _invite("Cyprien", table_b, responsable=True)


# --- le rôle se dérive, et trois conditions le referment ------------------ #

assert bd.table_gardee(gardien.personne_uuid).uuid == table_a
assert bd.table_gardee(ordinaire.personne_uuid) is None

# **Un marié n'est jamais Gardien**, même si la coche traîne dans le tableur :
# il se mariera ce soir-là, et sa table finirait à zéro enluminure sans que
# personne s'en aperçoive. Le défaut sûr est celui qui protège quand on oublie.
marie_coche = _invite("Damien", table_b, responsable=True, marie=True)
assert bd.table_gardee(marie_coche.personne_uuid) is None, \
    "un marié coché responsable est devenu Gardien"

# Désigné Gardien sans table — le cas de la saisie libre. À DIRE, jamais à
# taire : le rôle disparaîtrait en silence.
apatride = _invite("Eudes", None, responsable=True)
assert bd.table_gardee(apatride.personne_uuid) is None
assert bd.est_gardien_sans_table(apatride.personne_uuid) is True
assert bd.est_gardien_sans_table(ordinaire.personne_uuid) is False

print("TOUT PASSE — le rôle se dérive, marié et sans-table exclus")


# --- il apprend qu'il l'est, trois fois ---------------------------------- #

# Depuis qu'EX-AUTH-08 a été réécrite, le rôle n'arrive plus par un carton
# remis en main propre : sans annonce, personne ne saurait qu'il l'est.

# 1. Une page à traverser, juste après s'être reconnu.
avant = client.get(f"/gardien-avant/{gardien.personne_uuid}")
assert avant.status_code == 200
lu = _texte(avant.text)
assert "Gardien des chroniques perdues" in lu
assert "Andúril" in lu
assert "Suivant" in lu
# On ANNONCE, on ne détourne pas : « Suivant » mène au questionnaire ordinaire.
assert f'href="/questionnaire/{gardien.personne_uuid}"' in avant.text

# Un invité ordinaire n'y a rien à faire.
assert client.get(f"/gardien-avant/{ordinaire.personne_uuid}",
                  follow_redirects=False).status_code == 303

# 2. Le bandeau, tout du long.
portrait = client.get(f"/portrait/{gardien.uuid}").text
assert "bandeau-gardien" in portrait, "le bandeau ne suit pas le Gardien"
assert "Andúril" in _texte(portrait)
assert f'href="/enluminures/{gardien.uuid}"' in portrait
assert "bandeau-gardien" not in client.get(f"/portrait/{ordinaire.uuid}").text

# Le Gardien sans table est prévenu, plutôt que laissé devant un rôle muet.
assert "aucune table ne vous est rattachée" in _texte(
    client.get(f"/portrait/{apatride.uuid}").text)

# 3. Le rappel après « C'est bien moi », une fois la photo passée.
# `/bonus` ne REDIRIGE qu'à l'étage 2 ; à l'étage 1 il rend l'intro avec son
# lien de sortie. Les deux passent par `_apres_le_portrait`, donc on éprouve
# les deux formes plutôt que la seule qui arrangeait le test.
photos.deposer(gardien.personne_uuid, _img())
assert f'href="/gardien/{gardien.uuid}"' in client.get(
    f"/bonus/{gardien.uuid}").text
photos.deposer(ordinaire.personne_uuid, _img())
intro_ordinaire = client.get(f"/bonus/{ordinaire.uuid}").text
assert 'href="/fin"' in intro_ordinaire
assert "/gardien/" not in intro_ordinaire

bd.ajouter_bonus(gardien.uuid, {"lien": "Cousin"})
saut = client.get(f"/bonus/{gardien.uuid}", follow_redirects=False)
assert saut.status_code == 303
assert saut.headers["location"] == f"/gardien/{gardien.uuid}", saut.headers

rappel = _texte(client.get(f"/gardien/{gardien.uuid}").text)
assert "Cinq enluminures" in rappel and "Andúril" in rappel

print("TOUT PASSE — page d'annonce, bandeau permanent, rappel après validation")


# --- l'écran de capture, et lui seul -------------------------------------- #

ecran = client.get(f"/enluminures/{gardien.uuid}")
assert ecran.status_code == 200
lu = _texte(ecran.text)
# EX-CDT-19 — chez lui, et chez lui seulement, l'appareil est « la boîte à
# capturer les dessins ». L'invité ordinaire, lui, fait tirer son portrait.
assert "boîte à capturer les dessins" in lu
assert "boîte à capturer" not in _texte(client.get(f"/photo/{ordinaire.uuid}").text)
# EX-PHO-26 — l'aperçu local exige `blob:`, absent de la CSP du projet.
assert "blob:" in ecran.headers["Content-Security-Policy"]
# EX-CDT-15 — les trois compteurs en en-tête, ensemble.
assert "0 sur 5" in lu and "0 envoi" in lu and "0 suppression" in lu

# EX-CDT-16 — aucun droit sur les objets d'autrui. Le bouton absent ne suffit
# pas : une adresse se recopie.
refus = client.get(f"/enluminures/{ordinaire.uuid}")
assert refus.status_code == 403, refus.status_code
assert "Ce n'est pas votre office" in _texte(refus.text)
assert client.post(f"/enluminures/{ordinaire.uuid}",
                   files={"fichier": ("x.jpg", _img(), "image/jpeg")}
                   ).status_code == 403

print("TOUT PASSE — la capture n'est ouverte qu'au Gardien, avec son vocabulaire")


# --- l'enluminure suit le chemin de la photo, sur un autre budget --------- #

perso_avant = photos.budget(gardien.personne_uuid).restants
depot = client.post(f"/enluminures/{gardien.uuid}",
                    files={"fichier": ("e.jpg", _img(), "image/jpeg")})
assert depot.status_code == 200, depot.text[:200]

with bd.Seance() as seance:
    photo = seance.get(Photo, depot.json()["photo"])
    assert photo.portee == "table" and photo.table_uuid == table_a
    assert photo.personne_uuid == gardien.personne_uuid
    assert photo.etat == "traitement"

budget = photos.budget_table(table_a)
assert (budget.affichees, budget.envois, budget.suppressions) == (1, 1, 0), budget
# Les deux budgets sont étanches : une enluminure ne coûte pas une photo
# personnelle.
assert photos.budget(gardien.personne_uuid).restants == perso_avant
assert photos.budget_table(table_b).envois == 0, "le budget a fui vers l'autre table"

# Même chemin, donc même conversion : la tâche est en file comme pour une
# photo personnelle.
_ = [taches.traiter_une() for _ in range(6)]
with bd.Seance() as seance:
    assert seance.get(Photo, depot.json()["photo"]).etat == "prete"

print("TOUT PASSE — l'enluminure suit le chemin de la photo, sur son budget")


# --- une enluminure ne se lit pas depuis une autre table ----------------- #

photo_uuid = depot.json()["photo"]
vignettes = config.projet().dossier_medias / "photos_invites" / "vignettes"
assert (vignettes / f"{photo_uuid}.jpg").is_file()

servie = client.get(f"/enluminure/{gardien.uuid}/{photo_uuid}")
assert servie.status_code == 200
# `?v=` sur l'adresse : sans empreinte, le navigateur rendrait la précédente.
assert f'/enluminure/{gardien.uuid}/{photo_uuid}?v=' in client.get(
    f"/enluminures/{gardien.uuid}").text

# Le Gardien de l'AUTRE table n'y accède pas — une table n'est pas moins
# « autrui » qu'une personne (EX-CDT-16).
assert client.get(
    f"/enluminure/{autre_gardien.uuid}/{photo_uuid}").status_code == 404
assert client.get(
    f"/enluminure/{ordinaire.uuid}/{photo_uuid}").status_code == 403

print("TOUT PASSE — une enluminure ne se lit que depuis sa propre table")


# --- un échec de conversion rend le crédit au budget QUI A PAYÉ ---------- #

# **Le piège.** `marquer_echec` créditait la personne : le Gardien aurait gagné
# un dépôt de photo personnelle et sa table en aurait perdu un. Faux dans les
# deux sens, et silencieux.
perso_reference = photos.budget(gardien.personne_uuid).restants
envois_avant = photos.budget_table(table_a).envois

illisible = client.post(f"/enluminures/{gardien.uuid}",
                        files={"fichier": ("k.png",
                                           b"\x89PNG\r\n\x1a\n" + b"nawak" * 40,
                                           "image/png")})
assert illisible.status_code == 200
assert photos.budget_table(table_a).envois == envois_avant + 1
_ = [taches.traiter_une() for _ in range(6)]

with bd.Seance() as seance:
    assert seance.get(Photo, illisible.json()["photo"]).etat == "echouee"
assert photos.budget_table(table_a).envois == envois_avant, \
    "l'échec de conversion a été décompté à la table"
assert photos.budget(gardien.personne_uuid).restants == perso_reference, \
    "l'échec d'une enluminure a crédité le budget PERSONNEL du Gardien"

with bd.Seance() as seance:
    trace = seance.scalar(select(Journal).where(
        Journal.objet_uuid == table_a,
        Journal.action == Journal.ENLUMINURE_ECHOUEE))
assert trace is not None, "l'échec n'est pas journalisé sur la table"

print("TOUT PASSE — l'échec rend le crédit à la table, jamais à la personne")


# --- les trois budgets s'emboîtent et ferment ---------------------------- #

# Cinq affichées plus cinq suppressions font dix envois : les trois lient en
# même temps. Arrivé à cinq, il faut supprimer pour ajouter.
while photos.budget_table(table_a).affichees < 5:
    reponse = client.post(f"/enluminures/{gardien.uuid}",
                          files={"fichier": ("e.jpg", _img(), "image/jpeg")})
    assert reponse.status_code == 200, reponse.text[:200]

budget = photos.budget_table(table_a)
assert budget.affichees == 5 and budget.peut_deposer is False
assert budget.restantes == 0

sixieme = client.post(f"/enluminures/{gardien.uuid}",
                      files={"fichier": ("e.jpg", _img(), "image/jpeg")})
assert sixieme.status_code == 422
assert "cinq enluminures" in sixieme.json()["refus"]
assert photos.budget_table(table_a).affichees == 5

# L'écran le dit, plutôt que d'offrir un bouton qui refusera.
plein = _texte(client.get(f"/enluminures/{gardien.uuid}").text)
assert "5 sur 5" in plein and "Le compte y est" in plein
assert "boîte à capturer les dessins" not in plein

print("TOUT PASSE — cinq affichées ferment le dépôt, et l'écran le dit")


# --- l'accueil porte toutes les portes ouvertes -------------------------- #

# *Constaté en production le 30 août :* un Gardien qui avait fini son parcours
# revenait à l'accueil et n'y trouvait que « Retrouver mon personnage ». Aucune
# porte vers ses enluminures — il quittait le site et n'y revenait pas.

def _reconnaitre(chronique):
    """Pose le cookie d'appareil, comme le fait le choix d'identité."""
    with bd.Seance() as seance:
        personne_uuid = seance.get(Chronique, chronique.uuid).personne_uuid
    reponse = client.post("/identite/choisir",
                          data={"personne_uuid": personne_uuid,
                                "intention": "revoir"},
                          follow_redirects=False)
    assert reponse.status_code in (200, 303), reponse.status_code


_reconnaitre(gardien)
menu = client.get("/").text
assert f'href="/portrait/{gardien.uuid}"' in menu
assert f'href="/photo/{gardien.uuid}"' in menu, "la photo n'a pas de porte"
assert f'href="/enluminures/{gardien.uuid}"' in menu, \
    "le Gardien n'a aucune porte vers ses enluminures depuis l'accueil"
assert "Andúril" in _texte(menu)

# L'invité ordinaire a ses deux portes, pas la troisième.
_reconnaitre(ordinaire)
menu = client.get("/").text
assert f'href="/photo/{ordinaire.uuid}"' in menu
assert "/enluminures/" not in menu, "un invité ordinaire se voit offrir les enluminures"

print("TOUT PASSE — l'accueil porte la chronique, la photo et les enluminures")


# --- la fin du parcours n'est pas la fin de la soirée -------------------- #

# « Recommencer avec quelqu'un d'autre » venait du kiosque, où l'on passe
# l'appareil au suivant. Sur son propre téléphone, la phrase invite à partir.
_reconnaitre(gardien)
fin = client.get("/fin").text
lu = _texte(fin)
assert "Recommencer avec quelqu'un d'autre" not in lu
assert "Retour à l'accueil" in lu
assert f'href="/enluminures/{gardien.uuid}"' in fin, \
    "le Gardien quitte la soirée sans porte vers sa charge"
assert "Gardien" in lu and "Andúril" in lu

_reconnaitre(ordinaire)
fin_ordinaire = client.get("/fin").text
assert "Retour à l'accueil" in _texte(fin_ordinaire)
assert "/enluminures/" not in fin_ordinaire

# Sans appareil reconnu, la page tient quand même — elle est publique.
sans_cookie = test_outils.client(main.app)
assert sans_cookie.get("/fin").status_code == 200

print("TOUT PASSE — la fin renvoie à l'accueil, et rappelle sa charge au Gardien")
