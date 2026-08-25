"""Tests de fumée de l'identité. Lancer : python test_identite.py"""
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")
import html as _html
from fastapi.testclient import TestClient
import base_donnees as bd, identite, main, test_outils


def texte(reponse):
    """Le corps rendu, apostrophes et accents rétablis.

    EX-SEC-02 — Jinja échappe le contenu des variables : « n\'a » sort en
    « n&#39;a ». Une assertion sur le texte brut échoue alors sans rapport avec
    ce qu\'elle prétend éprouver. Le texte STATIQUE des gabarits, lui, n\'est
    pas échappé : la faute ne se voit donc que sur les messages dynamiques.
    """
    return _html.unescape(reponse.text)

c = test_outils.client(main.app)
LIEUX = main.CODES_LIEUX

# --- L'écran d'entrée offre deux portes, pas une ---------------------------
# EX-AUTH-09. Avant l'étape 2, l'accueil demandait le nom d'emblée : celui qui
# revenait voir son personnage n'avait d'autre chemin que de refaire le geste
# de création, et de se retrouver devant un portrait sans savoir pourquoi.
page = c.get("/").text
assert "/identite?intention=creer" in page, page[:400]
assert "/identite?intention=revoir" in page, "la porte « revoir » manque"
assert 'name="prenom"' not in page, "l'accueil ne doit plus demander le nom"
print("TOUT PASSE — l'écran d'entrée offre deux portes")

# --- Créer : la saisie libre mène au questionnaire -------------------------
r = test_outils.entrer_identite(c, "aria", "sonval", "feminin")
assert r.status_code == 200, r.status_code
assert "Quel est ton métier" in r.text, r.text[:300]
aria = bd.resoudre("aria", "sonval").unique
assert aria is not None
assert (aria.prenom, aria.nom) == ("Aria", "Sonval"), (aria.prenom, aria.nom)
assert aria.genre == "feminin", "EX-IA-36 — le genre est posé à l'écran d'identité"
assert aria.source == "saisie_libre"
# L'identité voyage par uuid : reposter un nom rouvrirait la résolution que
# l'écran vient de trancher, et deux homonymes ne se distinguent que par lui.
assert f'name="personne_uuid" value="{aria.uuid}"' in r.text, "uuid absent du formulaire"
assert 'name="prenom"' not in r.text, "le nom ne doit plus voyager dans le formulaire"
print("TOUT PASSE — la saisie libre crée la personne et porte son uuid")

# --- Le cookie d'appareil est un raccourci, et rien d'autre ----------------
appareil = c.cookies.get(identite.NOM_COOKIE)
assert appareil, "aucun cookie d'appareil posé"
assert bd.personne_de_l_appareil(appareil).uuid == aria.uuid

reponses = {"personne_uuid": aria.uuid, "metier": "luthière",
            "attachement": "La musique et les belles choses",
            "allegeance": "La Lumière", "souvenir": "un concert sous la pluie"}
uid_aria = c.post("/valider", data=reponses,
                  follow_redirects=False).headers["location"].rsplit("/", 1)[-1]
assert bd.lire(uid_aria) is not None

# L'appareil est FIGÉ à la création (EX-AUTH-06).
assert bd.lire(uid_aria).appareil_uuid == appareil

# Le raccourci se voit : l'écran d'entrée propose de retrouver son personnage.
page = c.get("/").text
assert "Retrouver mon personnage" in page, page[:400]
assert f"/portrait/{uid_aria}" in page
assert "Aria" in page, "l'écran doit dire à qui il croit parler"
print("TOUT PASSE — le cookie d'appareil reconnaît sans rien autoriser")

# --- Perdre son cookie ne coûte aucun droit (EX-AUTH-02, EX-AUTH-03) -------
# La référence est prise AVANT l'effacement : mesurée après, elle
# photographierait l'état dégradé et l'appellerait la normale.
generations_avant = bd.lire(uid_aria).nb_generations
sans_cookie = test_outils.client(main.app)
assert "Retrouver mon personnage" not in sans_cookie.get("/").text
r = test_outils.entrer_identite(sans_cookie, "ARIA", "  Sonval ", intention="revoir")
assert r.status_code == 303, r.status_code
assert r.headers["location"] == f"/portrait/{uid_aria}", r.headers["location"]
assert bd.lire(uid_aria).nb_generations == generations_avant, \
    "retrouver son personnage ne doit rien consommer"
# Et la chronique garde l'appareil de sa naissance : changer de téléphone ne
# réécrit pas ce qui est déjà créé.
assert bd.lire(uid_aria).appareil_uuid == appareil, "EX-AUTH-06 — attribution figée"
print("TOUT PASSE — perdre son cookie ne coûte ni chronique ni crédit")

# --- Deux homonymes ne sont plus confondus (EX-AUTH-05) --------------------
# Le défaut : `personne_par_nom` faisait un `scalar()` et renvoyait
# silencieusement la première des deux. L'import produira exactement ce cas,
# puisque EX-ADM-13 autorise deux homonymes distingués par leur Identifiant.
with bd.Seance() as seance:
    une = bd.creer_personne(seance, "marie", "meyer", source="import")
    une.identifiant_import = "MEYER-01"
    autre = bd.creer_personne(seance, "marie", "meyer", source="import")
    autre.identifiant_import = "MEYER-02"
    seance.commit()
    uuid_une, uuid_autre = une.uuid, autre.uuid

resolution = bd.resoudre("Marie", "Meyer")
assert resolution.ambigue, "deux homonymes doivent être signalés comme ambigus"
assert resolution.unique is None, "« unique » ne doit pas désigner la première de deux"
assert {p.uuid for p in resolution.candidates} == {uuid_une, uuid_autre}

deux = test_outils.client(main.app)
r = test_outils.entrer_identite(deux, "marie", "meyer")
assert r.status_code == 200
assert "Deux personnes portent ce nom" in r.text, r.text[:300]
assert uuid_une in r.text and uuid_autre in r.text, "les deux choix doivent être offerts"
assert "Quel est ton métier" not in r.text, "on ne questionne pas avant d'avoir tranché"
print("TOUT PASSE — deux homonymes ouvrent un choix, jamais une confusion")

# --- Le choix mène au questionnaire de la BONNE personne ------------------
r = deux.post("/identite/choisir",
              data={"personne_uuid": uuid_autre, "intention": "creer"},
              follow_redirects=False)
assert r.status_code == 200, r.status_code
assert f'name="personne_uuid" value="{uuid_autre}"' in r.text
uid_autre = deux.post("/valider", data={"personne_uuid": uuid_autre,
                                        "metier": "vigneronne"},
                      follow_redirects=False).headers["location"].rsplit("/", 1)[-1]
assert bd.chronique_de_personne(uuid_autre) == uid_autre
assert bd.chronique_de_personne(uuid_une) is None, \
    "la chronique s'est attachée à la mauvaise des deux homonymes"

# Et l'autre Marie Meyer garde son propre chemin : l'écran de choix la
# distingue par ce qu'elle a, pas par son rang dans la liste.
r = test_outils.entrer_identite(deux, "marie", "meyer")
assert "a déjà un personnage" in r.text and "n'a pas encore de personnage" in r.text
print("TOUT PASSE — le choix attache la chronique à la bonne des deux")

# --- Revoir un nom inconnu le dit, au lieu d'en créer un ------------------
seul = test_outils.client(main.app)
r = test_outils.entrer_identite(seul, "Personne", "Inexistante", intention="revoir")
assert r.status_code == 404, r.status_code
assert "Aucun personnage" in texte(r), texte(r)[:300]
assert bd.resoudre("Personne", "Inexistante").candidates == [], \
    "« revoir » ne doit jamais créer la personne qu'il cherche"
print("TOUT PASSE — revoir un nom inconnu ne crée rien")

# --- Une personne connue sans chronique, en « revoir » --------------------
with bd.Seance() as seance:
    orpheline = bd.creer_personne(seance, "sans", "chronique", source="import")
    seance.commit()
    uuid_orpheline = orpheline.uuid
r = test_outils.entrer_identite(seul, "sans", "chronique", intention="revoir")
assert r.status_code == 404, r.status_code
assert "aucun personnage n'a" in texte(r).lower(), texte(r)[:300]
assert bd.chronique_de_personne(uuid_orpheline) is None, \
    "« revoir » ne doit pas créer de chronique en chemin"
print("TOUT PASSE — un nom connu sans personnage le dit sans rien créer")

# --- La reconduction n'est plus muette (EX-AUTH-09) ----------------------
# L'écart « la reconduction vers une chronique existante est muette », consigné
# dans CONVENTIONS.md à l'étape 1, se referme ici.
retour = test_outils.client(main.app)
r = test_outils.entrer_identite(retour, "aria", "sonval")
assert r.status_code == 200, r.status_code
assert "déjà un personnage" in r.text, r.text[:300]
assert f"/portrait/{uid_aria}" in r.text
reponses_avant = bd.lire(uid_aria).reponses_json
r = retour.post("/valider", data={"personne_uuid": aria.uuid,
                                  "metier": "espionne"},
                follow_redirects=False)
assert r.headers["location"] == f"/portrait/{uid_aria}", "porte dérobée ouverte"
assert bd.lire(uid_aria).reponses_json == reponses_avant, \
    "les réponses sont la seule chose irremplaçable du projet (EX-GEN-08)"
print("TOUT PASSE — la reconduction s'explique et n'écrase rien")

# --- Le genre atteint une personne DÉJÀ EN BASE -------------------------
# Trou découvert en mutation : mon contrôle du genre ne couvrait que la
# création, où `creer_personne_libre` le pose lui-même. Retirer l'appel à
# `definir_genre` ne faisait donc tomber aucune assertion — alors qu'après
# l'import Excel, toutes les personnes existent DÉJÀ, et c'est ce chemin-là
# qui compte.
with bd.Seance() as seance:
    importee = bd.creer_personne(seance, "sans", "genre", source="import")
    seance.commit()
    uuid_importee = importee.uuid
assert bd.personne(uuid_importee).genre is None, "référence prise avant l'action"

tardif = test_outils.client(main.app)
test_outils.entrer_identite(tardif, "sans", "genre", "masculin")
assert bd.personne(uuid_importee).genre == "masculin", \
    "le genre donné à l'écran d'identité n'a pas atteint la personne (EX-IA-36)"

# Et il ne se perd pas au repassage suivant, qui ne le redonne pas.
test_outils.entrer_identite(tardif, "sans", "genre", "")
assert bd.personne(uuid_importee).genre == "masculin", \
    "un passage sans réponse de genre a effacé le genre connu"
print("TOUT PASSE — le genre atteint une personne déjà en base, et ne s'efface pas")

# --- Un uuid inventé ne fabrique pas de chronique ------------------------
avant = len(bd.lister())
r = seul.post("/valider", data={"personne_uuid": "00000000-0000-0000-0000-000000000000",
                                "metier": "fantôme"}, follow_redirects=False)
assert r.status_code == 303 and "/identite" in r.headers["location"], r.headers
assert len(bd.lister()) == avant, "une chronique a été créée sans personne"
print("TOUT PASSE — un uuid inventé ne fabrique aucune chronique")

# --- Le cookie d'appareil porte les attributs d'EX-SEC-07 ---------------
frais = test_outils.client(main.app)
r = frais.post("/identite", data={"intention": "creer", "prenom": "Cook",
                                  "nom": "Ie", "genre": ""},
               follow_redirects=False)
brut = [v for k, v in r.headers.items()
        if k.lower() == "set-cookie" and identite.NOM_COOKIE in v]
assert brut, r.headers
assert "HttpOnly" in brut[0], brut[0]
assert "samesite=lax" in brut[0].lower(), brut[0]
assert "Secure" not in brut[0], "en HTTP local, Secure empêcherait toute reconnaissance"
print("TOUT PASSE — le cookie d'appareil est HttpOnly et SameSite=Lax")
