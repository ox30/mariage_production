"""La clôture du Livre et la soupape du Grand Chroniqueur.

Deux choses qui n'ont l'air de rien et qui décident du 5 septembre : que rien
ne se ferme tout seul, et qu'un invité à bout de quota ait où aller.
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
import main
import photos
import test_outils
from modeles import Chronique, Journal, Personne

ADMIN = ("admin", os.environ.get("MOT_DE_PASSE_ADMIN", "essai-admin"))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", ADMIN[1])

client = test_outils.client(main.app)


def _texte(page: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(page))


def _img():
    tampon = io.BytesIO()
    Image.new("RGB", (600, 400), (40, 60, 80)).save(tampon, "JPEG")
    return tampon.getvalue()


def _chronique(prenom):
    identifiant = test_outils.creer_chronique(
        prenom, "Soirée", {"metier": "x", "allegeance": "La Lumière"},
        main.CODES_LIEUX, etat="prete")
    bd.enregistrer_portrait(identifiant, {
        "nom_fictif": f"{prenom} le Tardif", "peuple": "homme",
        "portrait": "Un paragraphe.", "indice": "Un indice.",
        "fuites_noms": [], "modele": "claude-sonnet-5", "duree_s": 5.0,
        "jetons_entree": 800, "jetons_sortie": 250})
    return bd.lire(identifiant)


# --- le défaut est OUVERT, et c'est un renversement assumé --------------- #

# La règle du projet veut que le défaut protège quand on oublie. Ici elle
# s'inverse : oublier de fermer laisse écrire des gens bornés par leurs quotas,
# oublier d'ouvrir laisse quatre-vingt-treize personnes devant une porte close.
assert bd.phase_soiree() == "ouvert"
assert bd.livre_clos() is False

# Aucune ligne à semer : la table est vide au départ, et c'est déjà « ouvert ».
with bd.Seance() as seance:
    from modeles import EtatSoiree
    assert seance.get(EtatSoiree, 1) is None, "une ligne a été semée"

print("TOUT PASSE — rien à semer, et tout ce qui n'est pas clos est ouvert")


# --- un seul verrou, et il couvre tout ce qui écrit ---------------------- #

tardif = _chronique("Isidore")
photos.deposer(tardif.personne_uuid, _img())

# Ouvert : les écritures passent.
assert client.post(f"/portrait/{tardif.uuid}/valider",
                   follow_redirects=False).status_code == 303

client.post("/admin/soiree", auth=ADMIN, data={"phase": "lecture_seule"})
assert bd.livre_clos() is True

# **Onze routes d'écriture, une seule règle.** Le verrou vit dans le middleware
# et non dans chaque route : une route ajoutée demain est protégée sans qu'on y
# pense.
ecritures = [
    ("/valider", {}),
    (f"/portrait/{tardif.uuid}/regenerer", {}),
    (f"/portrait/{tardif.uuid}/reprendre", {}),
    (f"/portrait/{tardif.uuid}/valider", {}),
    (f"/bonus/{tardif.uuid}", {}),
    ("/identite/choisir", {"personne_uuid": tardif.personne_uuid}),
    ("/identite/libre", {"prenom": "Intrus"}),
    (f"/message/{tardif.uuid}", {"texte": "trop tard"}),
]
for chemin, donnees in ecritures:
    reponse = client.post(chemin, data=donnees, follow_redirects=False)
    assert reponse.status_code == 409, (chemin, reponse.status_code)
    assert "Le Livre est clos" in _texte(reponse.text), chemin

assert client.post(f"/photo/{tardif.uuid}",
                   files={"fichier": ("x.jpg", _img(), "image/jpeg")}
                   ).status_code == 409

# Aucun message n'a été enregistré malgré la tentative.
assert bd.messages_de(tardif.personne_uuid) == []

print("TOUT PASSE — un seul verrou ferme les onze écritures de l'invité")


# --- fermer l'écriture n'est pas fermer le site -------------------------- #

# Chacun relit sa chronique, sa photo, ses enluminures. Les GET passent tous.
for chemin in ("/", f"/portrait/{tardif.uuid}", f"/photo/{tardif.uuid}",
               "/fin"):
    assert client.get(chemin).status_code == 200, chemin

# `/entrer` reste ouvert : il faut encore pouvoir franchir la porte pour LIRE.
assert client.post("/entrer", data={"mot_de_passe": "x"},
                   follow_redirects=False).status_code != 409

# L'administrateur, lui, garde tout.
assert client.post(f"/admin/chronique/{tardif.uuid}/crediter", auth=ADMIN,
                   data={"quoi": "photo", "portee": "un"},
                   follow_redirects=False).status_code == 303

print("TOUT PASSE — la lecture reste ouverte, et l'administrateur garde tout")


# --- réversible, et rien n'est interrompu -------------------------------- #

client.post("/admin/soiree", auth=ADMIN, data={"phase": "ouvert"})
assert bd.livre_clos() is False
assert client.post(f"/portrait/{tardif.uuid}/valider",
                   follow_redirects=False).status_code == 303

# Journalisé dans les deux sens : on voudra savoir quand le Livre s'est fermé.
with bd.Seance() as seance:
    lignes = list(seance.scalars(select(Journal).where(
        Journal.action == Journal.PHASE_CHANGEE)))
assert len(lignes) == 2, len(lignes)

# Une valeur inconnue ne fait rien : la contrainte de la base n'admet que cinq
# phases, et l'on n'en emploie que deux.
bd.definir_phase("n_importe_quoi")
assert bd.phase_soiree() == "ouvert"

print("TOUT PASSE — la clôture est réversible et tracée")


# --- EX-GAL-04 : la soupape, offerte quand le budget est épuisé ---------- #

# « C'est la soupape du système, pas un lot de consolation. »
assert f'action="/message/{tardif.uuid}"' not in client.get(
    f"/portrait/{tardif.uuid}").text, \
    "la soupape est offerte alors qu'il reste des générations"

epuise = _chronique("Jocelin")
with bd.Seance() as seance:
    for _ in range(main.MAX_GENERATIONS):
        bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                       objet_uuid=epuise.uuid, objet_type="chronique")
    seance.commit()
page = client.get(f"/portrait/{epuise.uuid}").text
assert f'action="/message/{epuise.uuid}"' in page, \
    "aucune soupape alors que le budget est épuisé"
assert "Signaler au Grand Chroniqueur" in _texte(page)

# Le budget de photo épuisé l'offre aussi, sur son propre écran.
for _ in range(photos.maximum_depots()):
    photos.deposer(epuise.personne_uuid, _img())
assert photos.budget(epuise.personne_uuid).epuise
assert f'action="/message/{epuise.uuid}"' in client.get(
    f"/photo/{epuise.uuid}").text

print("TOUT PASSE — la soupape n'apparaît qu'une fois le budget épuisé")


# --- le message reste affiché, et la promesse est datée ------------------ #

client.post(f"/message/{epuise.uuid}",
            data={"texte": "J'aimerais changer ma photo, elle est floue.",
                  "sujet": "sa photo"}, follow_redirects=False)
messages = bd.messages_de(epuise.personne_uuid)
assert len(messages) == 1 and "floue" in messages[0]["texte"]

page = _texte(client.get(f"/portrait/{epuise.uuid}").text)
# Il RESTE : sans quoi l'invité le réécrira, ne sachant pas s'il est parti.
assert "elle est floue" in page
assert "Votre message est parti" in page
# EX-GAL-04 — la confirmation dit explicitement QUAND ce sera traité.
assert "avant d'écrire la Chronique principale" in page

# Borné : trois messages, dérivés du journal comme tout le reste.
for i in range(5):
    client.post(f"/message/{epuise.uuid}", data={"texte": f"encore {i}"})
assert len(bd.messages_de(epuise.personne_uuid)) == bd.MAX_MESSAGES
# Un message vide n'est pas enregistré.
assert bd.ecrire_au_chroniqueur(tardif.personne_uuid, "   ") is False

print("TOUT PASSE — le message reste affiché, et la promesse dit quand")


# --- l'administrateur les voit, et ils disparaissent une fois clos ------- #

soiree = client.get("/admin/soiree", auth=ADMIN)
assert soiree.status_code == 200
lu = _texte(soiree.text)
assert "elle est floue" in lu and "Jocelin" in lu
assert f'href="/admin/chronique/{epuise.uuid}?onglet=portrait"' in soiree.text
assert client.get("/admin/soiree").status_code == 401
assert 'href="/admin/soiree"' in client.get("/admin/invites", auth=ADMIN).text

# La fiche de la chronique porte les siens.
fiche = client.get(f"/admin/chronique/{epuise.uuid}?onglet=portrait",
                   auth=ADMIN)
assert fiche.status_code == 200

# Une fois le Livre clos : plus de formulaire. Promettre qu'on tiendra compte
# d'un message qu'on ne peut plus envoyer serait pire que de ne rien offrir.
#
# Éprouvé sur quelqu'un qui n'a ENCORE ÉCRIT AUCUN message : `epuise` a déjà
# ses trois, donc chez lui le formulaire disparaît de toute façon — on ne
# saurait pas si c'est la clôture ou le quota qui l'a retiré.
muet = _chronique("Kilian")
with bd.Seance() as seance:
    for _ in range(main.MAX_GENERATIONS):
        bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                       objet_uuid=muet.uuid, objet_type="chronique")
    seance.commit()
assert bd.messages_de(muet.personne_uuid) == []
assert f'action="/message/{muet.uuid}"' in client.get(
    f"/portrait/{muet.uuid}").text, "la soupape manque avant la clôture"

client.post("/admin/soiree", auth=ADMIN, data={"phase": "lecture_seule"})
assert f'action="/message/{muet.uuid}"' not in client.get(
    f"/portrait/{muet.uuid}").text, "la soupape survit à la clôture"
page = client.get(f"/portrait/{epuise.uuid}").text
assert f'action="/message/{epuise.uuid}"' not in page
# Mais ce qui a été écrit reste lisible.
assert "elle est floue" in _texte(page)
client.post("/admin/soiree", auth=ADMIN, data={"phase": "ouvert"})

print("TOUT PASSE — les messages remontent au Chroniqueur, et se ferment avec le Livre")


# --- la soupape est la DERNIÈRE option, pas la première ------------------ #

# *Constaté en production le 30 août :* le bouton s'offrait en tête de page,
# avant même que l'invité ait lu son portrait. On ne propose pas de réclamer à
# quelqu'un qui n'a pas encore vu ce qu'on lui a écrit.

assert bd.messages_de(muet.personne_uuid) == []
place = client.get(f"/portrait/{muet.uuid}").text
assert "Signaler au Grand Chroniqueur" in place
assert place.index("Signaler au Grand Chroniqueur") > place.index(
    "épuisé vos réécritures"), "la soupape passe avant le constat d'épuisement"
assert place.index("Signaler au Grand Chroniqueur") > place.index(
    "Un paragraphe."), "la soupape passe avant le portrait lui-même"

print("TOUT PASSE — la soupape vient après le portrait et le constat")


# --- le lien de l'administrateur mène à la chronique ACTUELLE ------------ #

# *Constaté le 30 août :* il menait à une version antérieure, masquée. Trois
# requêtes cherchaient « la chronique d'une personne », de trois façons, et
# deux sans filtre ni ordre — SQLite rendait la plus ancienne.

ancienne = _chronique("Ludivine")
with bd.Seance() as seance:
    personne_uuid = seance.get(Chronique, ancienne.uuid).personne_uuid
bd.supprimer_chronique(ancienne.uuid)          # masquée

import time as _time
_time.sleep(0.01)                              # deux dates distinctes
neuve = test_outils.creer_chronique(
    "Ludivine", "Soirée", {"metier": "y", "allegeance": "La Lumière"},
    main.CODES_LIEUX, etat="prete")
with bd.Seance() as seance:
    seance.get(Chronique, neuve).personne_uuid = personne_uuid
    seance.commit()
bd.enregistrer_portrait(neuve, {
    "nom_fictif": "Ludivine la Neuve", "peuple": "elfe",
    "portrait": "La version refaite.", "indice": "i", "fuites_noms": [],
    "modele": "claude-sonnet-5", "duree_s": 5.0,
    "jetons_entree": 800, "jetons_sortie": 250})

# L'invité, lui, ne voit que la vivante — une masquée n'existe pas pour lui.
assert bd.chronique_de_personne(personne_uuid) == neuve, \
    "l'invité est renvoyé vers une version antérieure"

with bd.Seance() as seance:
    for _ in range(main.MAX_GENERATIONS):
        bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                       objet_uuid=neuve, objet_type="chronique")
    seance.commit()
client.post(f"/message/{neuve}", data={"texte": "Deuxième essai raté."})

courrier = client.get("/admin/soiree", auth=ADMIN).text
assert f'href="/admin/chronique/{neuve}?onglet=portrait"' in courrier, \
    "le message mène à une version antérieure"
assert f'href="/admin/chronique/{ancienne.uuid}?onglet=portrait"' not in courrier

# Et la liste des invités montre la même — masquée seulement s'il n'en reste
# aucune de vivante.
liste = client.get("/admin/invites?onglet=liste", auth=ADMIN).text
assert f'href="/admin/chronique/{neuve}?onglet=portrait"' in liste
assert f'/admin/chronique/{ancienne.uuid}?onglet=portrait' not in liste

# **Deux chroniques vivantes n'existent pas**, et c'est la base qui le
# garantit : `ux_chronique_personne` est un index unique PARTIEL, posé
# `WHERE supprimee = 0`. Remontrer une masquée alors qu'une neuve existe lève
# une `IntegrityError` — la règle est donc tenue par le schéma, pas par du code
# qu'on pourrait oublier de relire.
import sqlalchemy.exc as _exc
try:
    bd.supprimer_chronique(ancienne.uuid, supprimee=False)
    raise AssertionError("deux chroniques vivantes ont été acceptées")
except _exc.IntegrityError:
    pass

# Une personne dont la SEULE chronique est masquée doit rester visible, marquée
# — sinon elle paraîtrait n'avoir jamais rien écrit.
orpheline = _chronique("Maxime")
bd.supprimer_chronique(orpheline.uuid)
liste = client.get("/admin/invites?onglet=liste", auth=ADMIN).text
assert f'href="/admin/chronique/{orpheline.uuid}?onglet=portrait"' in liste
assert "masquée" in _texte(liste)
# Mais pour l'invité, elle n'existe plus : il peut en écrire une neuve.
with bd.Seance() as seance:
    uuid_orphelin = seance.get(Chronique, orpheline.uuid).personne_uuid
assert bd.chronique_de_personne(uuid_orphelin) is None

print("TOUT PASSE — le lien mène à la chronique actuelle, jamais à l'ancienne")
