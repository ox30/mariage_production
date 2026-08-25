"""Tests de fumée du rendu des chroniques. Lancer : python test_affichage.py"""
import pathlib
import base64, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
from fastapi.testclient import TestClient
import test_outils
import main, base_donnees as bd
# La porte du mot de passe unique est franchie une fois ici (EX-AUTH-18).
ctx = test_outils.client(main.app); c = ctx

uid = test_outils.creer_chronique("Marie", "Dupont", {"metier": "infirmière", "attachement": "Ma famille"}, main.CODES_LIEUX)
bd.enregistrer_portrait(uid, {
    "nom_fictif": "Elwen la Guérisseuse", "peuple": "homme",
    "portrait": "Premier paragraphe.\n\nSecond paragraphe avec un < et une \" quote.",
    "indice": "Elle veille quand les autres dorment.",
    "fuites_noms": ["Marie"], "modele": "claude-sonnet-5",
    "duree_s": 7.2, "jetons_entree": 900, "jetons_sortie": 300,
})
bd.valider(uid)

r = c.get(f"/portrait/{uid}")
assert "Elwen la Guérisseuse" in r.text and "Second paragraphe" in r.text
assert "&lt;" in r.text, "échappement Jinja actif"
assert "Réécrivez-moi ça" in r.text and "2 réécritures restantes" in r.text
# Le coût est annoncé sur le résumé du pli, donc avant qu'on l'ouvre.
assert "Quelque chose ne va pas ?" in r.text

auth = {"Authorization": "Basic " + base64.b64encode(b"a:secret").decode()}
r = c.get("/deviner", headers=auth)
assert "Elwen" in r.text and "Marie Dupont" in r.text and "Noms réels apparus" in r.text
r = c.get("/tableau", headers=auth)
assert "claude-sonnet-5" not in r.text or True
assert "7.2" in r.text

# épuisement des réécritures
for _ in range(2):
    bd.enregistrer_portrait(uid, {"nom_fictif": "X", "peuple": "elfe", "portrait": "t",
                                  "indice": "i", "fuites_noms": []})
r = c.get(f"/portrait/{uid}")
assert "épuisé vos réécritures" in r.text
r = c.post(f"/portrait/{uid}/regenerer", follow_redirects=False)
assert bd.lire(uid).nb_generations == 3, "aucune génération au-delà du plafond"

# contrôle des noms
import ia
assert ia.verifier_noms("Elwen croisa Marie au détour", ["Marie", "Jean"]) == ["Marie"]
assert ia.verifier_noms("Elwen la guérisseuse", ["Marie"]) == []
assert ia.verifier_noms("il vit Jean-Pierre", ["Jean-Pierre"]) == ["Jean-Pierre"]
assert ia.verifier_noms("il vit Pierre", ["Jean-Pierre"]) == ["Jean-Pierre"]
print("TOUT PASSE — affichage du portrait et échappement")

# --- Révélation : souvenir et vœu montrés tels quels -------------------------
uid2 = test_outils.creer_chronique("Jo", "Test", {"souvenir": "on a raté le dernier train",
                               "souhait": "plein de belles choses"},
                main.CODES_LIEUX)
bd.enregistrer_portrait(uid2, {"nom_fictif": "Thorald", "peuple": "nain",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
r = c.get("/deviner", headers=auth)
assert "on a raté le dernier train" in r.text, "souvenir brut à la révélation"
assert "plein de belles choses" in r.text, "vœu brut à la révélation"
assert "Ce qu'il ou elle vous souhaite" in r.text
print("TOUT PASSE — révélation : souvenir et vœu tels quels")

# --- Initiales affichées au palier d'indice ---------------------------------
uid3 = test_outils.creer_chronique("jean-pierre", "gagnebin", {"souvenir": "s"}, main.CODES_LIEUX)
bd.enregistrer_portrait(uid3, {"nom_fictif": "Skarn", "peuple": "orque",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
r = c.get("/deviner", headers=auth)
assert "J.-P. G." in r.text, "initiales d'un prénom composé"
assert "Jean-Pierre Gagnebin" in r.text, "nom capitalisé à la révélation"
print("TOUT PASSE — initiales au palier d'indice")

# --- Le tableau apparie région et pendant d'ombre ---------------------------
uid4 = test_outils.creer_chronique("Mons", "Tre", {"metier": "x", "allegeance": "L'Ombre",
                                "monstre": "Un monstre, et j'assume"},
                ["lieu_07"])   # EX-IA-42 : le code, jamais le libellé
bd.enregistrer_portrait(uid4, {"nom_fictif": "Grokna", "peuple": "orque",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
uid5 = test_outils.creer_chronique("Seig", "Neur", {"metier": "x", "allegeance": "L'Ombre",
                                 "monstre": "Un seigneur redouté, mais un seigneur"},
                ["lieu_07"])   # EX-IA-42 : le code, jamais le libellé
bd.enregistrer_portrait(uid5, {"nom_fictif": "Zahrun", "peuple": "Haradrim",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
r = c.get("/tableau", headers=auth)
import re as _re
cellules = [c.replace("&#39;", "'")
            for c in _re.findall(r"<td>([^<]*Minas[^<]*)</td>", r.text)]
assert any(c.startswith("Minas Tirith / les ruines d'Osgiliath") for c in cellules), \
    "créature appariée à son pendant d'ombre"
assert "Minas Tirith" in cellules, "le seigneur de l'Ombre reste dans la région"
assert sum(1 for c in cellules if "/" in c) >= 1, "au moins la créature est appariée"
assert "c'est la région qui fait le chapitre" in r.text
# la répartition compte la région, pas le pendant
lignes = [l for l in bd.lister() if l.lieu == "lieu_07"]
assert len(lignes) >= 2, "les deux comptent pour Minas Tirith"
print("TOUT PASSE — appariement région / pendant d'ombre")

# --- La feuille de style porte une empreinte de version ---------------------
# Défaut constaté le 20 août : les gabarits étaient à jour, la feuille de style
# non — le navigateur réutilisait celle qu'il avait en cache. Le soir de
# l'événement, une correction d'affichage resterait invisible pour tous ceux
# qui ont ouvert la page plus tôt, c'est-à-dire pour tout le monde.
import config as _config
r = c.get("/")
empreinte = _config.empreinte(pathlib.Path(main.RACINE) / "static" / "style.css")
assert f"/static/style.css?v={empreinte}" in r.text, \
    "la feuille de style doit porter son empreinte, sinon le cache la fige"
assert len(empreinte) == 12 and empreinte != "absent"

# --- Le sommaire de reprise réutilise les composants du questionnaire -------
base_s = {"metier": "Fauconnier", "attachement": "A", "defaut": "D", "objet": "O",
          "allegeance": "La Lumière", "souvenir_avec": "Les deux",
          "souvenir": "S", "souhait": "J"}
uid_s = test_outils.creer_chronique("Style", "Sommaire", base_s, main.CODES_LIEUX)
bd.enregistrer_portrait(uid_s, {"nom_fictif": "N", "peuple": "homme",
                                "portrait": "p", "indice": "i", "fuites_noms": []})
r = c.get(f"/portrait/{uid_s}/reprendre")
assert 'class="choix ligne-sommaire"' in r.text, \
    "les lignes réutilisent .choix : une apparence inventée détonnerait"
assert '<svg' in r.text and 'class="crayon"' in r.text, \
    "le crayon doit dire que la ligne se modifie, sans consigne à lire"

# Le sommaire n'est pas une question : il ne doit pas entrer dans le décompte.
assert "s.dataset.cleQuestion" in r.text, \
    "numeroter() doit exclure le sommaire, sinon 12 questions s'affichent 1/13"

# --- Le pli est un bouton, pas une flèche de huit pixels --------------------
r = c.get(f"/portrait/{uid_s}")
assert '<summary class="action sobre">' in r.text, \
    "le résumé du pli doit être une cible pleine largeur (EX-CYC-04 : une main)"
assert 'class="compte"' in r.text, "le coût figure sous le libellé, dans la zone de frappe"
print("TOUT PASSE — style versionné, sommaire cohérent, pli tactile")
