"""Tests de fumée de la porte. Lancer : python test_acces.py"""
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")
import base64
from fastapi.testclient import TestClient
import acces, config, main

AUTH = {"Authorization": "Basic " + base64.b64encode(b"a:secret").decode()}
MOT = acces.MOT_DE_PASSE_DEVELOPPEMENT

ctx = TestClient(main.app, follow_redirects=False); ctx.__enter__(); c = ctx

# --- Sans mot de passe, aucune route invité ne répond -----------------------
# La référence est prise AVANT toute saisie : un client qui aurait déjà franchi
# la porte photographierait l'état d'après et ne pourrait plus rien détecter.
for chemin in ("/", "/portrait/nimporte", "/bonus/nimporte", "/fin"):
    r = c.get(chemin)
    assert r.status_code == 303, f"{chemin} a répondu {r.status_code}"
    assert r.headers["location"].startswith("/entrer?vers="), r.headers["location"]

# Le POST aussi : masquer un formulaire n'est pas une protection (EX-SEC-04).
r = c.post("/valider", data={"prenom": "Sans", "nom": "Cle", "metier": "x"})
assert r.status_code == 303 and "/entrer" in r.headers["location"]

# La porte elle-même et les fichiers statiques restent joignables.
assert c.get("/entrer").status_code == 200
assert c.get("/static/style.css").status_code == 200
assert c.get("/static/htmx.min.js").status_code == 200
print("TOUT PASSE — sans mot de passe, tout le parcours invité est fermé")

# --- Un mauvais mot de passe ne pose aucun cookie ---------------------------
r = c.post("/entrer", data={"mot_de_passe": "pas-le-bon", "vers": "/"})
assert r.status_code == 401, r.status_code
assert acces.NOM_COOKIE not in r.cookies
assert "carton" in r.text, "EX-AUTH-11 : le message doit dire quoi faire"
assert c.get("/").status_code == 303, "la porte doit rester fermée"
print("TOUT PASSE — un mot de passe faux ne pose pas de cookie")

# --- Le bon mot de passe ouvre, casse et espaces compris (EX-AUTH-07) -------
for saisie in (MOT, MOT.upper(), f"  {MOT}  ", MOT.capitalize()):
    frais = TestClient(main.app, follow_redirects=False)
    r = frais.post("/entrer", data={"mot_de_passe": saisie, "vers": "/"})
    assert r.status_code == 303, f"« {saisie} » refusé"
    assert frais.get("/").status_code == 200, f"« {saisie} » n'a pas ouvert"
print("TOUT PASSE — insensible à la casse et aux espaces superflus")

# --- Le cookie porte les trois attributs d'EX-SEC-07 ------------------------
frais = TestClient(main.app, follow_redirects=False)
r = frais.post("/entrer", data={"mot_de_passe": MOT, "vers": "/"})
brut = r.headers["set-cookie"]
assert "HttpOnly" in brut, brut
assert "SameSite=lax" in brut.replace("SameSite=Lax", "SameSite=lax"), brut
# `Secure` est conditionné à HTTPS : posé en clair, le navigateur ne le
# renverrait jamais en local et la porte se refermerait en boucle.
assert "Secure" not in brut, "en HTTP local, Secure fermerait la porte en boucle"
r = frais.post("/entrer", data={"mot_de_passe": MOT, "vers": "/"},
               headers={"x-forwarded-proto": "https"})
assert "Secure" in r.headers["set-cookie"], r.headers["set-cookie"]
print("TOUT PASSE — cookie HttpOnly, SameSite=Lax, Secure dès que HTTPS")

# --- La destination est conservée, mais jamais vers l'extérieur ------------
r = c.get("/portrait/abc123")
assert "vers=%2Fportrait%2Fabc123" in r.headers["location"], r.headers["location"]
# Chaque forme est arrêtée par un contrôle DIFFÉRENT. Les trois premières le
# sont par l'absence d'hôte ; `/\\ailleurs.example` passait ce contrôle et se
# faisait normaliser en `//ailleurs.example` par le navigateur.
for hostile in ("https://ailleurs.example", "//ailleurs.example", "http://x",
                "/\\ailleurs.example", "javascript:alert(1)",
                "ailleurs.example/page"):
    r = c.post("/entrer", data={"mot_de_passe": MOT, "vers": hostile})
    assert r.headers["location"] == "/", f"tremplin ouvert vers {hostile}"
print("TOUT PASSE — la destination est conservée, jamais hors du site")

# --- Changer le mot de passe referme les cookies déjà posés ----------------
ouvert = TestClient(main.app, follow_redirects=False)
ouvert.post("/entrer", data={"mot_de_passe": MOT, "vers": "/"})
assert ouvert.get("/").status_code == 200
_vrai_mot = acces.mot_de_passe
acces.mot_de_passe = lambda: "un-autre-mot"
try:
    assert ouvert.get("/").status_code == 303, \
        "le cookie doit tomber avec l'ancien mot de passe"
finally:
    acces.mot_de_passe = _vrai_mot
assert ouvert.get("/").status_code == 200, "et revivre quand il revient"
print("TOUT PASSE — changer le mot de passe referme les cookies posés")

# --- Les en-têtes de sécurité sont sur toutes les réponses (EX-SEC-08) -----
for chemin, client in (("/entrer", c), ("/", frais)):
    e = client.get(chemin).headers
    assert e["X-Content-Type-Options"] == "nosniff", chemin
    assert e["Referrer-Policy"] == "same-origin", chemin
    csp = e["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp, chemin
    assert "base-uri 'none'" in csp, chemin
    # Le questionnaire porte son comportement en <script> inline : une CSP qui
    # l'interdirait rendrait tous les boutons inertes, sans message d'erreur.
    # L'assertion porte sur la DIRECTIVE et non sur la chaîne entière : retirer
    # `unsafe-inline` de script-src le laissait dans style-src, et le contrôle
    # passait quand même.
    directives = {d.strip().split(" ")[0]: d.strip()
                  for d in csp.split(";") if d.strip()}
    assert "'unsafe-inline'" in directives["script-src"], directives["script-src"]
    # htmx est servi depuis /static : aucun script tiers n'est autorisé.
    assert "unpkg" not in csp and "cdn" not in csp, chemin
print("TOUT PASSE — en-têtes de sécurité présents, CSP compatible avec l'existant")

# --- Le démarrage refuse un mot de passe absent ou d'exemple ---------------
# Éprouvé sur la fonction et non par un vrai démarrage : monter un volume
# factice au milieu d'un test qui a déjà ouvert la base ferait dériver l'état.
_vrai_projet = config.projet


def _projet_avec(valeur):
    reel = _vrai_projet()
    class Faux:
        identifiant = "2026-09-05-essai"
        chemin_configuration = pathlib.Path("/data/projets/essai/config.yaml")
    Faux.chemin_questions = reel.chemin_questions
    return Faux()


for valeur, attendu in ((None, "absent"), ("", "vide"),
                        (acces.MOT_DE_PASSE_EXEMPLE, "valeur d'exemple"),
                        ("A-Definir ", "valeur d'exemple mal recopiée")):
    config.projet = lambda v=valeur: _projet_avec(v)
    _vrai_parametre = config.parametre
    config.parametre = lambda chemin, defaut=None, v=valeur: (
        v if chemin == "acces.mot_de_passe" else defaut)
    try:
        leve = False
        try:
            acces.verifier_au_demarrage()
        except config.ErreurConfiguration:
            leve = True
        assert leve, f"le démarrage a accepté un mot de passe {attendu}"
    finally:
        config.parametre = _vrai_parametre
        config.projet = _vrai_projet

# Et il accepte un vrai mot de passe.
config.projet = lambda: _projet_avec("le-conseil")
_vrai_parametre = config.parametre
config.parametre = lambda chemin, defaut=None: (
    "le-conseil" if chemin == "acces.mot_de_passe" else defaut)
try:
    acces.verifier_au_demarrage()
finally:
    config.parametre = _vrai_parametre
    config.projet = _vrai_projet
print("TOUT PASSE — le démarrage refuse un mot de passe absent, vide ou d'exemple")

# --- Le modèle vient de config.yaml, plus de l'environnement ---------------
import ia
assert "MODELE_IA" not in pathlib.Path("ia.py").read_text(encoding="utf-8"), \
    "ia.py ne doit plus lire le modèle dans l'environnement (écart n° 3)"
assert "MODELE_IA" not in pathlib.Path(".env.example").read_text(encoding="utf-8")
os.environ["MODELE_IA"] = "modele-fantome"
try:
    trace = {}
    try:
        ia.generer({"contrat": "x", "peuples": [], "lieux": [], "mots_max": {}},
                   {"lieu": {"libelle": "L", "code": "lieu_01"}, "reponses": {},
                    "noms_interdits": [], "modele": "modele-attendu"})
    except ia.ErreurGeneration as exc:
        trace = exc.trace or {}
    # Sans clé d'API l'appel échoue avant l'envoi ; ce qui compte est que la
    # valeur retenue soit celle passée par l'appelant, jamais celle de l'env.
    assert trace.get("modele") != "modele-fantome", trace
finally:
    os.environ.pop("MODELE_IA", None)
print("TOUT PASSE — le modèle est un paramètre reçu, jamais lu dans l'environnement")

ctx.__exit__(None, None, None)
