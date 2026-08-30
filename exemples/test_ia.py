"""Client d'API : une tentative, exceptions typées. python test_ia.py

Couvre EX-ARC-13 (le réessai appartient au worker, jamais au client),
EX-IA-19 et EX-IA-22 (429 avec `retry-after` contre 529), EX-IA-31 modifiée
v3.15 (le doublon de nom est signalé, plus rejeté), EX-IA-44 (détection
dérivée) et EX-IA-45 (invite et réponse brute consignées).

Aucun appel réseau : `httpx.post` est remplacé par une fonction d'essai. Ce
qui est éprouvé ici, c'est la **décision** prise face à chaque réponse, pas
la capacité d'Anthropic à répondre.
"""
import inspect
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", "secret")
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-essai"

import httpx

import base_donnees as bd
import ia
import main

CONFIG = main.CONFIG
PARTICIPATION = {
    "lieu": main.LIEUX_PAR_CODE["lieu_07"],
    "reponses": {"metier": "Fauconnier", "attachement": "Ma famille",
                 "defaut": "Têtu", "objet": "Ma longue-vue",
                 "allegeance": "La Lumière", "souvenir_avec": "Les deux",
                 "souvenir": "Un été", "souhait": "Joie"},
    "noms_interdits": ["Florian", "Sandoz"],
    "noms_fictifs_pris": ["Borin Fendroc"],
    "genre": "masculin",
    "motif_reprise": None,
    "couple": main.COUPLE,
}

PORTRAIT_VALIDE = {"nom_fictif": "Aldor Vaillegarde", "peuple": "homme",
                   "portrait": "Un texte de portrait.", "indice": "Un indice."}


class FausseReponse:
    def __init__(self, code=200, charge=None, entetes=None, texte=None):
        self.status_code = code
        self.headers = entetes or {}
        self._charge = charge
        self.text = texte if texte is not None else json.dumps(charge or {})

    def json(self):
        if self._charge is None:
            raise ValueError("pas du JSON")
        return self._charge


def repondre(*reponses):
    """Remplace httpx.post et compte les appels réellement émis."""
    appels = []

    def faux_post(url, json=None, headers=None, timeout=None):
        appels.append(json)
        reponse = reponses[min(len(appels) - 1, len(reponses) - 1)]
        if isinstance(reponse, Exception):
            raise reponse
        return reponse

    httpx.post = faux_post
    return appels


def charge_utile(portrait, stop="end_turn", entree=4200, sortie=2800):
    return {"content": [{"type": "text", "text": json.dumps(portrait)}],
            "stop_reason": stop,
            "usage": {"input_tokens": entree, "output_tokens": sortie}}


vrai_post = httpx.post

# --------------------------------------------------------------------------- #
# --- EX-ARC-13 : une tentative, jamais plus -------------------------------
# La boucle interne du banc composée avec celle de la file produisait jusqu'à
# trente appels facturés là où trois sont prévus.
assert "for tentative" not in inspect.getsource(ia.generer), \
    "aucune boucle de réessai ne doit subsister dans le client (EX-ARC-13)"

for reponse, attendue in (
    (FausseReponse(429, {}, {"retry-after": "12"}), ia.ErreurDebit),
    (FausseReponse(529, {}), ia.ErreurSaturation),
    (FausseReponse(503, {}), ia.ErreurReseau),
    (FausseReponse(401, {}), ia.ErreurDefinitive),
    (httpx.ConnectTimeout("délai dépassé"), ia.ErreurReseau),
):
    appels = repondre(reponse)
    try:
        ia.generer(CONFIG, PARTICIPATION)
    except ia.ErreurGeneration as exc:
        assert isinstance(exc, attendue), f"{reponse} → {type(exc).__name__}"
    else:
        raise AssertionError(f"{reponse} aurait dû lever {attendue.__name__}")
    assert len(appels) == 1, f"{len(appels)} appels émis pour un seul attendu"

print("TOUT PASSE — une seule tentative, quelle que soit la réponse")

# --------------------------------------------------------------------------- #
# --- EX-IA-19 et EX-IA-22 : 429 et 529 ne se traitent pas pareil ----------
appels = repondre(FausseReponse(429, {}, {"retry-after": "12"}))
try:
    ia.generer(CONFIG, PARTICIPATION)
except ia.ErreurDebit as exc:
    # Le délai lu se posera dans `tache.reprendre_apres` : une attente en
    # puissances de deux l'ignorerait par construction.
    assert exc.reprendre_apres_s == 12.0, exc.reprendre_apres_s
    assert exc.temporaire and exc.categorie == "debit"

# Une date HTTP est acceptée au même titre qu'un nombre de secondes.
from email.utils import format_datetime  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
import test_outils

futur = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
appels = repondre(FausseReponse(429, {}, {"retry-after": futur}))
try:
    ia.generer(CONFIG, PARTICIPATION)
except ia.ErreurDebit as exc:
    assert 25 <= (exc.reprendre_apres_s or 0) <= 31, exc.reprendre_apres_s

# 529 : surcharge du fournisseur, indépendante du palier. Pas de `retry-after`,
# et surtout une catégorie distincte — seul un 429 justifie d'espacer les
# validations ou de monter de palier.
appels = repondre(FausseReponse(529, {}))
try:
    ia.generer(CONFIG, PARTICIPATION)
except ia.ErreurSaturation as exc:
    assert exc.categorie == "saturation" and exc.temporaire

# Un 401 ne se réessaie pas : le worker ne doit pas user trois tentatives
# contre un mur.
appels = repondre(FausseReponse(401, {}))
try:
    ia.generer(CONFIG, PARTICIPATION)
except ia.ErreurDefinitive as exc:
    assert not exc.temporaire

# Clé absente : définitif aussi, et sans appel émis.
sans_cle = os.environ.pop("ANTHROPIC_API_KEY")
appels = repondre(FausseReponse(200, charge_utile(PORTRAIT_VALIDE)))
try:
    ia.generer(CONFIG, PARTICIPATION)
except ia.ErreurDefinitive:
    assert not appels, "aucun appel ne doit partir sans clé"
os.environ["ANTHROPIC_API_KEY"] = sans_cle

print("TOUT PASSE — 429, 529, réseau et définitif se distinguent (EX-IA-22)")

# --------------------------------------------------------------------------- #
# --- Réponses arrivées mais inutilisables : réessayables -------------------
cas = [
    (charge_utile(PORTRAIT_VALIDE, stop="max_tokens"), "tronquée"),
    ({"content": [{"type": "text", "text": "ceci n'est pas du JSON"}],
      "usage": {}}, "JSON illisible"),
    (charge_utile({**PORTRAIT_VALIDE, "indice": ""}), "champs manquants"),
    (charge_utile({**PORTRAIT_VALIDE, "peuple": "licorne"}), "peuple hors liste"),
]
for charge, fragment in cas:
    appels = repondre(FausseReponse(200, charge))
    try:
        ia.generer(CONFIG, PARTICIPATION)
    except ia.ErreurReponse as exc:
        assert fragment in str(exc), f"{fragment} absent de « {exc} »"
        assert exc.temporaire, "le modèle varie d'un appel à l'autre"
    else:
        raise AssertionError(f"« {fragment} » aurait dû lever ErreurReponse")
    assert len(appels) == 1

print("TOUT PASSE — troncature, JSON, champs et peuple restent réessayables")

# --------------------------------------------------------------------------- #
# --- EX-IA-31 modifiée v3.15 : le doublon n'est plus rejeté ---------------
# La règle du rejet, validée sur huit chroniques, portait sur tout mot de
# quatre lettres partagé. À cent chroniques, chaque rejet gaspillerait un
# appel déjà payé en occupant un fil trente secondes.
doublon = {**PORTRAIT_VALIDE, "nom_fictif": "Borin Fendroc"}
appels = repondre(FausseReponse(200, charge_utile(doublon)))
portrait = ia.generer(CONFIG, PARTICIPATION)
assert portrait["nom_fictif"] == "Borin Fendroc", "le doublon doit être accepté"
assert len(appels) == 1, "et ne doit surtout pas relancer un appel"

# La liste reste transmise au modèle : suggestion, pas interdiction.
assert "Borin Fendroc" in appels[0]["messages"][0]["content"], \
    "la liste des noms pris reste une suggestion (EX-IA-31)"

print("TOUT PASSE — le doublon de nom est accepté, non relancé")

# --------------------------------------------------------------------------- #
# --- EX-IA-45 : ce qui a été envoyé et reçu, même en cas d'échec ----------
appels = repondre(FausseReponse(200, charge_utile(PORTRAIT_VALIDE, sortie=2800)))
portrait = ia.generer(CONFIG, PARTICIPATION)
trace = portrait["trace"]
assert "Fauconnier" in trace["invite"], "l'invite envoyée est consignée"
assert "Aldor Vaillegarde" in trace["reponse_brute"], "la réponse brute aussi"
assert trace["jetons_sortie"] == 2800 and trace["code_http"] == 200
assert trace["duree_s"] is not None
# Le contrat système n'est pas recopié : son empreinte suffit à l'identifier,
# et il pèse quatre fois l'invite.
assert CONFIG["contrat"][:80] not in trace["invite"], \
    "le contrat système ne doit pas être dupliqué dans la trace"

# Un échec porte la trace lui aussi : c'est le cheminement complet qui compte.
appels = repondre(FausseReponse(429, {}, {"retry-after": "5"}))
try:
    ia.generer(CONFIG, PARTICIPATION)
except ia.ErreurDebit as exc:
    assert "Fauconnier" in exc.trace["invite"], "l'invite d'un échec est consignée"
    assert exc.trace["code_http"] == 429

print("TOUT PASSE — invite et réponse brute consignées, échecs compris")

# --------------------------------------------------------------------------- #
# --- EX-IA-44 : la détection de doublon est dérivée -----------------------
bd.initialiser()
a = test_outils.creer_chronique("Doublon", "Premier", {"metier": "x"}, main.CODES_LIEUX)
b = test_outils.creer_chronique("Doublon", "Second", {"metier": "x"}, main.CODES_LIEUX)
c = test_outils.creer_chronique("Doublon", "Tiers", {"metier": "x"}, main.CODES_LIEUX)
for identifiant, nom in ((a, "Borin Fendroc"), (b, "Borin Ferconte"),
                         (c, "Aldor Vaillegarde")):
    bd.enregistrer_portrait(identifiant, {**PORTRAIT_VALIDE, "nom_fictif": nom,
                                          "fuites_noms": []})
doublons = bd.doublons_de_noms()
assert set(doublons) == {a, b}, doublons
assert doublons[a] == [b] and doublons[b] == [a]
assert c not in doublons, "un nom sans recoupement n'est pas signalé"

# Rien n'est stocké : renommer l'un fait disparaître le signalement.
bd.enregistrer_portrait(b, {**PORTRAIT_VALIDE, "nom_fictif": "Théoden Sombrelame",
                            "fuites_noms": []})
assert bd.doublons_de_noms() == {}, \
    "un drapeau stocké aurait menti ici (EX-IA-44)"

# Le recoupement ignore les accents et la casse, comme partout ailleurs.
bd.enregistrer_portrait(c, {**PORTRAIT_VALIDE, "nom_fictif": "THÉODEN Griveleux",
                            "fuites_noms": []})
assert set(bd.doublons_de_noms()) == {b, c}, bd.doublons_de_noms()

print("TOUT PASSE — doublons dérivés, sensibles ni à la casse ni aux accents")

httpx.post = vrai_post


# --- Le palier de débit se relève sur chaque réponse ----------------------
# Le point 8 de l'annexe C demandait de le lire sur la console : une lecture
# ponctuelle, hors de l'application, périmée le lendemain et invisible le soir
# où elle compterait. L'API le dit d'elle-même sur chaque réponse.
import debit as _debit

_ENTETES = {
    "anthropic-ratelimit-output-tokens-limit": "80000",
    "anthropic-ratelimit-output-tokens-remaining": "47200",
    "anthropic-ratelimit-output-tokens-reset": "2026-09-05T21:31:00Z",
    "anthropic-ratelimit-input-tokens-limit": "500000",
    "anthropic-ratelimit-input-tokens-remaining": "488000",
    "anthropic-ratelimit-requests-limit": "1000",
    "anthropic-ratelimit-requests-remaining": "992",
}

_debit.oublier()
assert _debit.dernier() is None, "aucun relevé ne doit être inventé au départ"

_debit.noter(_ENTETES)
_lu = _debit.dernier()
assert set(_lu["axes"]) == {"sortie", "entree", "requetes"}, _lu["axes"]
assert _lu["axes"]["sortie"] == {"limite": 80000, "reste": 47200,
                                 "reinitialise_le": "2026-09-05T21:31:00Z",
                                 "part_utilisee": 41}
# L'âge est calculé À LA LECTURE : stocké, il figerait un relevé de trois
# heures en « maintenant », et l'on croirait disposer d'un budget qui n'existe
# plus. Les compteurs se réinitialisent à la minute.
assert _lu["age_s"] == 0
assert "mesure_a" not in _lu

# Éprouvé en faisant VIEILLIR le relevé : lu dans la foulée, son âge vaut zéro
# qu'il soit calculé ou figé, et le contrôle ne pouvait pas distinguer les
# deux. Le cas de test était trop frais pour exercer ce qu'il portait.
with _debit._verrou:
    _debit._dernier["mesure_a"] -= 180
assert _debit.dernier()["age_s"] >= 180, \
    "un relevé de trois minutes se présente comme neuf : on le croirait actuel"
_debit.noter(_ENTETES)
assert _debit.dernier()["age_s"] == 0, "un relevé neuf doit repartir de zéro"

# Un axe absent est OMIS, jamais mis à zéro : zéro voudrait dire « plus de
# budget », ce qui est le contraire de « on ne sait pas ». Derrière un espace
# de travail, l'API n'envoie que la limite la plus contraignante.
_debit.oublier()
_debit.noter({"anthropic-ratelimit-output-tokens-limit": "80000",
              "anthropic-ratelimit-output-tokens-remaining": "0"})
_partiel = _debit.dernier()
assert set(_partiel["axes"]) == {"sortie"}, _partiel["axes"]
assert _partiel["axes"]["sortie"]["part_utilisee"] == 100, "zéro restant = 100 % utilisé"

# Et une réponse sans aucun en-tête n'efface pas le dernier relevé connu :
# l'effacer donnerait « aucun relevé » pour une réponse qui n'en portait pas.
assert _debit.noter({"content-type": "application/json"}) == {}
assert _debit.dernier()["axes"], "le relevé précédent a été effacé"
print("TOUT PASSE — le relevé de débit omet ce qu'il ignore et porte son âge")

# --- Le circuit complet, succès ET saturation ----------------------------
# Les en-têtes sont présents sur un 429 comme sur un succès, et c'est
# justement quand ça sature qu'on veut le chiffre. D'où le relevé AVANT
# l'aiguillage sur le code HTTP.
#
# Réutilise `FausseReponse` et `PARTICIPATION` du fichier plutôt que d'en
# refaire : mon premier jet en réécrivait, et sa charge incomplète levait un
# KeyError qui masquait ce que le bloc prétendait éprouver.
_debit.oublier()
os.environ["ANTHROPIC_API_KEY"] = "cle-de-test"
_vrai_post = httpx.post
try:
    for _code, _attendu in ((429, ia.ErreurDebit), (200, None)):
        _debit.oublier()
        httpx.post = (lambda code: lambda *a, **k: FausseReponse(
            code=code, charge=charge_utile(PORTRAIT_VALIDE), entetes=dict(_ENTETES)))(_code)
        _leve = None
        try:
            ia.generer(CONFIG, dict(PARTICIPATION))
        except Exception as exc:
            _leve = exc
        if _attendu:
            assert isinstance(_leve, _attendu), (type(_leve), _code)
            # La trace emporte le relevé : le journal garde donc le palier au
            # moment exact où il a lâché, ce qu'aucune console ne dira après
            # coup.
            assert _leve.trace.get("debit", {}).get("sortie"), _leve.trace
        assert _debit.dernier() is not None, f"aucun relevé après un {_code}"
        assert _debit.dernier()["axes"]["sortie"]["limite"] == 80000
finally:
    httpx.post = _vrai_post
    os.environ.pop("ANTHROPIC_API_KEY", None)
print("TOUT PASSE — le palier se relève sur un succès comme sur une saturation")
