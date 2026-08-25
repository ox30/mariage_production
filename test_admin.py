"""Tables et régions modifiables. Lancer : python test_admin.py"""
import base64, html as _html, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")
from openpyxl import Workbook
import base_donnees as bd, import_invites, main, modeles, test_outils
from sqlalchemy import select

AUTH = {"Authorization": "Basic " + base64.b64encode(b"a:secret").decode()}
ATELIER = pathlib.Path("essais-admin")
ATELIER.mkdir(exist_ok=True)
c = test_outils.client(main.app)


def classeur(lignes, nom):
    livre = Workbook()
    livre.active.append(import_invites.COLONNES)
    for ligne in lignes:
        livre.active.append(list(ligne))
    chemin = ATELIER / nom
    livre.save(chemin)
    return chemin


LISTE = classeur([
    ["", "3", "Aria", "Sonval", "F", "non", "non"],
    ["", "3", "Bilbon", "Sacquet", "H", "non", "non"],
    ["", "7", "Cora", "Lie", "F", "non", "non"],
], "liste.xlsx")
import_invites.appliquer(LISTE)

# --- Les régions sont semées depuis questions.yaml, une seule fois ---------
regions = bd.regions()
assert len(regions) == len(main.CONFIG["lieux"]), (len(regions), len(main.CONFIG["lieux"]))
for lieu in main.CONFIG["lieux"]:
    assert regions[lieu["code"]]["libelle"] == lieu["libelle"], lieu["code"]
    assert regions[lieu["code"]]["locution"] == lieu["locution"], lieu["code"]

# Un second semis n'écrase RIEN : sans cela, chaque redémarrage effacerait les
# renommages faits pendant la soirée.
bd.modifier_region("lieu_02", "Imladris", "à Imladris", "les gorges")
assert bd.semer_regions(main.CONFIG["lieux"]) == 0, "le semis a réécrit"
assert bd.regions()["lieu_02"]["libelle"] == "Imladris", \
    "un redémarrage effacerait le travail de la soirée"
print("TOUT PASSE — les régions sont semées une fois, jamais réécrites")

# --- Renommer une région n'orpheline aucune chronique (EX-IA-28) ----------
uid = test_outils.creer_chronique("Chro", "Nique", {"metier": "x"}, main.CODES_LIEUX)
code_avant = bd.lire(uid).lieu
bd.modifier_region(code_avant, "Nom Tout Neuf", "à Nom Tout Neuf", "la marge")
assert bd.lire(uid).lieu == code_avant, "la chronique a changé de région"
assert main.libelle_lieu(code_avant) == "Nom Tout Neuf"
assert main.locution_lieu(code_avant) == "à Nom Tout Neuf"

# La chronique porte le CODE : c'est ce qui rend le renommage sans danger.
assert bd.lire(uid).lieu.startswith("lieu_"), bd.lire(uid).lieu
print("TOUT PASSE — renommer une région ne touche à aucune chronique")

# --- La locution est relue à chaud, pas figée au démarrage ---------------
# EX-ADM-22 veut la modification « y compris après ouverture de la soirée » :
# figée au démarrage, elle demanderait un redéploiement, qu'EX-SAU-09 interdit.
bd.modifier_region("lieu_01", "La Comté", "en Comté", "les Galgals")
assert main.locution_lieu("lieu_01") == "en Comté"
bd.modifier_region("lieu_01", "Les Deux Tours", "aux Deux Tours", "les Galgals")
assert main.locution_lieu("lieu_01") == "aux Deux Tours", \
    "la locution est figée : un renommage à 21 h resterait invisible"

# Et la page du portrait suit, sans redémarrage.
uid2 = test_outils.creer_chronique("Sui", "Vi", {"metier": "x"}, ["lieu_01"])
page = _html.unescape(c.get(f"/portrait/{uid2}").text)
assert "convoquera <strong>aux Deux Tours</strong>" in page, page[:500]
print("TOUT PASSE — libellé et locution suivent sans redémarrage")

# --- Le code d'une table ne bouge jamais, son nom oui --------------------
tables = bd.tables()
assert [t["code"] for t in tables] == ["3", "7"], tables
assert all(t["code"] == t["nom"] for t in tables), "au départ, nom = code"
assert {t["code"]: t["effectif"] for t in tables} == {"3": 2, "7": 1}

table_3 = [t for t in tables if t["code"] == "3"][0]
assert bd.renommer_table(table_3["uuid"], "Fondcombe")
apres = {t["code"]: t["nom"] for t in bd.tables()}
assert apres == {"3": "Fondcombe", "7": "7"}, apres

# L'effectif se COMPTE, il ne se stocke pas (EX-GEN-07).
with bd.Seance() as seance:
    orpheline = bd.creer_personne(seance, "Hors", "Table", source="import")
    seance.commit()
assert {t["code"]: t["effectif"] for t in bd.tables()} == {"3": 2, "7": 1}
print("TOUT PASSE — une table se renomme sans que son code bouge")

# --- Réimporter après renommage ne crée pas de table fantôme ------------
# LE défaut que cette migration ferme : l'import rapprochait les tables par
# leur nom. Renommer « 3 » en « Fondcombe » puis réimporter le fichier — qui
# porte toujours Table = 3 — créait une SECONDE table « 3 » et y déplaçait ses
# invités, en silence.
avant_tables = len(bd.tables())
uuid_avant = {t["code"]: t["uuid"] for t in bd.tables()}
plan = import_invites.preparer(LISTE)
assert plan.recevable, plan.erreurs
assert not plan.creations and not plan.modifications, \
    f"un renommage de table fait croire à un changement : {plan.modifications}"
import_invites.appliquer(LISTE)
assert len(bd.tables()) == avant_tables, "une table fantôme est apparue"
assert {t["code"]: t["uuid"] for t in bd.tables()} == uuid_avant, "un uuid a bougé"
assert [t["nom"] for t in bd.tables() if t["code"] == "3"] == ["Fondcombe"], \
    "le nom choisi a été écrasé par le fichier"
print("TOUT PASSE — réimporter après renommage ne crée aucune table fantôme")

# --- Les trois onglets répondent, et sont fermés ------------------------
for chemin in ("/admin/invites", "/admin/tables", "/admin/regions"):
    assert c.get(chemin).status_code == 401, f"{chemin} est ouvert à tous"
    page = c.get(chemin, headers=AUTH)
    assert page.status_code == 200, (chemin, page.status_code)
    # Chaque onglet est un LIEN : un onglet qui vivrait en mémoire serait
    # perdu dès que l'écran du téléphone se verrouille.
    for autre in ("/admin/invites", "/admin/tables", "/admin/regions"):
        assert f'href="{autre}"' in page.text, f"{chemin} n'offre pas {autre}"
    assert 'class="onglet actif"' in page.text, f"{chemin} n'indique pas où l'on est"
print("TOUT PASSE — les trois onglets répondent, fermés, et se désignent")

# --- Les écrans écrivent bien ce qu'on leur donne ----------------------
table_7 = [t for t in bd.tables() if t["code"] == "7"][0]
c.post("/admin/tables", headers=AUTH, data={f"nom_{table_7['uuid']}": "Glamdring"})
assert [t["nom"] for t in bd.tables() if t["code"] == "7"] == ["Glamdring"]

# Un nom vide ne l'efface pas : un champ effacé par mégarde à 21 h laisserait
# une table sans nom sur l'écran de sélection.
c.post("/admin/tables", headers=AUTH, data={f"nom_{table_7['uuid']}": "   "})
assert [t["nom"] for t in bd.tables() if t["code"] == "7"] == ["Glamdring"]

c.post("/admin/regions", headers=AUTH,
       data={"libelle_lieu_03": "La Moria", "locution_lieu_03": "dans la Moria",
             "ombre_lieu_03": "les puits"})
assert main.libelle_lieu("lieu_03") == "La Moria"
assert main.locution_lieu("lieu_03") == "dans la Moria"
assert bd.regions()["lieu_03"]["ombre"] == "les puits"

# Les autres régions ne bougent pas : le formulaire les renvoie toutes, et une
# écriture aveugle les remplacerait par des champs vides.
assert main.libelle_lieu("lieu_02") == "Imladris", "une région non touchée a bougé"

# Un champ effacé par mégarde ne vide pas la région. Éprouvé en POSTANT un
# champ vide, et non en s'en remettant au fait que le formulaire les renvoie
# tous : c'est précisément le cas où quelqu'un sélectionne un libellé et
# appuie sur Supprimer avant d'enregistrer.
c.post("/admin/regions", headers=AUTH,
       data={"libelle_lieu_03": "", "locution_lieu_03": "",
             "ombre_lieu_03": "les puits"})
assert main.libelle_lieu("lieu_03") == "La Moria", \
    "un libellé effacé par mégarde laisserait une région sans nom sur la carte"
assert main.locution_lieu("lieu_03") == "dans la Moria"
# L'ombre, elle, s'efface : c'est le seul des trois qui puisse légitimement
# être vide, et le repli d'affichage la remplace.
c.post("/admin/regions", headers=AUTH,
       data={"libelle_lieu_03": "La Moria", "locution_lieu_03": "dans la Moria",
             "ombre_lieu_03": ""})
assert bd.regions()["lieu_03"]["ombre"] == ""
print("TOUT PASSE — les écrans écrivent, et n'effacent pas sur un champ vide")

import shutil
shutil.rmtree(ATELIER, ignore_errors=True)
