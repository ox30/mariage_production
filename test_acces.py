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

# --- Une configuration refusée laisse le service DEBOUT, sans rien servir ---
# Le 25 août, le refus de démarrer a rendu le volume inatteignable — donc le
# fichier fautif incorrigible. Ce qu'on éprouve ici : le service répond, il dit
# quoi corriger, et il n'a RIEN fait d'autre.
import panne, taches

_vrai_controle = acces.verifier_au_demarrage
_vrai_demarrer = taches.demarrer
_demarrages = []
taches.demarrer = lambda *a, **k: _demarrages.append(1) or 0


def _refuser():
    raise config.ErreurConfiguration(
        "`acces.mot_de_passe` est absent du config.yaml du projet "
        "« 2026-09-05-court-mariage ». L'ajouter dans "
        "/data/projets/2026-09-05-court-mariage/config.yaml.")


acces.verifier_au_demarrage = _refuser
try:
    en_panne = TestClient(main.app, follow_redirects=False)
    en_panne.__enter__()
    try:
        assert main.PANNE is not None, "le drapeau de panne n'a pas été posé"
        # Toutes les routes, la porte comprise : un écran de mot de passe qui
        # n'ouvre sur rien ferait croire à un mot de passe erroné.
        for chemin in ("/", "/entrer", "/portrait/abc", "/bonus/x", "/fin"):
            r = en_panne.get(chemin)
            assert r.status_code == 503, f"{chemin} a répondu {r.status_code}"
            assert "config.yaml" in r.text, chemin
            assert "2026-09-05-court-mariage" in r.text, chemin
        r = en_panne.post("/valider", data={"prenom": "X", "nom": "Y"})
        assert r.status_code == 503, r.status_code
        # Et surtout : rien n'a démarré. Une migration appliquée à une base
        # dont on ne sait plus si elle est au bon endroit serait pire que
        # l'arrêt.
        assert not _demarrages, "le worker a démarré alors que la config est refusée"
    finally:
        en_panne.__exit__(None, None, None)
finally:
    acces.verifier_au_demarrage = _vrai_controle
    taches.demarrer = _vrai_demarrer
    main.PANNE = None

# La page de panne ne dépend d'aucun gabarit ni d'aucune configuration : c'est
# la seule façon qu'elle a de s'afficher quand la configuration est en cause.
# Contrôlé sur les IMPORTS et non par recherche de chaîne : le premier jet
# cherchait « empreinte » dans le fichier entier et tombait sur le mot écrit
# dans un commentaire. Un test qui échoue sur un commentaire n'éprouve pas la
# dépendance, il éprouve la prose.
import ast
_arbre = ast.parse(pathlib.Path("panne.py").read_text(encoding="utf-8"))
_importes = set()
for noeud in ast.walk(_arbre):
    if isinstance(noeud, ast.Import):
        _importes |= {a.name.split(".")[0] for a in noeud.names}
    elif isinstance(noeud, ast.ImportFrom) and noeud.module:
        _importes.add(noeud.module.split(".")[0])
_du_projet = {"config", "main", "base_donnees", "modeles", "ia", "noms",
              "taches", "instantane", "depot_objet", "acces"}
assert not (_importes & _du_projet), \
    f"panne.py dépend de {_importes & _du_projet} — donc de ce qui est en panne"
assert "&lt;script&gt;" in panne.page("<script>alert(1)</script>"), "message non échappé"

# Le point d'entrée d'uvicorn passe par serveur.py, qui attrape le second
# moment où une ErreurConfiguration peut sortir : l'import de `main`.
# Sur la LIGNE CMD et non dans le fichier entier : le commentaire qui explique
# le choix contient lui aussi « serveur:app », et l'assertion passait donc même
# après être revenue à `main:app`. Deuxième occurrence de la même faute dans
# cette session, après le contrôle des dépendances de panne.py.
_cmd = [l for l in pathlib.Path("Dockerfile").read_text(encoding="utf-8").splitlines()
        if l.lstrip().startswith("CMD")]
assert len(_cmd) == 1, f"{len(_cmd)} lignes CMD dans le Dockerfile"
assert "serveur:app" in _cmd[0], \
    f"le Dockerfile doit lancer serveur:app, sinon les erreurs d'import tuent : {_cmd[0]}"
assert "main:app" not in _cmd[0], _cmd[0]
assert "from main import app" in pathlib.Path("serveur.py").read_text(encoding="utf-8")
print("TOUT PASSE — une configuration refusée laisse le service debout et réparable")

# --- Une configuration refusée s'écrit en clair, sans trace ----------------
# Constaté sur Railway le 25 août : le message utile sortait sous douze lignes
# de trace, onze fois de suite. Ce qu'on éprouve ici, c'est que le texte de
# l'exception se retrouve INTÉGRALEMENT dans le bloc — un repliage qui perdrait
# un mot ferait disparaître le chemin du fichier à corriger.
# Le message RÉEL de l'incident du 25 août, et non un raccourci : trop court,
# il ne produisait que trois lignes et n'exerçait donc jamais le repliage —
# l'assertion existait, le cas de test ne l'atteignait pas.
message = ("`acces.mot_de_passe` vaut encore « a-definir », la valeur de "
           "exemples/config.yaml. Un fichier recopié depuis l'exemple et "
           "jamais relu a déjà envoyé les sauvegardes sous un préfixe "
           "orphelin le 25 août (EX-PRJ-13) ; ici il ouvrirait la soirée avec "
           "un mot de passe public. En poser un vrai dans "
           "/data/projets/2026-08-19-repetition/config.yaml.")
bloc = config.bloc_erreur(config.ErreurConfiguration(message))
assert "CONFIGURATION REFUSÉE" in bloc
# Le libellé doit dire l'état RÉEL : depuis le mode panne, le service démarre.
# « ne démarrera pas » enverrait chercher un crash qui n'a pas lieu.
assert "ne démarrera pas" not in bloc, "libellé périmé depuis le mode panne"
assert "ne sert rien" in bloc
for mot in message.split():
    assert mot in bloc, f"« {mot} » perdu au repliage"
largeurs = {len(l) for l in bloc.splitlines() if l.startswith(("┌", "│", "├", "└"))}
assert len(largeurs) == 1, f"cadre irrégulier : {sorted(largeurs)}"
# Multiligne : les messages de config.py en portent, et un repliage naïf
# collerait deux paragraphes l'un à l'autre.
assert config.bloc_erreur(config.ErreurConfiguration("un\n\ndeux")).count("\n") >= 7
# Un mot plus long que le cadre — chemin, URL — est coupé et non laissé
# déborder : sinon la bordure se décale au milieu du message.
long_ = config.bloc_erreur(config.ErreurConfiguration("chemin " + "x" * 200))
assert len({len(l) for l in long_.splitlines() if l.startswith(("┌", "│", "├", "└"))}) == 1
print("TOUT PASSE — une configuration refusée s'écrit en clair, sans trace")

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
