"""E — le questionnaire réduit des mariés (EX-MAR-02, EX-MAR-03, EX-MAR-04).

Trois questions interrogent l'invité **sur** les mariés. Posées aux mariés
eux-mêmes le soir de leur mariage, elles n'ont pas de sens.

Ce qui est éprouvé ici, au-delà de « les questions disparaissent » : que le
retrait vaille aussi à la SAISIE — un champ forgé ne doit pas les
réintroduire —, que le lien injecté n'entre jamais en base, et que l'exclusion
du jeu ne rende pas l'administration aveugle.
"""

import html as html_module
import json
import os
import re

os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")

import base_donnees as bd
import main
import test_outils
from modeles import Chronique, Personne

ADMIN = ("admin", os.environ.get("MOT_DE_PASSE_ADMIN", "essai-admin"))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", ADMIN[1])

client = test_outils.client(main.app)

RETIREES = {"souvenir", "souhait", "lien"}
FORCEES = {"allegeance": "La Lumière"}


def _texte(page: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(page))


def _personne(prenom, marie=False, genre="masculin"):
    with bd.Seance() as seance:
        personne = Personne(prenom=prenom, nom="Marie", genre=genre,
                            est_marie=marie, source="import")
        seance.add(personne)
        seance.commit()
        return personne.uuid


# --- la liste réduite se dérive de questions.yaml ------------------------- #

# Marquée dans le fichier éditorial et non dans le code : il se corrige jusqu'au
# 4 septembre sans redéploiement, et une question ajoutée demain se marque là
# où elle s'écrit.
assert main.QUESTIONS_RETIREES_AUX_MARIES == RETIREES, \
    main.QUESTIONS_RETIREES_AUX_MARIES
assert main.REPONSES_FORCEES_AUX_MARIES == FORCEES, \
    main.REPONSES_FORCEES_AUX_MARIES

ordinaires = [q["cle"] for q in main.questions_du_bloc("obligatoires", False)]
reduites = [q["cle"] for q in main.questions_du_bloc("obligatoires", True)]
assert set(ordinaires) - set(reduites) == {"souvenir", "souhait", "allegeance"}
# L'ORDRE des questions restantes ne bouge pas : elles se lisent dans l'ordre
# du fichier, pas dans celui d'un ensemble.
assert reduites == [c for c in ordinaires if c in reduites], reduites

bonus_reduit = [q["cle"] for q in main.questions_du_bloc("bonus", True)]
assert "lien" not in bonus_reduit
assert len(bonus_reduit) == len(main.CONFIG["bonus"]) - 1

# EX-MAR-02 — l'allégeance forcée fait disparaître `monstre` et `destin` par la
# machinerie existante : ils portent `condition: allegeance = L'Ombre`.
conditionnelles = [q["cle"] for q in main.CONFIG["obligatoires"]
                   if q.get("condition")]
assert set(conditionnelles) == {"monstre", "destin"}, conditionnelles
for cle in conditionnelles:
    question = next(q for q in main.CONFIG["obligatoires"] if q["cle"] == cle)
    assert question["condition"]["valeur"] == "L'Ombre", question["condition"]

print("TOUT PASSE — la liste réduite vient de questions.yaml, dans l'ordre")


# --- l'écran ne montre pas ce qui a été retiré --------------------------- #

marie = _personne("Gaspard", marie=True)
invite = _personne("Ernest", marie=False)

page_marie = client.post("/identite/choisir",
                         data={"personne_uuid": marie}, follow_redirects=True)
assert page_marie.status_code == 200
for cle in RETIREES | set(FORCEES):
    assert f'name="{cle}"' not in page_marie.text, cle
for cle in reduites:
    assert f'name="{cle}"' in page_marie.text, cle
# Le PREMIER écran annonce lui aussi combien de questions complémentaires
# suivront : « cinq questions de plus » à qui n'en recevra que quatre est un
# mensonge posé dès la première page.
lu_premier = _texte(page_marie.text).lower()
assert "quatre question" in lu_premier, lu_premier[-400:]
assert "cinq question" not in lu_premier

page_invite = client.post("/identite/choisir",
                          data={"personne_uuid": invite}, follow_redirects=True)
for cle in ("souvenir", "souhait", "allegeance"):
    assert f'name="{cle}"' in page_invite.text, cle

print("TOUT PASSE — l'écran des mariés ne porte plus les trois questions")


# --- et le retrait vaut aussi à la SAISIE -------------------------------- #

# Un champ retiré de l'écran mais lu du formulaire se réintroduit d'un simple
# `curl` (EX-SEC-16). Et l'allégeance forcée doit être écrite AVANT la lecture,
# sinon une valeur envoyée à la main l'écraserait.
forge = {
    "personne_uuid": marie,
    "metier": "roi sans royaume",
    "souvenir": "un souvenir forgé",
    "souhait": "un vœu forgé",
    "lien": "un lien forgé",
    "allegeance": "L'Ombre",
}
reponses = main._reponses_du_formulaire(forge, "obligatoires", est_marie=True)
assert reponses["metier"] == "roi sans royaume"
for cle in ("souvenir", "souhait"):
    assert cle not in reponses, cle
assert reponses["allegeance"] == "La Lumière", reponses["allegeance"]

# L'invité ordinaire, lui, garde tout.
ordinaire = main._reponses_du_formulaire(forge, "obligatoires", est_marie=False)
assert ordinaire["souvenir"] == "un souvenir forgé"
assert ordinaire["allegeance"] == "L'Ombre"

print("TOUT PASSE — un champ forgé ne réintroduit rien, l'allégeance tient")


# --- le lien n'entre JAMAIS en base -------------------------------------- #

uid = test_outils.creer_chronique(
    "Gaspard", "Marie", {"metier": "roi", "allegeance": "La Lumière"},
    main.CODES_LIEUX, etat="prete")
with bd.Seance() as seance:
    chronique = seance.get(Chronique, uid)
    seance.get(Personne, chronique.personne_uuid).est_marie = True
    seance.commit()
ligne = bd.lire(uid)
assert ligne.est_marie is True, "la vue ne remonte pas est_marie"

# **Le piège** : `lien` est la première clé du bloc `bonus`, et l'étage se
# dérive de la présence d'une clé bonus (EX-QUE-11). L'écrire en base placerait
# la chronique au second étage dès la première réponse — le second étage ne
# serait jamais proposé.
assert "lien" in bd.CLES_SECOND_ETAGE
assert "lien" not in json.loads(ligne.reponses_json)
assert ligne.etage == 1, ligne.etage

# Le modèle, lui, le reçoit — accordé au genre, qui est un vocabulaire clos.
pour_le_modele = main._reponses_pour_le_modele(ligne)
assert pour_le_modele["lien"] == "Je suis le marié.", pour_le_modele["lien"]
assert json.loads(bd.lire(uid).reponses_json) == json.loads(ligne.reponses_json), \
    "la construction du prompt a écrit en base"

with bd.Seance() as seance:
    seance.get(Personne, bd.lire(uid).personne_uuid).genre = "feminin"
    seance.commit()
assert main._reponses_pour_le_modele(bd.lire(uid))["lien"] == "Je suis la mariée."

# Un invité ordinaire ne reçoit rien de tel.
autre = test_outils.creer_chronique("Ernest", "Simple", {"metier": "x"},
                                    main.CODES_LIEUX, etat="prete")
assert "lien" not in main._reponses_pour_le_modele(bd.lire(autre))

print("TOUT PASSE — le lien va au modèle, jamais en base, et l'étage tient")


# --- exclus du jeu, JAMAIS de l'administration --------------------------- #

bd.enregistrer_portrait(uid, {
    "nom_fictif": "Théoden le Juste", "peuple": "homme",
    "portrait": "Un paragraphe.", "indice": "Un indice.", "fuites_noms": [],
    "modele": "claude-sonnet-5", "duree_s": 6.0,
    "jetons_entree": 900, "jetons_sortie": 300})
bd.enregistrer_portrait(autre, {
    "nom_fictif": "Baldor le Bref", "peuple": "nain",
    "portrait": "Un paragraphe.", "indice": "Un indice.", "fuites_noms": [],
    "modele": "claude-sonnet-5", "duree_s": 6.0,
    "jetons_entree": 900, "jetons_sortie": 300})

jeu = client.get("/deviner", auth=ADMIN).text
assert "Baldor le Bref" in jeu
assert "Théoden le Juste" not in jeu, "un marié est à deviner"

# EX-MAR-04 est posée sur la ROUTE du jeu, pas dans `lister()` : le tableau
# était devenu aveugle au test le jour où `lister()` a exclu quelque chose pour
# tout le monde. L'administration doit continuer de les voir.
liste = client.get("/admin/chroniques", auth=ADMIN).text
assert "Théoden le Juste" in liste, "l'administration a perdu de vue un marié"
assert "marié·e — hors jeu" in _texte(liste)
assert "Théoden le Juste" in client.get(
    f"/admin/chronique/{uid}?onglet=portrait", auth=ADMIN).text
assert any(p.uuid == uid for p in bd.lister()), \
    "lister() a été amputée alors que seule la route du jeu devait l'être"

print("TOUT PASSE — exclus du jeu, toujours visibles pour l'administrateur")


# --- la révélation ne montre pas de boîte vide --------------------------- #

# Les mariés n'ont ni souvenir ni vœu : l'écran du jeu teste déjà leur
# présence, et ce test verrouille ces deux gardes — sinon quelqu'un les
# retirera un jour où « toutes les chroniques en ont ».
gabarit = __import__("pathlib").Path("templates/deviner.html").read_text(
    encoding="utf-8")
for cle in ("souvenir", "souhait"):
    assert f"{{% if dit.{cle} %}}" in gabarit, cle

print("TOUT PASSE — souvenir et vœu absents ne laissent pas de boîte vide")


# --- plus aucun mot de passe dédié aux mariés ---------------------------- #

# EX-AUTH-20 tombe : ils entrent par la même porte et se désignent dans la
# liste, comme les Gardiens par `est_responsable`. Une clé de configuration qui
# n'est lue nulle part est une invitation à croire qu'elle sert.
exemple = __import__("pathlib").Path("exemples/config.yaml").read_text(
    encoding="utf-8")
assert "mot_de_passe_maries" not in exemple
# Le fichier qui interdit la chaîne la contient forcément : s'exclure du
# balayage est nécessaire, mais on vérifie qu'il reste bien quelque chose à
# balayer — une sonde qui n'examine rien passe au vert pour rien.
_chemin = __import__("pathlib").Path
_fichiers = [f for f in _chemin(".").glob("*.py") if f.name != "test_maries.py"]
assert len(_fichiers) > 15, len(_fichiers)
source = "\n".join(f.read_text(encoding="utf-8") for f in _fichiers)
assert "mot_de_passe" + "_maries" not in source

print("TOUT PASSE — le mot de passe des mariés a disparu partout")


# --- le SECOND étage se réduit aussi ------------------------------------- #

# *Constaté en production le 30 août :* le premier étage était réduit, le
# second non — « Comment connais-tu les mariés ? » était encore posée. Mon test
# éprouvait `questions_du_bloc("bonus", True)` et jamais l'ÉCRAN qui la sert.
# La route `/bonus/{id}/questions` servait `CONFIG["bonus"]` en dur.

uid_bonus = test_outils.creer_chronique(
    "Delphine", "Marie", {"metier": "reine", "allegeance": "La Lumière"},
    main.CODES_LIEUX, etat="prete")
with bd.Seance() as seance:
    chronique = seance.get(Chronique, uid_bonus)
    personne = seance.get(Personne, chronique.personne_uuid)
    personne.est_marie = True
    personne.genre = "feminin"
    seance.commit()

ecran = client.get(f"/bonus/{uid_bonus}/questions").text
assert 'name="lien"' not in ecran, "« Comment connais-tu les mariés ? » est posée"
for cle in bonus_reduit:
    assert f'name="{cle}"' in ecran, cle

# Un invité ordinaire garde les cinq.
uid_simple = test_outils.creer_chronique("Hubert", "Simple", {"metier": "x"},
                                         main.CODES_LIEUX, etat="prete")
ordinaire = client.get(f"/bonus/{uid_simple}/questions").text
assert 'name="lien"' in ordinaire

# Le NOMBRE annoncé suit la liste servie : « cinq questions de plus » à qui
# n'en reçoit que quatre est un mensonge que personne ne relit.
assert main.nb_bonus_mot(True) == "quatre", main.nb_bonus_mot(True)
assert main.nb_bonus_mot(False) == "cinq", main.nb_bonus_mot(False)
lu_ecran = _texte(ecran).lower()
assert "quatre" in lu_ecran and "cinq" not in lu_ecran, lu_ecran[:200]

# Les quatre écrans qui l'annoncent le disent tous juste — il ne reste aucune
# constante de module qui pourrait diverger.
_source = __import__("pathlib").Path("main.py").read_text(encoding="utf-8")
assert "NB_BONUS_MOT" not in _source, "une constante morte invite à la reprendre"

# Les écrans du portrait exigent un portrait : sans lui, on éprouverait le
# rendu d'une chronique inachevée et non le décompte.
bd.enregistrer_portrait(uid_bonus, {
    "nom_fictif": "Arwen la Claire", "peuple": "elfe",
    "portrait": "Un paragraphe.", "indice": "Un indice.", "fuites_noms": [],
    "modele": "claude-sonnet-5", "duree_s": 6.0,
    "jetons_entree": 900, "jetons_sortie": 300})

for adresse in (f"/bonus/{uid_bonus}", f"/portrait/{uid_bonus}",
                f"/portrait/{uid_bonus}/reprendre"):
    page = _texte(client.get(adresse, follow_redirects=True).text).lower()
    assert "cinq question" not in page, adresse

print("TOUT PASSE — le second étage des mariés est réduit, et le compte suit")
