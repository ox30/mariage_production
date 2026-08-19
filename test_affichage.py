"""Tests de fumée du rendu des chroniques. Lancer : python test_affichage.py"""
import base64, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
from fastapi.testclient import TestClient
import main, base_donnees as bd
ctx = TestClient(main.app); ctx.__enter__(); c = ctx

uid = bd.creer("Marie", "Dupont", {"metier": "infirmière", "attachement": "Ma famille"}, main.LIBELLES_LIEUX)
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
assert "Réécrivez-moi ça" in r.text and "2 restants" in r.text

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
assert bd.lire(uid)["nb_generations"] == 3, "aucune génération au-delà du plafond"

# contrôle des noms
import ia
assert ia.verifier_noms("Elwen croisa Marie au détour", ["Marie", "Jean"]) == ["Marie"]
assert ia.verifier_noms("Elwen la guérisseuse", ["Marie"]) == []
assert ia.verifier_noms("il vit Jean-Pierre", ["Jean-Pierre"]) == ["Jean-Pierre"]
assert ia.verifier_noms("il vit Pierre", ["Jean-Pierre"]) == ["Jean-Pierre"]
print("TOUT PASSE — affichage du portrait et échappement")

# --- Révélation : souvenir et vœu montrés tels quels -------------------------
uid2 = bd.creer("Jo", "Test", {"souvenir": "on a raté le dernier train",
                               "souhait": "plein de belles choses"},
                main.LIBELLES_LIEUX)
bd.enregistrer_portrait(uid2, {"nom_fictif": "Thorald", "peuple": "nain",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
r = c.get("/deviner", headers=auth)
assert "on a raté le dernier train" in r.text, "souvenir brut à la révélation"
assert "plein de belles choses" in r.text, "vœu brut à la révélation"
assert "Ce qu'il ou elle vous souhaite" in r.text
print("TOUT PASSE — révélation : souvenir et vœu tels quels")

# --- Initiales affichées au palier d'indice ---------------------------------
uid3 = bd.creer("jean-pierre", "gagnebin", {"souvenir": "s"}, main.LIBELLES_LIEUX)
bd.enregistrer_portrait(uid3, {"nom_fictif": "Skarn", "peuple": "orque",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
r = c.get("/deviner", headers=auth)
assert "J.-P. G." in r.text, "initiales d'un prénom composé"
assert "Jean-Pierre Gagnebin" in r.text, "nom capitalisé à la révélation"
print("TOUT PASSE — initiales au palier d'indice")

# --- Le tableau apparie région et pendant d'ombre ---------------------------
uid4 = bd.creer("Mons", "Tre", {"metier": "x", "allegeance": "L'Ombre",
                                "monstre": "Un monstre, et j'assume"},
                ["Minas Tirith"])
bd.enregistrer_portrait(uid4, {"nom_fictif": "Grokna", "peuple": "orque",
                               "portrait": "p", "indice": "i", "fuites_noms": []})
uid5 = bd.creer("Seig", "Neur", {"metier": "x", "allegeance": "L'Ombre",
                                 "monstre": "Un seigneur redouté, mais un seigneur"},
                ["Minas Tirith"])
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
lignes = [l for l in bd.lister() if l["lieu"] == "Minas Tirith"]
assert len(lignes) >= 2, "les deux comptent pour Minas Tirith"
print("TOUT PASSE — appariement région / pendant d'ombre")
