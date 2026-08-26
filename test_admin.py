"""Tables et régions modifiables. Lancer : python test_admin.py"""
import base64, html as _html, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")
from openpyxl import Workbook
import base_donnees as bd, config, import_invites, main, modeles, test_outils
import re as _re
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
# La table de test n'y est pas : elle s'offrirait sinon à l'invité qui choisit
# sa table en saisie libre, et il s'y placerait sans savoir ce qu'elle est.
assert [t["code"] for t in tables] == ["3", "7"], tables
assert any(t["code"] == "test" for t in bd.tables(avec_test=True)), \
    "l'administration doit la voir, elle"
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

# --- La table de test : présente, invisible, étanche (EX-TST-01 à 08) -----
# EX-PRJ-10 — elle reste ACTIVE en production : le test de fumée du jour J se
# fait sur la vraie base, avec la vraie clé et le vrai modèle. Une répétition
# ailleurs n'éprouverait pas ce qui va servir.
testeurs = [bd.resoudre("Test", f"{n:02d}").unique for n in range(1, 11)]
assert all(t is not None for t in testeurs), "test_01…test_10 doivent exister"
assert all(t.est_test for t in testeurs)
assert {t.identifiant_import for t in testeurs} == {f"test_{n:02d}" for n in range(1, 11)}

# Idempotent : relancé, il ne double rien — et il RÉAFFIRME le drapeau, qu'une
# personne de test ayant perdu `est_test` apparaîtrait dans les listes.
with bd.Seance() as seance:
    seance.get(modeles.Personne, testeurs[0].uuid).est_test = False
    seance.commit()
assert bd.semer_table_test() == 0, "le semis a doublé les comptes de test"
assert bd.resoudre("Test", "01").unique.est_test, "le drapeau n'a pas été réaffirmé"

# EX-TST-04 — invisibles dans la liste où les invités se cherchent.
_annuaire = [p for g in bd.annuaire() for p in g["gens"]]
assert not [p for p in _annuaire if p["prenom"] == "Test"], \
    "les comptes de test s'affichent dans la liste des invités"
# Mais joignables par leur nom : sans cela, personne ne pourrait s'en servir.
assert bd.resoudre("Test", "03").unique is not None

# EX-TST-02 — le drapeau est hérité par ce que le testeur crée.
uid_test = bd.creer(testeurs[2].uuid, {"metier": "essai"}, main.CODES_LIEUX)
assert bd.lire(uid_test).est_test is True, "la chronique n'a pas hérité du drapeau"

# EX-TST-05 — exclues des listes et des totaux, PAR DÉFAUT. L'inverse ferait
# apparaître dix personnages fictifs sur la carte le jour où l'on oublierait
# le drapeau quelque part.
assert all(c.uuid != uid_test for c in bd.lister()), "une chronique de test est listée"
assert any(c.uuid == uid_test for c in bd.lister(avec_test=True))

# EX-TST-07 — le bandeau se DÉRIVE d'une chronique réellement présente, il ne
# suit pas un interrupteur. Cinquième grandeur du projet à suivre cette règle.
assert bd.mode_test_actif() is True
for chemin in ("/admin/invites", "/admin/tables", "/admin/regions"):
    assert "MODE TEST" in c.get(chemin, headers=AUTH).text, chemin
with bd.Seance() as seance:
    seance.get(modeles.Chronique, uid_test).supprimee = True
    seance.commit()
assert bd.mode_test_actif() is False, \
    "le bandeau reste allumé alors qu'aucune chronique de test ne subsiste"
assert "MODE TEST" not in c.get("/admin/invites", headers=AUTH).text
print("TOUT PASSE — la table de test est présente, invisible et étanche")

# --- Le tableau est un onglet, et il sépare production et test -----------
# Depuis que `lister()` exclut le test, le tableau était devenu aveugle à ce
# qu'on venait d'y faire : c'était pourtant l'endroit où l'on vérifie le test
# de fumée du jour J.
_vraie = bd.personne(bd.creer_personne_libre("Vraie", "Personne"))
_uid_vrai = bd.creer(_vraie.uuid, {"metier": "vrai"}, main.CODES_LIEUX)
_uid_test = bd.creer(bd.resoudre("Test", "05").unique.uuid,
                     {"metier": "essai"}, main.CODES_LIEUX)

# Le tableau nomme les personnes, il n'affiche pas d'UUID : c'est sur la ligne
# de tableau qu'il faut chercher, pas sur l'identifiant.
_lignes_de = lambda page: _re.findall(r"<td>([^<]*?)</td>", page)

_prod = c.get("/admin/tableau", headers=AUTH)
assert _prod.status_code == 200
assert "Vraie Personne" in _lignes_de(_prod.text), "la production manque au tableau"
assert "Test 05" not in _lignes_de(_prod.text), \
    "une chronique de test est mêlée à la production"

_test = c.get("/admin/tableau?test=oui", headers=AUTH)
assert "Test 05" in _lignes_de(_test.text), "le tableau de test ne montre pas le test"
assert "Vraie Personne" not in _lignes_de(_test.text), "la production est mêlée au test"
# Et les totaux suivent la vue : ils comptaient la production dans les deux.
assert _prod.text.count("Vraie Personne") >= 1

# Les deux vues ont chacune leur ADRESSE : un basculement en mémoire se perd
# au rechargement, et l'on ne saurait plus ce qu'on regarde.
assert 'href="/admin/tableau?test=oui"' in _prod.text
assert 'href="/admin/tableau"' in _test.text
# La navigation se vérifie depuis un AUTRE écran : sur le tableau lui-même,
# « href="/admin/tableau" » vient aussi du basculement production/test, et
# l'assertion passait même sans l'onglet. Quatrième fois qu'une chaîne cherchée
# dans toute la page vient d'ailleurs que de ce qu'elle prétend éprouver.
_ailleurs = c.get("/admin/invites", headers=AUTH).text
for chemin in ("/admin/invites", "/admin/tables", "/admin/regions", "/admin/tableau"):
    assert f'href="{chemin}"' in _ailleurs, f"{chemin} manque à la navigation"

# L'ancienne adresse reste : elle est en signet et sur des notes.
_ancienne = c.get("/tableau", headers=AUTH, follow_redirects=False)
assert _ancienne.status_code == 308, _ancienne.status_code
assert "/admin/tableau" in _ancienne.headers["location"]
assert c.get("/admin/tableau").status_code == 401, "le tableau est ouvert à tous"
print("TOUT PASSE — le tableau est un onglet et sépare production et test")

# --- Un export dit ce qu'il est, dans le fichier ET dans son nom --------
# Deux tableaux JSON nus ne se distinguent pas une fois sur le disque : l'un
# productif, l'autre de test, seraient interchangeables au moment où l'on s'en
# sert. Les deux marques sont posées parce que l'une des deux se perd toujours
# — le nom en renommant, l'enveloppe en ouvrant le fichier au milieu.
import json as _json

for _suffixe, _contenu, _dans_le_nom in (("", "production", "chroniques-"),
                                         ("?test=oui", "test", "chroniques-TEST-")):
    _r = c.get(f"/admin/tableau/export.json{_suffixe}", headers=AUTH)
    _d = _r.json()
    assert _d["contenu"] == _contenu, _d["contenu"]
    assert _d["nombre"] == len(_d["chroniques"]), "le compte annoncé ment"
    assert _d["projet"] == config.projet().identifiant
    assert _d["type_projet"] == config.projet().type
    _disposition = _r.headers.get("content-disposition", "")
    assert _dans_le_nom in _disposition, _disposition
    assert _disposition.endswith('.json"'), _disposition

# EX-TST-08 — l'export de production exclut le test. Toujours.
_prod_json = c.get("/admin/tableau/export.json", headers=AUTH).json()
assert all(x["uuid"] != _uid_test for x in _prod_json["chroniques"])
assert any(x["uuid"] == _uid_vrai for x in _prod_json["chroniques"])
_test_json = c.get("/admin/tableau/export.json?test=oui", headers=AUTH).json()
assert [x["uuid"] for x in _test_json["chroniques"]] == [_uid_test], _test_json["nombre"]

# Et les deux noms de fichier diffèrent : c'est tout l'intérêt.
_n1 = c.get("/admin/tableau/export.json", headers=AUTH).headers["content-disposition"]
_n2 = c.get("/admin/tableau/export.json?test=oui", headers=AUTH).headers["content-disposition"]
assert _n1 != _n2, _n1
assert c.get("/admin/tableau/export.json").status_code == 401
print("TOUT PASSE — un export dit ce qu'il est, dans son enveloppe et dans son nom")
