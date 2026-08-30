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
# L'erreur revient sur l'écran d'où l'on vient, plutôt qu'en cul-de-sac : à
# 22 h, une page d'erreur sans chemin de retour est une page qu'on quitte.
assert r.status_code == 303, r.status_code
assert "intention=revoir" in r.headers["location"], r.headers["location"]
assert "Aucun%20personnage" in r.headers["location"], r.headers["location"]
assert bd.resoudre("Personne", "Inexistante").candidates == [], \
    "« revoir » ne doit jamais créer la personne qu'il cherche"
print("TOUT PASSE — revoir un nom inconnu ne crée rien")

# --- Une personne connue sans chronique, en « revoir » --------------------
with bd.Seance() as seance:
    orpheline = bd.creer_personne(seance, "sans", "chronique", source="import")
    seance.commit()
    uuid_orpheline = orpheline.uuid
r = test_outils.entrer_identite(seul, "sans", "chronique", intention="revoir")
assert r.status_code == 303, r.status_code
assert "erreur=" in r.headers["location"], r.headers["location"]
assert bd.chronique_de_personne(uuid_orpheline) is None, \
    "« revoir » ne doit pas créer de chronique en chemin"
# Le message revient bien à l'écran, et n'est pas seulement dans l'adresse.
suite = seul.get(r.headers["location"])
assert "aucun personnage" in texte(suite).lower(), texte(suite)[:400]
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
r = frais.post("/identite/libre", data={"intention": "creer", "prenom": "Cook",
                                        "nom": "Ie", "genre": "",
                                        "confirme": "oui"},
               follow_redirects=False)
brut = [v for k, v in r.headers.items()
        if k.lower() == "set-cookie" and identite.NOM_COOKIE in v]
assert brut, r.headers
assert "HttpOnly" in brut[0], brut[0]
assert "samesite=lax" in brut[0].lower(), brut[0]
assert "Secure" not in brut[0], "en HTTP local, Secure empêcherait toute reconnaissance"
print("TOUT PASSE — le cookie d'appareil est HttpOnly et SameSite=Lax")


# ============================================================================
# La sélection dans la liste importée (EX-AUTH-19, EX-AUTH-05, EX-AUTH-16)
# ============================================================================
import import_invites
from openpyxl import Workbook

_ATELIER = pathlib.Path("essais-liste")
_ATELIER.mkdir(exist_ok=True)


def _classeur(lignes, nom):
    livre = Workbook()
    livre.active.append(import_invites.COLONNES)
    for ligne in lignes:
        livre.active.append(list(ligne))
    chemin = _ATELIER / nom
    livre.save(chemin)
    return chemin


# Référence prise AVANT l'import : les blocs précédents ont peuplé la base, et
# une valeur absolue mesurerait leur travail autant que le nôtre. C'est la
# faute de l'étape 1, sous sa troisième forme.
_avant_import = sum(len(g["gens"]) for g in bd.annuaire())

import_invites.appliquer(_classeur([
    ["", "1", "Jérémy", "Schäer", "H", "oui", "non"],
    ["", "1", "Coralie", "", "F", "non", "non"],
    ["", "2", "Jérémy", "", "H", "non", "non"],
    ["", "2", "Delphine", "Schäer", "F", "non", "non"],
    ["", "2", "Marc", "Meier", "H", "non", "non"],
], "liste.xlsx"))
liste = test_outils.client(main.app)

# --- Toute la liste part dans la page, groupée par table -----------------
page = texte(liste.get("/identite?intention=creer"))
assert sum(len(g["gens"]) for g in bd.annuaire()) == _avant_import + 5
assert page.count('class="choix personne"') == _avant_import + 5, \
    "la page doit porter TOUS les noms, pas une page de résultats"
for attendu in ("Jérémy Schäer", "Coralie", "Marc Meier"):
    assert attendu in page, attendu
assert page.count("groupe-table") >= 2, "les noms doivent être groupés par table"
# EX-AUTH-16 — la recherche se fait DANS la page : sans requête, elle survit à
# une 4G qui flanche au mauvais moment.
assert 'id="filtre"' in page and "addEventListener" in page
assert "/identite/libre" in page, "« je ne suis pas dans la liste » doit être offert"
print("TOUT PASSE — la liste entière part dans la page, groupée par table")

# --- Ceux qui ont déjà un personnage sont visibles ET signalés -----------
marc = bd.resoudre("Marc", "Meier").unique
uid_marc = bd.creer(marc.uuid, {"metier": "forgeron"}, main.CODES_LIEUX)
page = texte(liste.get("/identite?intention=creer"))
assert "Marc Meier" in page, "les masquer empêcherait de retrouver son personnage"
assert "a déjà un personnage" in page, "l'état doit être dit, pas deviné"
# La mention ne colle pas à tout le monde : autant de mentions que de personnes
# ayant réellement une chronique, comptées et non supposées.
_attendues = sum(1 for g in bd.annuaire() for p in g["gens"] if p["a_une_chronique"])
assert page.count("a déjà un personnage") == _attendues, \
    (page.count("a déjà un personnage"), _attendues)
assert _attendues < sum(len(g["gens"]) for g in bd.annuaire()), \
    "si tout le monde en a une, le contrôle ne prouve rien"
print("TOUT PASSE — ceux qui ont déjà joué restent visibles et sont signalés")

# --- Choisir un nom mène au questionnaire de CETTE personne -------------
delphine = bd.resoudre("Delphine", "Schäer").unique
r = liste.post("/identite/choisir",
               data={"personne_uuid": delphine.uuid, "intention": "creer"},
               follow_redirects=False)
assert r.status_code == 200 and "Quel est ton métier" in r.text, r.status_code
assert f'name="personne_uuid" value="{delphine.uuid}"' in r.text
assert bd.personne_de_l_appareil(liste.cookies.get(identite.NOM_COOKIE)).uuid \
    == delphine.uuid
print("TOUT PASSE — choisir un nom ouvre le questionnaire de cette personne")

# --- Une personne sans nom se voit proposer de le compléter -------------
sans = test_outils.client(main.app)
coralie = bd.resoudre("Coralie", "").unique
assert coralie.nom == "", "référence prise avant l'action"
r = sans.post("/identite/choisir",
              data={"personne_uuid": coralie.uuid, "intention": "creer"},
              follow_redirects=False)
assert r.status_code == 200 and "Bonjour Coralie" in texte(r), texte(r)[:400]
assert "Quel est ton métier" not in r.text, "le questionnaire ne doit pas s'ouvrir avant"

r = sans.post("/identite/completer",
              data={"personne_uuid": coralie.uuid, "prenom": "coralie",
                    "nom": "berthoud", "intention": "creer"},
              follow_redirects=False)
assert r.status_code == 200 and "Quel est ton métier" in r.text
# EX-AUTH-21 — capitalisé ici comme à la création.
relue = bd.personne(coralie.uuid)
assert (relue.prenom, relue.nom) == ("Coralie", "Berthoud"), (relue.prenom, relue.nom)

# Et passer sans rien saisir n'est pas bloquant : la lacune reste, la soirée
# continue.
autre = test_outils.client(main.app)
jeremy_sans_nom = [p for p in bd.resoudre("Jérémy", "").candidates][0]
r = autre.post("/identite/completer",
               data={"personne_uuid": jeremy_sans_nom.uuid, "prenom": "Jérémy",
                     "nom": "", "intention": "creer"}, follow_redirects=False)
assert r.status_code == 200 and "Quel est ton métier" in r.text
assert bd.personne(jeremy_sans_nom.uuid).nom == ""
print("TOUT PASSE — le nom manquant se complète, ou se saute sans conséquence")

# --- La saisie libre propose les ressemblances avant de créer -----------
# Trois règles, chacune exigeant une composante EXACTE : jamais flou sur les
# deux à la fois, sinon « Marie Meyer » et « Marc Meyer » se confondraient.
# Le seuil doit attraper ce qu'il vise ET rejeter le reste. Mesuré sur les
# seuls faux positifs, 0,85 semblait gratuit — et rejetait « Meier » contre
# « Meyer », l'exemple même du cahier des charges, qui vaut 0,800.
for _a, _b, _attendu in (("Meyer", "Meier", True), ("Mayer", "Meyer", True),
                         ("Durand", "Durant", True), ("Schär", "Schäer", True),
                         ("Meyer", "Muller", False), ("Dupont", "Durand", False)):
    _proche = bd._ressemblent(bd._cle_floue(_a), bd._cle_floue(_b))
    assert _proche is _attendu, (
        f"« {_a} » / « {_b} » : rapproché={_proche}, attendu={_attendu} — "
        f"seuil {bd.SEUIL_RESSEMBLANCE}")

# JAMAIS flou sur les deux composantes à la fois. « Martin Durant » et
# « Martine Durand » se ressemblent des deux côtés — 0,923 et 0,833 — et sont
# pourtant deux personnes, souvent un couple. Un flou double les rapprocherait,
# et noierait chaque invité d'une famille nombreuse sous des confirmations.
import_invites.appliquer(_classeur([
    ["", "3", "Martin", "Durant", "H", "non", "non"],
    # Une lacune FRAÎCHE : Coralie a été complétée par le bloc précédent, elle
    # n'en est donc plus une, et le contrôle porterait sur autre chose que ce
    # qu'il annonce.
    ["", "3", "Nolwenn", "", "F", "non", "non"],
], "couple.xlsx"))
assert not bd.rapprochements("Martine", "Durand"), \
    "flou sur les deux composantes : « Martine Durand » a été rapprochée de " \
    "« Martin Durant », qui est quelqu'un d'autre"
# Mais chacune des deux règles fonctionne seule.
assert [m for _, m in bd.rapprochements("Martin", "Durand")] == ["nom_proche"]
assert [m for _, m in bd.rapprochements("Martine", "Durant")] == ["prenom_proche"]

# Et la règle du nom absent se vérifie SEULE : « Nolwenn Kervella » ne
# ressemble à personne d'autre, seule la lacune de la liste la rattrape.
_lacune = bd.rapprochements("Nolwenn", "Kervella")
assert [m for _, m in _lacune] == ["nom_absent"], _lacune
assert (_lacune[0][0].prenom, _lacune[0][0].nom) == ("Nolwenn", "")
# Sans cette règle, les 48 invités importés sans nom de famille créeraient
# chacun un doublon en tapant leur vrai nom.
assert _lacune[0][0].nom_table, "l'écran doit pouvoir dire à quelle table"

# Référence prise ICI, après les imports de ce bloc : calculée plus haut, elle
# aurait compté les personnes ajoutées entre-temps et l'écart n'aurait plus
# rien mesuré. Quatrième forme de la même faute.
combien_avant = sum(len(g["gens"]) for g in bd.annuaire())

libre = test_outils.client(main.app)
r = libre.post("/identite/libre",
               data={"intention": "creer", "prenom": "Marc", "nom": "Meyer",
                     "genre": "masculin"}, follow_redirects=False)
assert r.status_code == 200, r.status_code
assert "Êtes-vous déjà sur la liste" in texte(r), texte(r)[:400]
assert "Marc Meier" in texte(r), "le nom proche doit être proposé"
apres = sum(len(g["gens"]) for g in bd.annuaire())
assert apres == combien_avant, "une personne a été créée avant confirmation"
print("TOUT PASSE — un nom ressemblant ouvre une confirmation, sans rien créer")

# --- « Je suis quelqu'un d'autre » crée bien, et ne reboucle pas --------
r = libre.post("/identite/libre",
               data={"intention": "creer", "prenom": "Marc", "nom": "Meyer",
                     "genre": "masculin", "confirme": "oui"},
               follow_redirects=False)
assert r.status_code == 200 and "Quel est ton métier" in r.text, r.status_code
assert "Êtes-vous déjà sur la liste" not in r.text, \
    "reproposer l'écran en boucle enfermerait l'invité"
nouveau = bd.resoudre("Marc", "Meyer").unique
assert nouveau is not None and nouveau.uuid != marc.uuid
assert nouveau.genre == "masculin"
print("TOUT PASSE — « je suis quelqu'un d'autre » crée sans reboucler")

# --- Confirmer « c'est moi » reprend le nom saisi -----------------------
# L'invité a tapé un nom plus complet que celui de la liste : on le lui reprend
# plutôt que de le lui refaire taper.
encore = test_outils.client(main.app)
r = encore.post("/identite/libre",
                data={"intention": "creer", "prenom": "Jérémy", "nom": "Schär"},
                follow_redirects=False)
assert "Êtes-vous déjà sur la liste" in texte(r), texte(r)[:300]
r = encore.post("/identite/choisir",
                data={"personne_uuid": jeremy_sans_nom.uuid, "intention": "creer",
                      "prenom_complet": "Jérémy", "nom_complet": "Schär"},
                follow_redirects=False)
assert r.status_code == 200 and "Quel est ton métier" in r.text, r.status_code
assert bd.personne(jeremy_sans_nom.uuid).nom == "Schär", \
    "le nom saisi devait combler la lacune de la liste"
print("TOUT PASSE — confirmer « c'est moi » reprend le nom saisi")

# --- La table facultative s'enregistre, et son absence ne bloque pas ----
avec_table = test_outils.client(main.app)
code = bd.tables()[0]["code"]
r = avec_table.post("/identite/libre",
                    data={"intention": "creer", "prenom": "Venu", "nom": "Tard",
                          "genre": "", "code_table": code, "confirme": "oui"},
                    follow_redirects=False)
assert r.status_code == 200 and "Quel est ton métier" in r.text
place = [p for g in bd.annuaire() for p in g["gens"] if p["prenom"] == "Venu"][0]
assert place["code_table"] == code, place

sans_table = test_outils.client(main.app)
r = sans_table.post("/identite/libre",
                    data={"intention": "creer", "prenom": "Sans", "nom": "Place",
                          "genre": "", "code_table": "", "confirme": "oui"},
                    follow_redirects=False)
assert r.status_code == 200 and "Quel est ton métier" in r.text, \
    "ne pas savoir sa table ne doit pas empêcher de jouer"

# Un code de table inventé n'attache personne n'importe où.
assert bd.affecter_table(bd.resoudre("Sans", "Place").unique.uuid, "table-fantome") is False
print("TOUT PASSE — la table est facultative, et un code inventé n'attache rien")

# --- Avant tout import, la liste vide n'est pas une impasse ------------
# Sur une base neuve — le matin du 5 septembre, avant l'import — un écran de
# sélection vide renverrait l'invité à rien.
_vraie = bd.annuaire
bd.annuaire = lambda: []
try:
    r = liste.get("/identite?intention=creer", follow_redirects=False)
    assert r.status_code == 303, r.status_code
    assert "/identite/libre" in r.headers["location"], r.headers["location"]
finally:
    bd.annuaire = _vraie
print("TOUT PASSE — sans liste, on est mené à la saisie libre")

import shutil
shutil.rmtree(_ATELIER, ignore_errors=True)
