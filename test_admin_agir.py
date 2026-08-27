"""C3 — agir : ce que l'administrateur peut faire (EX-ADM-10, EX-ADM-11).

L'assertion qui compte le plus est celle de l'idempotence : à 21 h, sur un
réseau lent, « tout rendre » sera appuyé deux fois. Des lignes de compensation
s'additionneraient et offriraient huit dépôts au lieu de quatre ; une borne
datée donne le même résultat aux deux appuis.
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
from modeles import Chronique, Journal, Photo, Tache

ADMIN = ("admin", os.environ.get("MOT_DE_PASSE_ADMIN", "essai-admin"))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", ADMIN[1])

client = test_outils.client(main.app)


def _texte(page: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(page))


def _img(largeur=800, hauteur=600) -> bytes:
    tampon = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), (90, 60, 30)).save(tampon, "JPEG")
    return tampon.getvalue()


def _chronique(prenom):
    identifiant = test_outils.creer_chronique(
        prenom, "Agir", {"metier": "veilleur", "allegeance": "La Lumière"},
        main.CODES_LIEUX, etat="prete")
    bd.enregistrer_portrait(identifiant, {
        "nom_fictif": f"{prenom} l'Ancien", "peuple": "homme",
        "portrait": "Un paragraphe.\n\nUn autre.", "indice": "Un indice.",
        "fuites_noms": [], "modele": "claude-sonnet-5", "duree_s": 6.0,
        "jetons_entree": 800, "jetons_sortie": 260})
    return bd.lire(identifiant)


# --- toutes les actions sont fermées sans mot de passe -------------------- #

ursule = _chronique("Ursule")
for chemin in ("modifier", "crediter", "photo", "supprimer", "regenerer"):
    reponse = client.post(f"/admin/chronique/{ursule.uuid}/{chemin}", data={})
    assert reponse.status_code == 401, (chemin, reponse.status_code)

print("TOUT PASSE — aucune action d'administration n'est ouverte")


# --- rendre UN crédit de photo, puis TOUT rendre -------------------------- #

# Le blocage réel : quatre dépôts faits, plus rien de possible.
for _ in range(4):
    photos.deposer(ursule.personne_uuid, _img())
assert photos.budget(ursule.personne_uuid).epuise is True

client.post(f"/admin/chronique/{ursule.uuid}/crediter",
            data={"quoi": "photo", "portee": "un"}, auth=ADMIN)
etat = photos.budget(ursule.personne_uuid)
assert etat.restants == 1 and etat.epuise is False, etat
# Le crédit rendu permet vraiment un dépôt de plus.
photos.deposer(ursule.personne_uuid, _img())
assert photos.budget(ursule.personne_uuid).epuise is True

client.post(f"/admin/chronique/{ursule.uuid}/crediter",
            data={"quoi": "photo", "portee": "tout"}, auth=ADMIN)
assert photos.budget(ursule.personne_uuid).restants == 4

print("TOUT PASSE — un crédit rendu, puis tous")


# --- et c'est idempotent, parce que la remise est une DATE ---------------- #

# Deux appuis sur « tout rendre » — le cas réel d'un réseau lent à 21 h. Des
# lignes de compensation s'additionneraient et offriraient huit dépôts.
for _ in range(3):
    client.post(f"/admin/chronique/{ursule.uuid}/crediter",
                data={"quoi": "photo", "portee": "tout"}, auth=ADMIN)
apres = photos.budget(ursule.personne_uuid)
assert apres.restants == 4, f"trois appuis ont donné {apres.restants} dépôts"
assert apres.maximum == 4

# Et le plancher tient : rendre plus de crédits qu'il n'y a eu de dépôts
# n'offre pas de dépôts supplémentaires.
vierge = _chronique("Vianney")
for _ in range(6):
    photos.crediter(vierge.personne_uuid)
assert photos.budget(vierge.personne_uuid).restants == 4

# Ce qui précède la borne ne compte plus, ce qui la suit compte.
photos.deposer(ursule.personne_uuid, _img())
assert photos.budget(ursule.personne_uuid).restants == 3

print("TOUT PASSE — la remise est une date : deux appuis valent un seul")


# --- les crédits de portrait suivent la même règle ------------------------ #

wilfried = _chronique("Wilfried")
with bd.Seance() as seance:
    for _ in range(main.MAX_GENERATIONS):
        bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                       objet_uuid=wilfried.uuid, objet_type="chronique")
    seance.commit()
# Un ÉCART, jamais une valeur absolue : la création d'une chronique de test
# journalise déjà une génération, et « == MAX_GENERATIONS » éprouverait le
# helper de test plutôt que le crédit.
reference = bd.lire(wilfried.uuid).nb_generations
assert reference >= main.MAX_GENERATIONS, reference

client.post(f"/admin/chronique/{wilfried.uuid}/crediter",
            data={"quoi": "chronique", "portee": "un"}, auth=ADMIN)
assert reference - bd.lire(wilfried.uuid).nb_generations == 1

client.post(f"/admin/chronique/{wilfried.uuid}/crediter",
            data={"quoi": "chronique", "portee": "tout"}, auth=ADMIN)
assert bd.lire(wilfried.uuid).nb_generations == 0

# **`nb_tentatives` n'est JAMAIS rendu** : c'est le garde-fou technique contre
# une chronique empoisonnée qui rappellerait l'API en boucle, pas une
# courtoisie. Une remise de crédits ne rouvre pas le portefeuille.
avant_tentatives = bd.lire(wilfried.uuid).nb_tentatives
with bd.Seance() as seance:
    bd.journaliser(seance, Journal.CHRONIQUE_TENTEE,
                   objet_uuid=wilfried.uuid, objet_type="chronique")
    seance.commit()
client.post(f"/admin/chronique/{wilfried.uuid}/crediter",
            data={"quoi": "chronique", "portee": "tout"}, auth=ADMIN)
assert bd.lire(wilfried.uuid).nb_tentatives == avant_tentatives + 1, \
    "la remise à zéro a effacé le garde-fou technique"

print("TOUT PASSE — les portraits se créditent, le garde-fou technique non")


# --- l'édition écrit, et le journal dit quoi ----------------------------- #

xavier = _chronique("Xavier")
avant_portrait = xavier.portrait
client.post(f"/admin/chronique/{xavier.uuid}/modifier", auth=ADMIN,
            data={"nom_fictif": "Xavier le Sage", "peuple": "elfe",
                  "portrait": "Texte corrigé à la main.",
                  "indice": "Nouvel indice.", "lieu": main.CODES_LIEUX[1]})
relu = bd.lire(xavier.uuid)
assert relu.nom_fictif == "Xavier le Sage"
assert relu.peuple == "elfe"
assert relu.portrait == "Texte corrigé à la main."
assert relu.lieu == main.CODES_LIEUX[1]

# Une ligne « modifiée » sans le détail ne sert à rien en octobre : ce qu'on
# voudra savoir, c'est si un portrait a été retouché, et depuis quoi.
with bd.Seance() as seance:
    trace = seance.scalar(select(Journal).where(
        Journal.objet_uuid == xavier.uuid,
        Journal.action == Journal.CHRONIQUE_MODIFIEE))
assert trace is not None
import json as _json
detail = _json.loads(trace.details_json)
assert detail["portrait"]["avant"] == avant_portrait
assert detail["portrait"]["apres"] == "Texte corrigé à la main."
assert trace.agit_pour_le_compte_de == "admin"

# Un champ hors liste est ignoré : `reponses_json` est la seule vérité
# (EX-GEN-08) et ne se corrige pas ici.
client.post(f"/admin/chronique/{xavier.uuid}/modifier", auth=ADMIN,
            data={"reponses_json": '{"metier": "pirate"}', "etat": "echouee"})
relu = bd.lire(xavier.uuid)
assert "pirate" not in (relu.reponses_json or "")
assert relu.etat == "prete", relu.etat

print("TOUT PASSE — l'édition écrit les champs permis et journalise l'écart")


# --- la suppression est douce, confirmée et réversible ------------------- #

yann = _chronique("Yann")
avant_carte = len(bd.lister())
client.post(f"/admin/chronique/{yann.uuid}/supprimer", data={}, auth=ADMIN)
with bd.Seance() as seance:
    assert seance.get(Chronique, yann.uuid).supprimee is True
    # Rien n'est effacé : `reponses_json` est la seule chose qui ne se réécrit
    # pas, et elle est intacte.
    assert seance.get(Chronique, yann.uuid).reponses_json
assert avant_carte - len(bd.lister()) == 1

fiche = client.get(f"/admin/chronique/{yann.uuid}", auth=ADMIN).text
assert "Cette chronique est masquée" in _texte(fiche)
assert "La remontrer" in fiche

client.post(f"/admin/chronique/{yann.uuid}/supprimer",
            data={"action": "restaurer"}, auth=ADMIN)
with bd.Seance() as seance:
    assert seance.get(Chronique, yann.uuid).supprimee is False
assert len(bd.lister()) == avant_carte

# Les deux boutons destructeurs demandent confirmation.
fiche = client.get(f"/admin/chronique/{yann.uuid}", auth=ADMIN).text
bloc = fiche.split('value="tout"')[1].split("</button>")[0]
assert "confirm(" in bloc, bloc
bloc = fiche.split("/supprimer")[-1]
assert "confirm(" in bloc

print("TOUT PASSE — suppression douce, confirmée, réversible")


# --- l'administrateur dépose sans consommer ------------------------------ #

zoe = _chronique("Zoé")
for _ in range(4):
    photos.deposer(zoe.personne_uuid, _img())
epuise = photos.budget(zoe.personne_uuid)
assert epuise.epuise is True

# La photo courante est déjà en « traitement » : sans retenir son UUID, on ne
# saurait pas distinguer le dépôt de l'administrateur du quatrième dépôt de
# l'invité, et le test passerait même si le dépôt avait été refusé.
avant_uuid = photos.courante(zoe.personne_uuid).uuid
reponse = client.post(f"/admin/chronique/{zoe.uuid}/photo", auth=ADMIN,
                      files={"fichier": ("f.jpg", _img(1200, 900),
                                         "image/jpeg")})
assert reponse.status_code == 200, reponse.text[:200]
# EX-ADM-10 — sans limite : le dépôt passe ET le budget n'a pas bougé.
assert photos.budget(zoe.personne_uuid).restants == epuise.restants
photo = photos.courante(zoe.personne_uuid)
assert photo is not None and photo.etat == "traitement"
assert photo.uuid != avant_uuid, \
    "le dépôt de l'administrateur a été refusé par le budget épuisé"

# Le retrait est doux et ne coûte rien non plus.
reference = photos.budget(zoe.personne_uuid).restants
client.post(f"/admin/chronique/{zoe.uuid}/photo", data={"action": "retirer"},
            auth=ADMIN)
assert photos.courante(zoe.personne_uuid) is None
with bd.Seance() as seance:
    assert seance.get(Photo, photo.uuid).supprimee is True
assert photos.budget(zoe.personne_uuid).restants == reference

print("TOUT PASSE — l'administrateur dépose et retire sans consommer")


# --- la régénération ne connaît pas de limite ---------------------------- #

alix = _chronique("Alix")
with bd.Seance() as seance:
    for _ in range(main.MAX_GENERATIONS + 2):
        bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                       objet_uuid=alix.uuid, objet_type="chronique")
    for _ in range(bd.MAX_TENTATIVES + 2):
        bd.journaliser(seance, Journal.CHRONIQUE_TENTEE,
                       objet_uuid=alix.uuid, objet_type="chronique")
    seance.commit()

def _en_file(identifiant):
    """Le témoin est la FILE, pas l'état de la chronique.

    `_lancer_generation` met en file et ne touche pas à `etat` — celui-ci ne
    bouge qu'au moment où le fil s'en saisit. Observer l'état ferait passer le
    test pour de mauvaises raisons.
    """
    with bd.Seance() as seance:
        return seance.scalar(select(Tache).where(
            Tache.type == "generation_chronique",
            Tache.objet_uuid == identifiant,
            Tache.etat.in_(("en_attente", "en_cours"))))


# L'invité est arrêté par les deux garde-fous.
client.post(f"/portrait/{alix.uuid}/regenerer", data={})
assert _en_file(alix.uuid) is None, "l'invité a franchi son quota"

# L'administrateur, non. Un appui n'est pas une boucle.
client.post(f"/admin/chronique/{alix.uuid}/regenerer", data={}, auth=ADMIN)
assert _en_file(alix.uuid) is not None, \
    "la régénération administrateur s'est heurtée au quota de l'invité"

print("TOUT PASSE — l'administrateur régénère là où l'invité est arrêté")


# --- le lieu se change, et sa conséquence est montrée -------------------- #

# Le lieu découpe les dix chapitres : le déplacer déséquilibre la répartition.
# L'effectif doit être visible À CÔTÉ du champ, sinon la conséquence ne se
# découvre qu'en octobre.
fiche = client.get(f"/admin/chronique/{xavier.uuid}", auth=ADMIN).text
choix = fiche.split('name="lieu"')[1].split("</select>")[0]
assert "convoqué(s)" in _texte(choix), choix[:300]
for code in main.CODES_LIEUX:
    assert f'value="{code}"' in choix, code

print("TOUT PASSE — le lieu se change avec son effectif sous les yeux")
