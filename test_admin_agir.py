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
import config
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


# --- tout champ de formulaire porte un `name` ---------------------------- #

# *Défaut du 27 août :* le champ de dépôt de photo de l'administrateur n'avait
# pas de `name`. Le navigateur n'envoyait donc RIEN — la galerie s'ouvrait, on
# validait, la page se rechargeait à l'identique. Mes tests postaient
# `files={"fichier": …}` directement : ils éprouvaient la ROUTE, jamais le
# formulaire. Un contrôle structurel sur tous les gabarits, une fois pour
# toutes.

import pathlib as _pathlib

# Le bon critère est « DANS un formulaire ». Hors formulaire, un champ n'est
# lu que par le JavaScript et n'a pas à porter de nom — c'est le cas du filtre
# de la liste des invités et des trois entrées de l'écran photo, qui passent
# par `FormData`. Dans un formulaire, un champ sans nom est un champ mort.
# Deux règles, parce qu'elles n'ont pas la même force.
#
# 1. **Un `<input type="file">` dans un formulaire DOIT porter un nom.** Sans
#    exception : on ne peut pas recopier un fichier dans un champ caché, donc
#    il n'existe aucune raison légitime de l'en priver. C'est le défaut exact
#    du 27 août.
# 2. Les autres champs le doivent aussi, **sauf** ceux qui portent un `data-`
#    et sont pilotés par le JavaScript — convention établie de
#    `questionnaire.html`, où la valeur visible est recopiée dans un champ
#    caché nommé (EX-QUE-17).
sans_nom, fichiers_muets = [], []
for gabarit in sorted(_pathlib.Path("templates").glob("*.html")):
    source = gabarit.read_text(encoding="utf-8")
    for bloc in re.finditer(r"<form\b.*?</form>", source, re.S):
        for champ in re.finditer(r"<(input|select|textarea)\b[^>]*>",
                                 bloc.group(0)):
            balise = champ.group(0)
            if 'type="submit"' in balise or "name=" in balise:
                continue
            if 'type="file"' in balise:
                fichiers_muets.append(f"{gabarit.name} : {balise[:70]}")
            elif "data-" not in balise:
                sans_nom.append(f"{gabarit.name} : {balise[:70]}")

assert not fichiers_muets, (
    "champ(s) de fichier sans `name` : le navigateur n'enverra rien\n  "
    + "\n  ".join(fichiers_muets))
assert not sans_nom, ("champ(s) sans `name` ni `data-` :\n  "
                      + "\n  ".join(sans_nom))

# La sonde doit pouvoir accuser : le jour où aucun gabarit ne porterait plus de
# formulaire, elle passerait au vert sans avoir rien examiné.
formulaires = sum(len(re.findall(r"<form\b", g.read_text(encoding="utf-8")))
                  for g in _pathlib.Path("templates").glob("*.html"))
assert formulaires >= 10, f"seulement {formulaires} formulaire(s) examiné(s)"

print("TOUT PASSE — aucun champ de formulaire n'est muet")


# --- le peuple se choisit dans une liste close --------------------------- #

# En texte libre, une faute de frappe crée un peuple qui n'existe pas :
# « naint » est arrivé en production le 27 août.
bertrand = _chronique("Bertrand")
fiche = client.get(f"/admin/chronique/{bertrand.uuid}", auth=ADMIN).text
choix = fiche.split('name="peuple"')[1].split("</select>")[0]
assert "<input" not in fiche.split('name="peuple"')[0][-40:], \
    "le peuple est resté un champ libre"
choix_lu = _texte(choix)
for peuple in main.CONFIG["peuples"]:
    # `Corsaire d'Umbar` porte une apostrophe, que Jinja échappe en `&#39;`.
    # Comparer la chaîne brute au HTML rendu éprouverait l'échappement et non
    # la présence du peuple.
    assert f'value="{peuple}"' in choix_lu, peuple
assert len(main.CONFIG["peuples"]) == 18

# Une valeur déjà en base et hors liste est CONSERVÉE et signalée : l'effacer
# en silence cacherait peut-être un vrai défaut de génération.
bd.modifier_chronique(bertrand.uuid, {"peuple": "naint"})
choix = client.get(f"/admin/chronique/{bertrand.uuid}",
                   auth=ADMIN).text.split('name="peuple"')[1].split("</select>")[0]
assert "naint" in choix and "hors liste" in choix, choix[:200]

print("TOUT PASSE — le peuple vient de questions.yaml, hors-liste signalé")


# --- corriger les réponses lève un drapeau, sans régénérer --------------- #

celine = _chronique("Céline")
assert bd.reponses_divergentes(celine.uuid) is False
en_file_avant = _en_file(celine.uuid)

reponse = client.post(f"/admin/chronique/{celine.uuid}/reponses", auth=ADMIN,
                      data={"reponse__metier": "cheminote de nuit",
                            "reponse__allegeance": "La Lumière"})
assert reponse.status_code == 200
relu = bd.lire(celine.uuid)
import json as _j
assert _j.loads(relu.reponses_json)["metier"] == "cheminote de nuit"

# **Aucune régénération** : deux gestes, pas un.
assert _en_file(celine.uuid) is en_file_avant or _en_file(celine.uuid) is None
assert relu.portrait == "Un paragraphe.\n\nUn autre.", "le portrait a bougé"

# Le drapeau est dérivé de deux dates du journal, jamais stocké.
assert bd.reponses_divergentes(celine.uuid) is True
assert "ont changé depuis le dernier portrait" in _texte(
    client.get(f"/admin/chronique/{celine.uuid}", auth=ADMIN).text)

# Corriger le PORTRAIT ne lève pas le drapeau : sinon il serait levé en
# permanence et on cesserait de le lire.
denis = _chronique("Denis")
bd.modifier_chronique(denis.uuid, {"portrait": "Texte retouché."})
assert bd.reponses_divergentes(denis.uuid) is False

# Et régénérer le baisse.
with bd.Seance() as seance:
    bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                   objet_uuid=celine.uuid, objet_type="chronique")
    seance.commit()
assert bd.reponses_divergentes(celine.uuid) is False

print("TOUT PASSE — corriger les réponses lève un drapeau et ne régénère rien")


# --- vider une réponse du second étage ramène à l'étage un --------------- #

# L'étage se dérive des clés présentes (EX-QUE-11) : il n'y a plus rien du
# second étage à raconter.
emile = _chronique("Émile")
bd.ajouter_bonus(emile.uuid, {"lien": "Collègue"})
assert bd.lire(emile.uuid).etage == 2
client.post(f"/admin/chronique/{emile.uuid}/reponses", auth=ADMIN,
            data={"reponse__lien": ""})
assert bd.lire(emile.uuid).etage == 1
assert "lien" not in _j.loads(bd.lire(emile.uuid).reponses_json)

# Un champ hors préfixe ne se mélange pas aux réponses.
# L'état AVANT l'action, jamais une valeur absolue : `ajouter_bonus` a relancé
# une génération plus haut, et « == prete » éprouverait cette relance.
etat_avant = bd.lire(emile.uuid).etat
cles_avant = set(_j.loads(bd.lire(emile.uuid).reponses_json))
client.post(f"/admin/chronique/{emile.uuid}/reponses", auth=ADMIN,
            data={"etat": "echouee", "uuid": "n'importe quoi"})
relu = bd.lire(emile.uuid)
assert relu.etat == etat_avant, (etat_avant, relu.etat)
assert set(_j.loads(relu.reponses_json)) == cles_avant

print("TOUT PASSE — l'étage suit les réponses, et rien ne s'y glisse")


# --- l'URL d'une photo change quand la photo change ---------------------- #

# *Défaut du 27 août :* l'URL porte l'UUID de la CHRONIQUE, pas celui du
# fichier. Identique avant et après un remplacement, le navigateur réaffichait
# la précédente — contourné au Ctrl+F5.

felix = _chronique("Félix")
premiere = photos.deposer(felix.personne_uuid, _img())
with bd.Seance() as seance:
    ligne = seance.get(Photo, premiere.uuid)
    ligne.etat, ligne.chemin_vignette = "prete", f"{premiere.uuid}.jpg"
    seance.commit()

def _source_vignette(page):
    trouve = re.search(r'src="(/(?:admin/)?photo/[^"]+)"', page)
    assert trouve, "aucune vignette dans la page"
    return trouve.group(1)

avant_url = _source_vignette(client.get(f"/portrait/{felix.uuid}").text)
assert "?v=" in avant_url, avant_url

seconde = photos.deposer(felix.personne_uuid, _img(1000, 750))
with bd.Seance() as seance:
    ligne = seance.get(Photo, seconde.uuid)
    ligne.etat, ligne.chemin_vignette = "prete", f"{seconde.uuid}.jpg"
    seance.commit()
apres_url = _source_vignette(client.get(f"/portrait/{felix.uuid}").text)
assert apres_url != avant_url, \
    f"l'URL n'a pas bougé après remplacement : {apres_url}"

# La fiche d'administration porte la même empreinte.
fiche_url = _source_vignette(
    client.get(f"/admin/chronique/{felix.uuid}", auth=ADMIN).text)
assert "?v=" in fiche_url, fiche_url

# Et l'en-tête autorise le cache, ce que seule l'empreinte rend sans danger.
vignettes = config.projet().dossier_medias / "photos_invites" / "vignettes"
vignettes.mkdir(parents=True, exist_ok=True)
(vignettes / f"{seconde.uuid}.jpg").write_bytes(_img())
servie = client.get(f"/photo/{felix.uuid}/vignette")
assert servie.status_code == 200
assert "private" in servie.headers.get("cache-control", ""), servie.headers

print("TOUT PASSE — l'URL d'une photo porte son empreinte")


# --- retoucher le personnage à la main baisse le drapeau ----------------- #

gaelle = _chronique("Gaëlle")
with bd.Seance() as seance:
    bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                   objet_uuid=gaelle.uuid, objet_type="chronique")
    seance.commit()
client.post(f"/admin/chronique/{gaelle.uuid}/reponses", auth=ADMIN,
            data={"reponse__metier": "veilleur de nuit"})
assert bd.reponses_divergentes(gaelle.uuid) is True

# Corriger le portrait à la main, c'est mettre le portrait en accord soi-même.
bd.modifier_chronique(gaelle.uuid, {"portrait": "Texte remis en accord."})
assert bd.reponses_divergentes(gaelle.uuid) is False, \
    "retoucher le portrait n'a pas baissé le drapeau"

# Le nom, le peuple et l'indice comptent aussi.
for champ, valeur in (("nom_fictif", "Gaëlle la Veilleuse"),
                      ("peuple", "elfe"), ("indice", "Autre indice.")):
    client.post(f"/admin/chronique/{gaelle.uuid}/reponses", auth=ADMIN,
                data={"reponse__metier": f"veilleur — {champ}"})
    assert bd.reponses_divergentes(gaelle.uuid) is True, champ
    bd.modifier_chronique(gaelle.uuid, {champ: valeur})
    assert bd.reponses_divergentes(gaelle.uuid) is False, champ

# **Le lieu, non** : il n'est pas dérivé des réponses, il est assigné.
client.post(f"/admin/chronique/{gaelle.uuid}/reponses", auth=ADMIN,
            data={"reponse__metier": "veilleur des quais"})
bd.modifier_chronique(gaelle.uuid, {"lieu": main.CODES_LIEUX[2]})
assert bd.reponses_divergentes(gaelle.uuid) is True, \
    "changer le lieu a fait taire un drapeau qu'il ne concerne pas"

# Un enregistrement qui ne change RIEN ne baisse rien non plus.
bd.modifier_chronique(gaelle.uuid, {"portrait": bd.lire(gaelle.uuid).portrait})
assert bd.reponses_divergentes(gaelle.uuid) is True

print("TOUT PASSE — retoucher le personnage baisse le drapeau, pas le lieu")


# --- une réponse qui n'atteint pas le modèle ne périme rien -------------- #

# « Que souhaites-tu aux mariés » est montré tel quel aux mariés (usage
# `revelation`) et n'entre jamais dans le prompt : la modifier ne change pas le
# personnage, donc ne périme pas son portrait.
assert "souhait" in bd.CLES_HORS_PORTRAIT, bd.CLES_HORS_PORTRAIT
assert "destin" in bd.CLES_HORS_PORTRAIT      # usage `chapitre`
assert "metier" not in bd.CLES_HORS_PORTRAIT
# Dérivé de questions.yaml, jamais écrit en dur.
assert bd.CLES_HORS_PORTRAIT == {
    q["cle"] for bloc in ("obligatoires", "bonus") for q in main.CONFIG[bloc]
    if q.get("usage", "portrait") in ("revelation", "chapitre")}

hugues = _chronique("Hugues")
with bd.Seance() as seance:
    bd.journaliser(seance, Journal.CHRONIQUE_GENEREE,
                   objet_uuid=hugues.uuid, objet_type="chronique")
    seance.commit()
client.post(f"/admin/chronique/{hugues.uuid}/reponses", auth=ADMIN,
            data={"reponse__souhait": "Une vie longue et douce."})
assert _j.loads(bd.lire(hugues.uuid).reponses_json)["souhait"] \
    == "Une vie longue et douce.", "la réponse n'a pas été enregistrée"
assert bd.reponses_divergentes(hugues.uuid) is False, \
    "modifier le vœu aux mariés a levé le drapeau à tort"

# Mais mélangée à une réponse qui compte, elle ne masque rien.
client.post(f"/admin/chronique/{hugues.uuid}/reponses", auth=ADMIN,
            data={"reponse__souhait": "Encore autre chose.",
                  "reponse__objet": "une lanterne"})
assert bd.reponses_divergentes(hugues.uuid) is True

print("TOUT PASSE — le vœu aux mariés ne périme pas le portrait")
