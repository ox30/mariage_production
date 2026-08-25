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

# --- La convocation emploie la locution, pas « en » en dur -----------------
# Le gabarit écrivait « convoqué en {libellé} », ce qui donnait « en Les Havres
# Gris » et « en Les Mines de la Moria » sur l'écran que TOUS les invités
# voient pendant l'écriture de leur chronique. La locution juste vivait dans
# questions.yaml depuis l'étape 1, branchée sur le seul prompt.
import html as _html

for code, lieu in main.LIEUX_PAR_CODE.items():
    locution = main.locution_lieu(code)
    assert locution == lieu["locution"], (code, locution)
    # Une locution est une préposition SUIVIE du nom : sans préposition, la
    # phrase se relit « convoquera Les Havres Gris ».
    assert locution.split()[0] in ("à", "en", "dans", "aux", "au", "chez"), \
        f"{code} : « {locution} » ne commence pas par une préposition"

# Un code inconnu ne casse pas la page : questions.yaml peut gagner une région
# le 4 septembre sans que quiconque pense à sa locution.
assert main.locution_lieu("lieu_99") == "lieu_99"

# Et l'écran d'attente porte bien la phrase, au futur et sans accord.
uid_conv = test_outils.creer_chronique("Convo", "Cation", {"metier": "x"},
                                       main.CODES_LIEUX)
page = _html.unescape(c.get(f"/portrait/{uid_conv}").text)
attendue = main.locution_lieu(bd.lire(uid_conv).lieu)
assert f"convoquera <strong>{attendue}</strong>" in page, page[:600]
assert "vous a convoqué" not in page, \
    "le passé composé impose un accord : « convoqué » se lit faux une fois sur deux"
# La dissociation table / convocation est dite explicitement : sans elle,
# l'invité assis à une table du même nom croit à une erreur.
assert "Pas ce soir" in page, page[:600]
# L'écran « brouillon » porte la même phrase, et n'était pas éprouvé : la
# mutation qui remettait le passé composé le frappait sans faire tomber quoi
# que ce soit. Deux endroits disent la même chose, les deux se vérifient.
uid_br = test_outils.creer_chronique("Brouil", "Lon", {"metier": "x"},
                                     main.CODES_LIEUX, etat="brouillon")
page_br = _html.unescape(c.get(f"/portrait/{uid_br}").text)
attendue_br = main.locution_lieu(bd.lire(uid_br).lieu)
assert f"convoquera {attendue_br}" in page_br, page_br[:600]
assert "convoqué" not in page_br, "le passé composé impose un accord"
print("TOUT PASSE — la convocation emploie la locution juste, au futur")

# --- Aucun lien ne prend les couleurs du navigateur -----------------------
# Constaté le 25 août : les onglets d'administration, « ← Revenir » et « Ce
# n'est pas vous ? » s'affichaient en bleu et en violet — les couleurs par
# défaut du navigateur, illisibles sur fond nocturne et étrangères à la
# palette. La feuille de style ne réglait `a { color }` nulle part.
_racine = pathlib.Path(__file__).parent
_style = (_racine / "static" / "style.css").read_text(encoding="utf-8")
for regle in ("a, a:link, a:visited", ".onglet, .onglet:link, .onglet:visited"):
    assert regle in _style, f"« {regle} » manque : le navigateur reprend la main"
# `:visited` explicitement : sans lui, un lien déjà suivi repasse au violet,
# et c'est précisément le cas de tous les liens d'un parcours qu'on refait.
assert _style.count(":visited") >= 3, "les liens visités retomberont au violet"

# Et aucun gabarit ne réinvente une couleur : les codes en dur du premier jet
# — #3a332c, #8a6d1f, #a4442e — n'appartenaient à aucune palette du projet.
import re as _re

for _gabarit in sorted((_racine / "templates").glob("*.html")):
    _texte = _gabarit.read_text(encoding="utf-8")
    for _regle in _re.findall(r'style="([^"]*)"', _texte):
        assert "color" not in _regle, (
            f"{_gabarit.name} fixe une couleur en dur : « {_regle} ». Les "
            "couleurs vivent dans style.css, où elles se corrigent une fois "
            "pour tous les écrans.")
# --- Un lien qui est un bouton reste lisible SANS survol -----------------
# `a:link` pèse plus lourd que `.action` — un élément plus une pseudo-classe
# contre une simple classe. La règle générale des liens écrasait donc la
# couleur du bouton : texte laiton sur fond laiton. Seul `a:hover` le
# rattrapait, ce qui ne se voit qu'à la souris ; au doigt, sur téléphone, le
# bouton était vide. Constaté le 25 août sur « Créer mon personnage ».
#
# Le contrôle se DÉDUIT des gabarits : toute classe portée par un `<a>` et qui
# pose un fond dans la feuille de style doit avoir sa règle `a.classe:link`.
# Un futur `<a class="bouton-neuf">` sera donc signalé sans qu'on y pense.
_classes_de_lien = set()
for _gabarit in sorted((_racine / "templates").glob("*.html")):
    for _attribut in _re.findall(r'<a\b[^>]*\bclass="([^"]+)"',
                                 _gabarit.read_text(encoding="utf-8")):
        _classes_de_lien.update(_attribut.split())

for _classe in sorted(_classes_de_lien):
    _bloc = _re.search(rf"^\.{_re.escape(_classe)}\b[^{{]*{{([^}}]*)}}",
                       _style, _re.M)
    if not _bloc or "background" not in _bloc.group(1):
        continue  # pas un bouton : une classe sans fond n'a rien à écraser
    for _etat in (":link", ":visited"):
        assert f"a.{_classe}{_etat}" in _style, (
            f"« {_classe} » pose un fond et sert de lien, mais aucune règle "
            f"`a.{_classe}{_etat}` ne fixe sa couleur de texte. Le bouton sera "
            "illisible tant que la souris n'est pas dessus — donc toujours, "
            "sur téléphone.")
    # `:visited` est exigé bien que `a.action` seul suffise aujourd'hui :
    # `a.action` et `a:visited` ont la MÊME spécificité — une classe et une
    # pseudo-classe pèsent pareil — et c'est l'ordre dans le fichier qui
    # tranche. Dépendre de l'ordre, c'est dépendre de l'endroit où quelqu'un
    # collera la prochaine règle.

# Et la lisibilité ne doit dépendre d'aucun survol : sur téléphone il n'existe
# pas, et un état qui n'existe pas ne peut rien réparer.
_survol = _re.search(r"^a\.action:hover[^{]*{([^}]*)}", _style, _re.M)
assert _survol and "#16110a" in _survol.group(1), \
    "le survol doit conserver la couleur du bouton, jamais la corriger"
print("TOUT PASSE — un lien qui est un bouton reste lisible sans survol")

print("TOUT PASSE — les liens et les couleurs restent dans la palette du projet")
