"""Tests de fumée du parcours invité. Lancer : python test_parcours.py"""
import base64, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
from fastapi.testclient import TestClient
import main, base_donnees as bd

import contextlib
ctx = TestClient(main.app); ctx.__enter__(); c = ctx
assert c.get("/").status_code == 200, "accueil"
r = c.post("/questionnaire", data={"prenom": "Florian", "nom": "Test"})
assert r.status_code == 200 and "Quel est ton métier" in r.text, "questionnaire"
assert r.text.count('class="ecran') == 10, "7 questions + 2 conditionnelles + récapitulatif"

reponses = {
    "prenom": "Florian", "nom": "Test",
    "metier": "opérateur du trafic ferroviaire",
    "attachement": "Un travail fait proprement",
    "defaut": "Je veux tout contrôler",
    "objet": "mon carnet de notes",
    "allegeance": "La Lumière",
    "souvenir": "le soir où on a raté le dernier train ensemble",
}
r = c.post("/valider", data=reponses, follow_redirects=False)
assert r.status_code == 303, r.status_code
uuid = r.headers["location"].split("/")[-1]

r = c.get(f"/portrait/{uuid}")
assert r.status_code == 200
time.sleep(1.5)
r = c.get(f"/portrait/{uuid}/etat")
print("état après tentative sans clé :", bd.lire(uuid).etat)
assert "ANTHROPIC_API_KEY absente" in r.text, r.text[:400]

# les réponses survivent à l'échec de génération : c'est le point important
ligne = bd.lire(uuid)
assert "opérateur du trafic" in ligne.reponses_json
assert ligne.lieu in main.CODES_LIEUX

# pages protégées
auth = {"Authorization": "Basic " + base64.b64encode(b"a:secret").decode()}
assert c.get("/tableau").status_code == 401
assert c.get("/tableau", headers=auth).status_code == 200
assert c.get("/deviner", headers=auth).status_code == 200
assert c.get("/tableau/export.json", headers=auth).status_code == 200

# bonus
r = c.post(f"/portrait/{uuid}/valider", follow_redirects=False)
assert r.status_code == 303 and "/bonus/" in r.headers["location"]
r = c.get(f"/bonus/{uuid}/questions")
assert "Une phrase que tu répètes" in r.text
r = c.post(f"/bonus/{uuid}", data={"phrase": "on verra bien", "lien": "Collègue"}, follow_redirects=False)
assert r.status_code == 303
assert bd.lire(uuid).etage == 2 and "on verra bien" in bd.lire(uuid).reponses_json

# répartition des lieux : 30 créations, écart maximal de 1
for i in range(30):
    bd.creer(f"P{i}", "X", {"metier": "x"}, main.CODES_LIEUX)
from collections import Counter
compte = Counter(p.lieu for p in bd.lister())
print("répartition :", sorted(compte.values()))
assert max(compte.values()) - min(compte.values()) <= 1, compte
print("TOUT PASSE — parcours nominal")

# --- Sélecteur préalable et prénoms des mariés ------------------------------
import importlib
os.environ["PRENOM_MARIEE"] = "Solène"
os.environ["PRENOM_MARIE"] = "Gaspard"
importlib.reload(main)
c2 = TestClient(main.app); c2.__enter__()

r = c2.post("/questionnaire", data={"prenom": "Ana", "nom": "Test"})
assert "Solène" in r.text and "Gaspard" in r.text, "prénoms substitués dans les libellés"
assert 'name="souvenir_avec"' in r.text, "champ du sélecteur préalable"
assert 'class="choix prealable"' in r.text, "boutons du sélecteur préalable"

donnees = dict(reponses); donnees.update({"prenom": "Ana", "nom": "Test",
                                          "souvenir_avec": "Solène"})
r = c2.post("/valider", data=donnees, follow_redirects=False)
uid2 = r.headers["location"].split("/")[-1]
assert '"souvenir_avec": "Solène"' in bd.lire(uid2).reponses_json, "réponse préalable stockée"

# le message envoyé au modèle porte les prénoms et le sélecteur
import json as _json, ia
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Isengard", "reponses": _json.loads(bd.lire(uid2).reponses_json),
    "noms_interdits": ["Solène"], "couple": main.COUPLE})
assert "la mariée s'appelle Solène" in msg
assert "DANS CE SOUVENIR (et rien d'autre) → Solène" in msg
assert "ne dit rien du lien de parenté" in msg
assert "jamais écrire" in msg
print("TOUT PASSE — sélecteur préalable et prénoms des mariés")

# --- Bifurcation avant génération -------------------------------------------
r = c2.post("/questionnaire", data={"prenom": "Bea", "nom": "Test"})
assert 'data-suite="bonus"' in r.text and "Créer mon personnage" in r.text, "écran de bifurcation"

d = dict(donnees); d.update({"prenom": "Bea", "nom": "Test", "suite": "bonus"})
r = c2.post("/valider", data=d, follow_redirects=False)
assert "/bonus/" in r.headers["location"] and "/questions" in r.headers["location"]
uid3 = r.headers["location"].split("/")[2]
assert bd.lire(uid3).etat == "brouillon", bd.lire(uid3).etat

r = c2.get(f"/portrait/{uid3}")
assert "Il reste cinq questions" in r.text, "état brouillon annoncé"

r = c2.get(f"/bonus/{uid3}/questions")
assert "sans ces questions" in r.text and "facultatif = true" in r.text

# sortie sans répondre : étage reste à 1, la génération part quand même
r = c2.post(f"/bonus/{uid3}", data={"suite": "sortie"}, follow_redirects=False)
assert r.status_code == 303
assert bd.lire(uid3).etage == 1, "aucune réponse complémentaire → étage 1"
assert bd.lire(uid3).etat in ("en_cours", "echouee", "en_attente")

# le volume reçu est annoncé au modèle
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Edoras", "reponses": _json.loads(bd.lire(uid3).reponses_json),
    "noms_interdits": [], "couple": main.COUPLE})
assert "sans complément" in msg and "Exploite-les toutes" in msg

d2 = dict(donnees); d2.update({"prenom": "Cyd", "nom": "Test", "suite": "bonus"})
uid4 = c2.post("/valider", data=d2, follow_redirects=False).headers["location"].split("/")[2]
c2.post(f"/bonus/{uid4}", data={"phrase": "on verra", "talent": "je siffle"},
        follow_redirects=False)
assert bd.lire(uid4).etage == 2
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Edoras", "reponses": _json.loads(bd.lire(uid4).reponses_json),
    "noms_interdits": [], "couple": main.COUPLE})
assert "complémentaires" in msg and "LONGUEUR IMPOSÉE : 220 mots" in msg
# on ne repropose pas le second étage à qui l'a déjà donné
assert c2.get(f"/bonus/{uid4}", follow_redirects=False).status_code == 303
print("TOUT PASSE — bifurcation avant génération")

# --- Boutons de la bifurcation : libellé et action doivent concorder ---------
r = c2.post("/questionnaire", data={"prenom": "Dan", "nom": "Test"})
assert 'name="suite" id="champ-suite"' in r.text, "le choix passe par un champ caché"
assert r.text.count('data-suite="maintenant"') == 1
assert r.text.count('data-suite="bonus"') == 1
# aucun bouton d'envoi ne doit être capté par la navigation arrière
import re as _re
for bloc in _re.findall(r'<button[^>]*data-arriere[^>]*>', r.text):
    assert 'type="button"' in bloc, bloc
for bloc in _re.findall(r'<button[^>]*class="[^"]*envoi[^"]*"[^>]*>', r.text):
    assert "data-arriere" not in bloc, bloc

# le champ caché pilote réellement le routage
d = dict(donnees); d.update({"prenom": "Dan", "nom": "Test", "suite": "bonus"})
assert "/bonus/" in c2.post("/valider", data=d, follow_redirects=False).headers["location"]
d["suite"] = "maintenant"
assert "/portrait/" in c2.post("/valider", data=d, follow_redirects=False).headers["location"]

# sortie du questionnaire complémentaire par le champ caché
d2 = dict(donnees); d2.update({"prenom": "Eve", "nom": "Test", "suite": "bonus"})
uid5 = c2.post("/valider", data=d2, follow_redirects=False).headers["location"].split("/")[2]
r = c2.get(f"/bonus/{uid5}/questions")
assert 'data-suite="sortie"' in r.text and 'class="retour envoi"' in r.text
c2.post(f"/bonus/{uid5}", data={"suite": "sortie", "phrase": "ignorée"},
        follow_redirects=False)
assert bd.lire(uid5).etage == 1, "la sortie ne retient aucune réponse complémentaire"
assert "ignorée" not in bd.lire(uid5).reponses_json

# troncature diagnostiquée comme telle
assert ia.MODELE_DEFAUT == "claude-sonnet-5"
print("TOUT PASSE — boutons de la bifurcation")

# --- Cloisonnement des réponses par destination -----------------------------
reponses_completes = {
    "metier": "Chef de groupe des opérateurs du trafic",
    "attachement": "Un travail fait proprement",
    "defaut": "Je veux tout contrôler",
    "objet": "Mes clubs de golf",
    "allegeance": "L'Ombre",
    "souvenir": "Mon épouse est la soeur de la mariée. Les repas en Valais.",
    "souvenir_avec": "Solène",
    "lien": "Famille de la mariée",
    "role_groupe": "Observe en silence",
    "colere": "Le travail bâclé",
    "talent": "J'ai de la créativité.",
    "phrase": "Je vais au golf",
    "souhait": "Tout le bonheur du monde.",
}
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Edoras", "reponses": reponses_completes,
    "noms_interdits": [], "couple": main.COUPLE})

bloc_portrait = msg.split("RÉSERVÉ À")[0]
assert "Mes clubs de golf" in bloc_portrait
assert "Famille de la mariée" in bloc_portrait, "le lien nourrit le portrait, transposé"
assert "Tout le bonheur du monde" not in msg, "le vœu n'atteint jamais le modèle"
assert "souhaites-tu" not in msg, "ni la question du vœu"
assert "Que souhaites-tu" not in msg
# le décompte annoncé ne compte que ce qui nourrit le portrait
assert "5 complémentaires" in msg, msg[-400:]

contrat = main.CONFIG["contrat"]
for regle in ("PEUT être nommée", "elle ne se pose jamais à plat",
              "a sa place dans le portrait, mais transposé",
              "Ne commence ni ne termine jamais", "cette limite est ferme"):
    assert regle in contrat, regle
assert "n'ouvre pas le portrait sur cette" in msg, "consigne d'ouverture transmise"
assert "décor du portrait, pas son sujet" in msg
print("TOUT PASSE — cloisonnement par destination")

# --- Ombre : questions conditionnelles, peuples, cloisonnement --------------
r = c2.post("/questionnaire", data={"prenom": "Fay", "nom": "Test"})
assert 'data-condition-cle="allegeance"' in r.text
assert r.text.count('data-condition-valeur="L&#39;Ombre"') == 2, "deux écrans conditionnels"
assert "Un monstre, et j'assume" in r.text.replace("&#39;", "'")
assert "périr dans d'atroces souffrances" in r.text.replace("&#39;", "'")
assert "La nature" in r.text, "sixième réponse d'attachement"

peuples = main.CONFIG["peuples"]
for p in ("hobbit", "elfe", "nain", "homme", "dunedain", "ent",
          "Dunlending", "Numenoreen noir", "Corsaire d'Umbar", "Oriental",
          "Haradrim", "Variag de Khand",
          "troll", "spectre", "Uruk-hai", "gobelin", "cavalier de warg", "orque"):
    assert p in peuples, p
assert len(peuples) == 18, "six peuples par registre"

# le destin ne quitte jamais la base
sombre = dict(donnees)
sombre.update({"prenom": "Fay", "nom": "Test", "allegeance": "L'Ombre",
               "attachement": "La nature",
               "monstre": "Un monstre, et j'assume",
               "destin": "Oui, et que ce soit spectaculaire", "suite": "maintenant"})
uid6 = c2.post("/valider", data=sombre, follow_redirects=False).headers["location"].split("/")[-1]
stocke = bd.lire(uid6).reponses_json
assert "spectaculaire" in stocke and "j'assume" in stocke, "les deux réponses sont stockées"

msg = ia._construire_message(main.CONFIG, {
    "lieu": "Isengard", "reponses": _json.loads(stocke),
    "noms_interdits": [], "couple": main.COUPLE})
assert "j'assume" in msg, "le consentement guide le peuple, il est transmis"
assert "spectaculaire" not in msg, "le destin n'atteint jamais le modèle"
assert "périr" not in msg

contrat = main.CONFIG["contrat"]
# les trois registres couvrent les six mêmes réponses, sans trou
for cle in ("une bonne table entre amis", "la musique et les belles choses",
            "un travail fait proprement", "ma famille",
            "la route et le grand air", "la nature"):
    assert contrat.count(cle) == 3, (cle, contrat.count(cle))
for peuple in ("ent", "orque", "Variag de Khand", "troll", "Corsaire d'Umbar"):
    assert "→ " + peuple in contrat, peuple
assert "jamais humiliant" in contrat
print("TOUT PASSE — Ombre : conditionnelles et registres")

# --- Un échec technique ne débite pas le quota de l'invité ------------------
uid7 = bd.creer("Gil", "Test", {"metier": "x"}, main.CODES_LIEUX)
for _ in range(4):
    bd.enregistrer_echec(uid7, "529 overloaded_error")
ligne = bd.lire(uid7)
assert ligne.nb_generations == 0, "aucun crédit consommé par un échec"
assert ligne.nb_tentatives == 4, ligne.nb_tentatives

# la relance reste possible après plusieurs échecs
r = c2.get(f"/portrait/{uid7}")
assert "Réessayer" in r.text and "rien coûté" in r.text

# un succès, lui, débite bien
bd.enregistrer_portrait(uid7, {"nom_fictif": "N", "peuple": "ent", "portrait": "p",
                               "indice": "i", "fuites_noms": []})
assert bd.lire(uid7).nb_generations == 1
assert bd.lire(uid7).nb_tentatives == 5

# garde-fou technique : au-delà de MAX_TENTATIVES, plus aucun appel
for _ in range(bd.MAX_TENTATIVES):
    bd.enregistrer_echec(uid7, "529")
avant = bd.lire(uid7).nb_tentatives
c2.post(f"/portrait/{uid7}/regenerer", follow_redirects=False)
import time as _t; _t.sleep(0.4)
assert bd.lire(uid7).nb_tentatives == avant, "aucun appel au-delà du garde-fou"
print("TOUT PASSE — un échec ne débite pas le quota")

# --- Un échec de génération ne consomme aucun crédit ------------------------
uid7 = bd.creer("Gilo", "Test", {"metier": "x"}, main.CODES_LIEUX)
for _ in range(5):
    bd.enregistrer_echec(uid7, "HTTP 529 — overloaded_error")
assert bd.lire(uid7).nb_generations == 0, "cinq pannes, zéro crédit débité"
assert bd.lire(uid7).etat == "echouee"
# le portrait obtenu, lui, compte
bd.enregistrer_portrait(uid7, {"nom_fictif": "N", "peuple": "nain", "portrait": "p",
                               "indice": "i", "fuites_noms": []})
assert bd.lire(uid7).nb_generations == 1
# et les réponses ont survécu à tout
assert "x" in bd.lire(uid7).reponses_json
print("TOUT PASSE — un échec ne consomme aucun crédit")

# --- Le lien déclaré ne doit pas être étendu ---------------------------------
otho = {"metier": "Dessinateur", "attachement": "Une bonne table entre amis",
        "defaut": "Je veux tout contrôler", "objet": "Mon décapsuleur",
        "allegeance": "La Lumière", "souvenir_avec": "Les deux",
        "souvenir": "un test", "lien": "Famille de Solène"}
msg = ia._construire_message(main.CONFIG, {
    "lieu": "Les Havres Gris", "reponses": otho,
    "noms_interdits": [], "couple": main.COUPLE})
assert "ne dit rien du lien de parenté" in msg, "le sélecteur est désambiguïsé"
assert "Famille de Solène" in msg
assert "N'étends jamais un lien" in main.CONFIG["contrat"]
print("TOUT PASSE — le lien déclaré n'est pas étendu")

# --- Locution, pendant d'ombre, unicité des noms fictifs --------------------
lieu_mt = next(l for l in main.CONFIG["lieux"] if l["libelle"] == "Minas Tirith")
base = {"metier": "postier", "attachement": "La nature", "allegeance": "L'Ombre"}

msg = ia._construire_message(main.CONFIG, {
    "lieu": lieu_mt, "reponses": base, "noms_interdits": [], "couple": main.COUPLE})
assert "à Minas Tirith" in msg and "la préposition est imposée" in msg
assert "Osgiliath" not in msg, "un humain de l'Ombre reste dans la région"

msg = ia._construire_message(main.CONFIG, {
    "lieu": lieu_mt, "reponses": {**base, "monstre": "Un monstre, et j'assume"},
    "noms_interdits": [], "couple": main.COUPLE})
assert "ruines d'Osgiliath" in msg, "la créature est reléguée aux abords"
assert "n'y est pas admise" in msg

comte = next(l for l in main.CONFIG["lieux"] if l["libelle"] == "La Comté")
assert "en Comté" in ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": base, "noms_interdits": [], "couple": main.COUPLE})

# noms fictifs déjà attribués
uid8 = bd.creer("Gilon", "Test", {"metier": "x"}, main.CODES_LIEUX)
bd.enregistrer_portrait(uid8, {"nom_fictif": "Skarn Rouille", "peuple": "orque",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
pris = bd.noms_fictifs_pris()
assert "Skarn Rouille" in pris
assert "Skarn Rouille" not in bd.noms_fictifs_pris(sauf=uid8), "on ne s'interdit pas son propre nom"
msg = ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": base, "noms_interdits": [],
    "noms_fictifs_pris": pris, "couple": main.COUPLE})
assert "NOMS FICTIFS DÉJÀ ATTRIBUÉS" in msg and "Skarn Rouille" in msg
print("TOUT PASSE — locution, pendant d'ombre, noms fictifs uniques")

# --- Longueur adaptée au volume de réponses --------------------------------
court = ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": {"metier": "postier", "attachement": "La nature"},
    "noms_interdits": [], "couple": main.COUPLE})
assert "LONGUEUR IMPOSÉE : 150 mots" in court
assert "sans complément" in court

long_ = ia._construire_message(main.CONFIG, {
    "lieu": comte,
    "reponses": {"metier": "postier", "attachement": "La nature",
                 "talent": "je chante", "phrase": "en avant", "lien": "Collègue"},
    "noms_interdits": [], "couple": main.COUPLE})
assert "LONGUEUR IMPOSÉE : 220 mots" in long_
assert "Exploite-les toutes" in long_, "à douze réponses, plus de tri à opérer"
assert "laisse les autres" not in long_

assert ia.MODELE_DEFAUT == "claude-sonnet-5"
import inspect
assert '"max_tokens": 8000' in inspect.getsource(ia.generer)
print("TOUT PASSE — longueur adaptée au volume")

# --- Le vœu est au premier étage, et n'atteint jamais le modèle -------------
assert [q["cle"] for q in main.CONFIG["obligatoires"]][-1] == "souhait", \
    "le vœu clôt le premier étage"
assert "souhait" not in [q["cle"] for q in main.CONFIG["bonus"]]
assert main.NB_BONUS == 5 and main.NB_BONUS_MOT == "cinq"

r = c2.post("/questionnaire", data={"prenom": "Hal", "nom": "Test"})
assert "Que souhaites-tu à Solène et Gaspard" in r.text.replace("&#39;", "'")
assert "cinq questions de plus" in r.text.lower()

avec_voeu = dict(donnees)
avec_voeu.update({"prenom": "Hal", "nom": "Test", "souhait": "Tout le bonheur du monde",
                  "suite": "maintenant"})
uid9 = c2.post("/valider", data=avec_voeu, follow_redirects=False).headers["location"].split("/")[-1]
stocke = bd.lire(uid9).reponses_json
assert "Tout le bonheur du monde" in stocke, "le vœu est bien enregistré dès l'étage 1"
msg = ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": _json.loads(stocke), "noms_interdits": [], "couple": main.COUPLE})
assert "Tout le bonheur du monde" not in msg, "et n'atteint toujours pas le modèle"
print("TOUT PASSE — le vœu n'atteint jamais le modèle")

# --- Le contrôle de noms ne retient que les occurrences capitalisées --------
# Cas réel du 18 août : « le nouveau-né tout juste arrivé au monde » signalait
# une fuite du prénom « Juste ».
assert ia.verifier_noms("le nouveau-né tout juste arrivé au monde", ["Juste"]) == []
assert ia.verifier_noms("il croisa Juste au détour", ["Juste"]) == ["Juste"]
assert ia.verifier_noms("il ramassa une pierre polie", ["Pierre"]) == []
assert ia.verifier_noms("elle salua Pierre et repartit", ["Pierre"]) == ["Pierre"]
assert ia.verifier_noms("Juste avant l'aube, il partit", ["Juste"]) == [], "début de phrase"
assert ia.verifier_noms("il vit Jean-Pierre au loin", ["Jean-Pierre"]) == ["Jean-Pierre"]
assert ia.verifier_noms("la scène avec Solène à ses côtés", ["Solène"]) == ["Solène"]
print("TOUT PASSE — fuites de noms : occurrences capitalisées")

# --- Capitalisation des noms saisis et initiales ----------------------------
import noms as mod_noms
assert mod_noms.capitaliser("jean-pierre") == "Jean-Pierre"
assert mod_noms.capitaliser("GAGNEBIN") == "Gagnebin"
assert mod_noms.capitaliser("  joël   sandoz ") == "Joël Sandoz"
assert mod_noms.capitaliser("de rham") == "de Rham", "la particule reste minuscule"
assert mod_noms.capitaliser("van der meer") == "van der Meer"
assert mod_noms.capitaliser("d'alembert") == "d'Alembert"
assert mod_noms.capitaliser("le roy") == "Le Roy", "Le se capitalise en patronyme"
assert mod_noms.capitaliser("") == ""

assert mod_noms.initiales("jean-pierre", "gagnebin") == "J.-P. G."
assert mod_noms.initiales("marie-josé", "de rham") == "M.-J. R."
assert mod_noms.initiales("anne", "van der meer") == "A. M."
assert mod_noms.initiales("jean", "d'alembert") == "J. A."
assert mod_noms.initiales("anne-marie", "von gunten") == "A.-M. G."

# la capitalisation a lieu à la création, une seule fois
uid10 = bd.creer("jean-pierre", "GAGNEBIN", {"metier": "x"}, main.CODES_LIEUX)
ligne = bd.lire(uid10)
assert ligne.prenom == "Jean-Pierre" and ligne.nom == "Gagnebin"
assert "Jean-Pierre" in bd.tous_les_prenoms() and "Gagnebin" in bd.tous_les_prenoms()
print("TOUT PASSE — capitalisation et initiales")

# --- Genre du personnage ----------------------------------------------------
# Cas réel du 18 août : « Jean-Pascal » a produit un personnage féminin.
r = c2.post("/questionnaire", data={"prenom": "jean-pascal", "nom": "van der maas",
                                    "genre": "masculin"})
assert 'name="genre" value="masculin"' in r.text, "le genre traverse le questionnaire"

d = dict(donnees); d.update({"prenom": "jean-pascal", "nom": "van der maas",
                             "genre": "masculin", "suite": "maintenant"})
uid11 = c2.post("/valider", data=d, follow_redirects=False).headers["location"].split("/")[-1]
ligne = bd.lire(uid11)
assert ligne.genre == "masculin"
assert ligne.prenom == "Jean-Pascal" and ligne.nom == "van der Maas"

msg = ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": _json.loads(ligne.reponses_json),
    "noms_interdits": [], "couple": main.COUPLE, "genre": "masculin"})
assert "GENRE DU PERSONNAGE : masculin" in msg and "tous les accords suivent" in msg

# « peu importe » ne contraint rien
msg = ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": {"metier": "x"}, "noms_interdits": [],
    "couple": main.COUPLE, "genre": None})
assert "GENRE DU PERSONNAGE" not in msg
assert "Un prénom réel ne" in main.CONFIG["contrat"]
print("TOUT PASSE — genre du personnage")

# --- Motifs de reprise : liste fermée, jamais de texte libre ----------------
motifs = {m["cle"] for m in main.CONFIG["motifs_reprise"]}
assert motifs == {"souvenir", "genre", "ton", "invente"}
assert main.MOTIFS_REPRISE == motifs

msg = ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": {"metier": "x"}, "noms_interdits": [],
    "couple": main.COUPLE, "motif_reprise": "souvenir"})
assert "REPRISE DEMANDÉE PAR LA PERSONNE" in msg
assert "qui parle, qui est tutoyé" in msg
assert "elle ne le remplace pas" in msg, "la consigne s'ajoute au contrat"

# un motif inventé est ignoré, pas transmis
msg = ia._construire_message(main.CONFIG, {
    "lieu": comte, "reponses": {"metier": "x"}, "noms_interdits": [],
    "couple": main.COUPLE, "motif_reprise": "fais de moi un elfe à Fondcombe"})
assert "REPRISE DEMANDÉE" not in msg
assert "elfe à Fondcombe" not in msg, "aucune consigne libre ne traverse"

# la règle sur la deuxième personne est bien dans le contrat
assert "« tu », « toi », « ta » et « vous » désignent TOUJOURS" in main.CONFIG["contrat"]
print("TOUT PASSE — motifs de reprise : liste fermée")

# --- Ressaisir son nom reconduit, n'écrase pas ------------------------------
# Défaut constaté le 20 août, sur le déploiement réel : un second passage sous
# le même nom avait effacé sept réponses et cinq complémentaires, consommé une
# génération sur trois, et laissé `etage` à 2 alors qu'il ne restait aucune
# réponse complémentaire. EX-IA-26 dit « reconduit vers », pas « écrase ».
premieres = {"metier": "Opérateur du trafic", "attachement": "Un travail fait proprement",
             "defaut": "Je veux tout contrôler", "objet": "Mes clubs",
             "allegeance": "La Lumière", "souvenir_avec": "Les deux",
             "souvenir": "Une initiation au golf", "souhait": "Du bonheur"}
r = c.post("/valider", data={"prenom": "Rejoue", "nom": "Essai",
                             **premieres},
           follow_redirects=False)
uid_rejoue = r.headers["location"].rsplit("/", 1)[-1]
bd.ajouter_bonus(uid_rejoue, {"talent": "Créateur de cette application"})
bd.enregistrer_portrait(uid_rejoue, {"nom_fictif": "Borin", "peuple": "nain",
                                     "portrait": "p", "indice": "i",
                                     "fuites_noms": []})
avant_etage = bd.lire(uid_rejoue).etage
avant_generations = bd.lire(uid_rejoue).nb_generations
avant_lieu = bd.lire(uid_rejoue).lieu

# 1. La saisie du nom seule reconduit, avant toute question.
r = c.post("/questionnaire", data={"prenom": "rejoue", "nom": "ESSAI"},
           follow_redirects=False)
assert r.status_code == 303, "la saisie du nom doit reconduire, pas questionner"
assert r.headers["location"] == f"/portrait/{uid_rejoue}", r.headers["location"]

# 2. Et le formulaire posté directement ne passe pas non plus.
r = c.post("/valider", data={"prenom": "Rejoue", "nom": "Essai",
                             "metier": "espion", "souhait": "autre chose"},
           follow_redirects=False)
assert r.headers["location"] == f"/portrait/{uid_rejoue}", "porte dérobée ouverte"

relue = bd.lire(uid_rejoue)
assert "espion" not in relue.reponses_json, "les nouvelles réponses ne s'écrivent pas"
assert "Opérateur du trafic" in relue.reponses_json, "les premières tiennent"
assert "Créateur de cette application" in relue.reponses_json, \
    "les réponses complémentaires survivent"
assert relue.etage == avant_etage, "l'étage ne se désynchronise pas"
assert relue.lieu == avant_lieu, "le lieu ne se rejoue pas (EX-IA-08)"
assert relue.nb_generations == avant_generations, \
    "ressaisir son nom ne consomme aucune génération (EX-IA-04)"
print("TOUT PASSE — ressaisir son nom reconduit sans rien écraser")

# --- Reprendre ses réponses après lecture du portrait (EX-IA-05) ------------
# L'invité modifie n'importe quelle réponse et régénère. Deux règles gouvernent
# l'opération : rien n'est jamais effacé (EX-GEN-08), et l'étage ne redescend
# jamais — il dit ce qui a été donné, et ce qui a été donné l'a été.
base = {"metier": "Fauconnier", "attachement": "Ma famille",
        "defaut": "Je parle trop", "objet": "Ma longue-vue",
        "allegeance": "La Lumière", "souvenir_avec": "Les deux",
        "souvenir": "Un été à la mer", "souhait": "Beaucoup de joie"}
r = c.post("/valider", data={"prenom": "Repri", "nom": "Se", **base},
           follow_redirects=False)
uid_r = r.headers["location"].rsplit("/", 1)[-1]


def _attendre(condition, limite=3.0):
    """Attend qu'un fil de génération ait fini d'écrire.

    Sans cette attente, une mesure prise juste après la requête constate
    l'état d'AVANT le travail qu'elle prétend vérifier — et l'assertion passe
    quoi qu'il arrive.
    """
    import time as _t
    fin = _t.monotonic() + limite
    while _t.monotonic() < fin:
        if condition():
            return True
        _t.sleep(0.05)
    return False


# La création a lancé une génération qui va échouer, faute de clé d'API. Il
# faut la laisser s'inscrire, sinon son échec tardif se confondrait avec celui
# de la reprise et rendrait la mesure suivante ininterprétable.
assert _attendre(lambda: bd.lire(uid_r).etat == "echouee"), \
    "le fil de génération de la création n'a pas rendu la main"
bd.enregistrer_portrait(uid_r, {"nom_fictif": "Aldor", "peuple": "homme",
                                "portrait": "p", "indice": "i", "fuites_noms": []})

# Le portrait propose le second étage tant qu'il n'a pas été donné, et replie
# les deux actions qui coûtent une réécriture.
r = c.get(f"/portrait/{uid_r}")
assert "questions de plus" in r.text, "le second étage doit être proposé ici"
assert "/portrait/" + uid_r + "/reprendre" in r.text, "la reprise doit être offerte"
assert "<details" in r.text and "Quelque chose ne va pas ?" in r.text

# L'écran de reprise ouvre sur un sommaire et arrive pré-rempli.
r = c.get(f"/portrait/{uid_r}/reprendre")
assert 'id="sommaire"' in r.text and "Touchez ce que vous voulez changer" in r.text
assert "Fauconnier" in r.text, "les réponses doivent être pré-remplies"
assert "2 restantes" in r.text, "le coût doit être annoncé"
# Étage 1 : les cinq questions complémentaires ne sont pas dans la reprise.
assert "Une phrase que tu répètes tout le temps ?" not in r.text, \
    "le second étage se propose ailleurs, pas par la porte de la reprise"

# Une réponse absente du formulaire est inchangée, pas effacée.
avant_tentatives = bd.lire(uid_r).nb_tentatives
r = c.post(f"/portrait/{uid_r}/reprendre",
           data={"metier": "Fauconnier du roi"}, follow_redirects=False)
assert r.status_code == 303
relue = bd.lire(uid_r)
assert "Fauconnier du roi" in relue.reponses_json, "la correction est prise"
assert "Un été à la mer" in relue.reponses_json, "le reste survit (EX-GEN-08)"
assert relue.etage == 1, "aucune réponse du second étage n'a été donnée"

# EX-IA-04 — modifier puis régénérer consomme la même unité que régénérer.
# On compare un ÉCART, pas une valeur absolue : les valeurs absolues se
# décalent au premier bloc inséré, et une assertion qui ne peut pas échouer
# ne prouve rien.
assert _attendre(lambda: bd.lire(uid_r).nb_tentatives > avant_tentatives), \
    "la reprise doit déclencher une génération (EX-IA-04)"
assert bd.lire(uid_r).nb_tentatives == avant_tentatives + 1, \
    "et exactement une"

# --- L'étage ne redescend jamais (EX-QUE-11) --------------------------------
bd.ajouter_bonus(uid_r, {"phrase": "Par la barbe !", "colere": "L'injustice"})
assert bd.lire(uid_r).etage == 2
# Repasser par le formulaire complémentaire en l'envoyant vide ne doit pas
# faire retomber à 1 : les cinq réponses sont toujours là.
bd.ajouter_bonus(uid_r, {})
assert bd.lire(uid_r).etage == 2, "l'étage ne redescend jamais"
assert "Par la barbe !" in bd.lire(uid_r).reponses_json
# Une reprise partielle non plus.
bd.reprendre_reponses(uid_r, {"metier": "Fauconnier impérial"})
assert bd.lire(uid_r).etage == 2, "l'étage ne redescend pas à la reprise"
assert "Par la barbe !" in bd.lire(uid_r).reponses_json

# Au second étage, la reprise montre les douze questions.
r = c.get(f"/portrait/{uid_r}/reprendre")
assert "Une phrase que tu répètes tout le temps ?" in r.text, \
    "au second étage, tout se repasse"
assert "Par la barbe !" in r.text, "y compris pré-rempli"
# Et le portrait ne propose plus le second étage, déjà donné.
bd.enregistrer_portrait(uid_r, {"nom_fictif": "Aldor", "peuple": "homme",
                                "portrait": "p", "indice": "i", "fuites_noms": []})
r = c.get(f"/portrait/{uid_r}")
assert "questions de plus" not in r.text, "le second étage ne se propose qu'une fois"

# --- Quota épuisé : la reprise est fermée -----------------------------------
uid_q = bd.creer("Quota", "Plein", dict(base), main.CODES_LIEUX)
for _ in range(main.MAX_GENERATIONS):
    bd.enregistrer_portrait(uid_q, {"nom_fictif": "X", "peuple": "nain",
                                    "portrait": "p", "indice": "i",
                                    "fuites_noms": []})
r = c.get(f"/portrait/{uid_q}/reprendre", follow_redirects=False)
assert r.status_code == 303, "reprendre sans pouvoir régénérer n'a pas de sens"
r = c.get(f"/portrait/{uid_q}")
assert "reprendre" not in r.text and "épuisé vos réécritures" in r.text
print("TOUT PASSE — reprise des réponses, étage monotone, quota respecté")
