# Écarts entre mariage_histoire (commit a0ec7ea) et mariage_production

Généré pour revue. Les quatre docstrings modifiés ne correspondent à
aucune édition journalisée pendant la session : à relire en particulier.

> Les prénoms réels des mariés sont **remplacés par `«mariée»` et `«marié»`**
> dans les lignes retirées ci-dessous. `EX-SEC-18` vaut pour tout fichier
> versionné, document de revue compris — `test_hygiene.py` a d'ailleurs refusé
> ce fichier tel qu'il était d'abord écrit, sur 17 occurrences.

## main.py
```diff
@@ -1,12 +1,18 @@
-"""Banc d'essai « Terre du Milieu ».
+"""« Le Livre des Convoqués » — application événementielle du 5 septembre 2026.
 
-Objectif unique : vérifier deux choses avant d'écrire le cahier des charges
-v3.0 — que les invités savent répondre seuls aux six questions, et que les
-portraits produits sont devinables par les mariés.
-
-Ce n'est pas l'application. Pas de mot de passe de table, pas de photo, pas de
-quotas, pas de file de tâches persistée. Le parcours et le prompt, en revanche,
-sont ceux de la version réelle.
+Le soir de la fête, une centaine d'invités répondent à un questionnaire depuis
+leur téléphone ; une IA transpose chacun en personnage de la Terre du Milieu.
+Le montage du recueil — carte, chapitres, épilogue — se fait après l'événement.
+Le 5 septembre, l'application collecte, rien d'autre.
+
+Le parcours invité, le questionnaire, le prompt, l'assignation des lieux et le
+plafond de trois réécritures viennent du banc d'essai, éprouvés contre l'API
+réelle les 16 et 17 août.
+
+État — étape 1 du socle. Manquent encore : mot de passe unique, import Excel,
+photo, Gardien des chroniques perdues, formulaire des mariés, phases de soirée,
+administration, réclamations, kiosque, sauvegardes, file de tâches persistée,
+SQLAlchemy. La génération part toujours dans un `threading.Thread` nu.
 """
 
 import json
@@ -23,14 +29,12 @@
 from fastapi.templating import Jinja2Templates
 
 import base_donnees as bd
+import config
 import ia
 import noms
 
 RACINE = os.path.dirname(os.path.abspath(__file__))
 MAX_GENERATIONS = 3
-MOTIFS_REPRISE = {m["cle"] for m in yaml.safe_load(
-    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.yaml"),
-         encoding="utf-8")).get("motifs_reprise", [])}
 
 # Prénoms des mariés : en variables d'environnement, jamais dans le dépôt, pour
 # que l'outil serve à un autre mariage sans toucher au code ni à la config.
@@ -57,17 +61,25 @@
     return valeur
 
 
+# EX-PRJ-12 — `questions.yaml` vit dans le dossier de projet, sur le volume, et
+# non dans le dépôt : c'est le seul moyen de corriger un libellé le 4 septembre
+# au soir sans redéployer. Une seule lecture, là où il y en avait deux.
 CONFIG = _substituer(
-    yaml.safe_load(open(os.path.join(RACINE, "questions.yaml"), encoding="utf-8"))
+    yaml.safe_load(config.projet().chemin_questions.read_text(encoding="utf-8"))
 )
 
+MOTIFS_REPRISE = {m["cle"] for m in CONFIG.get("motifs_reprise", [])}
+
 @asynccontextmanager
 async def cycle_de_vie(_: FastAPI):
+    # Une ligne par démarrage, dont l'empreinte de questions.yaml : c'est la
+    # seule chose qui aurait révélé la configuration périmée du 17 août.
+    print(config.resume_demarrage(), flush=True)
     bd.initialiser()
     yield
 
 
-app = FastAPI(title="Banc d'essai Terre du Milieu", lifespan=cycle_de_vie)
+app = FastAPI(title="Le Livre des Convoqués", lifespan=cycle_de_vie)
 app.mount("/static", StaticFiles(directory=os.path.join(RACINE, "static")), name="static")
 gabarits = Jinja2Templates(directory=os.path.join(RACINE, "templates"))
 gabarits.env.autoescape = True
@@ -295,7 +307,9 @@
 
 
 # --------------------------------------------------------------------------- #
-# Pages de test — c'est ici que le banc d'essai gagne son nom
+# Pages d'administration provisoires — reprises du banc d'essai.
+# Remplacées à l'étape 4 par l'écran de relecture (EX-ADM-19) et le tableau
+# de bord complet (EX-ADM-18).
 # --------------------------------------------------------------------------- #
 
 @app.get("/deviner", response_class=HTMLResponse)
```

## base_donnees.py
```diff
@@ -1,7 +1,12 @@
-"""Persistance SQLite du banc d'essai.
+"""Persistance SQLite — **reprise du banc d'essai, en attente de migration**.
 
-Volontairement en sqlite3 de la bibliothèque standard : c'est un banc d'essai,
-pas l'application. L'application réelle garde SQLAlchemy 2.0 + Alembic.
+Ce module utilise `sqlite3` de la bibliothèque standard, alors que la section
+4.2 du cahier des charges impose SQLAlchemy 2.0 + Alembic. C'est l'écart n° 2
+du briefing : un choix tenable pour une table, intenable pour dix.
+
+Il sera remplacé à l'étape suivante du socle par les dix entités de la
+section 5.1. La table `participation` ci-dessous n'existe que pour garder le
+parcours invité fonctionnel jusque-là.
 """
 
 import json
@@ -11,20 +16,12 @@
 import uuid
 from datetime import datetime, timezone
 
+import config
 import noms
 
-DOSSIER = "/data" if os.path.isdir("/data") else "."
-CHEMIN = os.path.join(DOSSIER, "banc-essai.db")
-
-# Le repli vers le dossier courant est commode en local et dangereux en ligne :
-# la base vit alors dans le conteneur et disparaît au redéploiement. Poser
-# EXIGER_VOLUME=1 dans Railway fait échouer le démarrage plutôt que de perdre
-# les données en silence.
-if os.environ.get("EXIGER_VOLUME") == "1" and DOSSIER != "/data":
-    raise RuntimeError(
-        "EXIGER_VOLUME=1 mais /data est absent : aucun volume persistant n'est "
-        "monté. Railway → service → Volumes → point de montage /data."
-    )
+# Le chemin et le garde-fou de volume vivent désormais dans config.py : un seul
+# endroit décide où l'application écrit (EX-PRJ-01, EX-ARC-17).
+CHEMIN = str(config.projet().chemin_base)
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS participation (
```

## test_parcours.py
```diff
@@ -1,4 +1,4 @@
-"""Tests de fumée du banc d'essai. Lancer : python test_parcours.py"""
+"""Tests de fumée du parcours invité. Lancer : python test_parcours.py"""
 import base64, os, pathlib, sys, time
 sys.path.insert(0, str(pathlib.Path(__file__).parent))
 os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
@@ -60,36 +60,36 @@
 compte = Counter(p["lieu"] for p in bd.lister())
 print("répartition :", sorted(compte.values()))
 assert max(compte.values()) - min(compte.values()) <= 1, compte
-print("TOUT PASSE")
+print("TOUT PASSE — parcours nominal")
 
 # --- Sélecteur préalable et prénoms des mariés ------------------------------
 import importlib
-os.environ["PRENOM_MARIEE"] = "«mariée»"
-os.environ["PRENOM_MARIE"] = "«marié»"
+os.environ["PRENOM_MARIEE"] = "Solène"
+os.environ["PRENOM_MARIE"] = "Gaspard"
 importlib.reload(main)
 c2 = TestClient(main.app); c2.__enter__()
 
 r = c2.post("/questionnaire", data={"prenom": "Ana", "nom": "Test"})
-assert "«mariée»" in r.text and "«marié»" in r.text, "prénoms substitués dans les libellés"
+assert "Solène" in r.text and "Gaspard" in r.text, "prénoms substitués dans les libellés"
 assert 'name="souvenir_avec"' in r.text, "champ du sélecteur préalable"
 assert 'class="choix prealable"' in r.text, "boutons du sélecteur préalable"
 
 donnees = dict(reponses); donnees.update({"prenom": "Ana", "nom": "Test",
-                                          "souvenir_avec": "«mariée»"})
+                                          "souvenir_avec": "Solène"})
 r = c2.post("/valider", data=donnees, follow_redirects=False)
 uid2 = r.headers["location"].split("/")[-1]
-assert '"souvenir_avec": "«mariée»"' in bd.lire(uid2)["reponses_json"], "réponse préalable stockée"
+assert '"souvenir_avec": "Solène"' in bd.lire(uid2)["reponses_json"], "réponse préalable stockée"
 
 # le message envoyé au modèle porte les prénoms et le sélecteur
 import json as _json, ia
 msg = ia._construire_message(main.CONFIG, {
     "lieu": "Isengard", "reponses": _json.loads(bd.lire(uid2)["reponses_json"]),
-    "noms_interdits": ["«mariée»"], "couple": main.COUPLE})
-assert "la mariée s'appelle «mariée»" in msg
-assert "DANS CE SOUVENIR (et rien d'autre) → «mariée»" in msg
+    "noms_interdits": ["Solène"], "couple": main.COUPLE})
+assert "la mariée s'appelle Solène" in msg
+assert "DANS CE SOUVENIR (et rien d'autre) → Solène" in msg
 assert "ne dit rien du lien de parenté" in msg
 assert "jamais écrire" in msg
-print("TOUT PASSE (2)")
+print("TOUT PASSE — sélecteur préalable et prénoms des mariés")
 
 # --- Bifurcation avant génération -------------------------------------------
 r = c2.post("/questionnaire", data={"prenom": "Bea", "nom": "Test"})
@@ -130,7 +130,7 @@
 assert "complémentaires" in msg and "LONGUEUR IMPOSÉE : 220 mots" in msg
 # on ne repropose pas le second étage à qui l'a déjà donné
 assert c2.get(f"/bonus/{uid4}", follow_redirects=False).status_code == 303
-print("TOUT PASSE (3)")
+print("TOUT PASSE — bifurcation avant génération")
 
 # --- Boutons de la bifurcation : libellé et action doivent concorder ---------
 r = c2.post("/questionnaire", data={"prenom": "Dan", "nom": "Test"})
@@ -162,7 +162,7 @@
 
 # troncature diagnostiquée comme telle
 assert ia.MODELE_DEFAUT == "claude-sonnet-5"
-print("TOUT PASSE (4)")
+print("TOUT PASSE — boutons de la bifurcation")
 
 # --- Cloisonnement des réponses par destination -----------------------------
 reponses_completes = {
@@ -172,7 +172,7 @@
     "objet": "Mes clubs de golf",
     "allegeance": "L'Ombre",
     "souvenir": "Mon épouse est la soeur de la mariée. Les repas en Valais.",
-    "souvenir_avec": "«mariée»",
+    "souvenir_avec": "Solène",
     "lien": "Famille de la mariée",
     "role_groupe": "Observe en silence",
     "colere": "Le travail bâclé",
@@ -200,7 +200,7 @@
     assert regle in contrat, regle
 assert "n'ouvre pas le portrait sur cette" in msg, "consigne d'ouverture transmise"
 assert "décor du portrait, pas son sujet" in msg
-print("TOUT PASSE (5)")
+print("TOUT PASSE — cloisonnement par destination")
 
 # --- Ombre : questions conditionnelles, peuples, cloisonnement --------------
 r = c2.post("/questionnaire", data={"prenom": "Fay", "nom": "Test"})
@@ -244,7 +244,7 @@
 for peuple in ("ent", "orque", "Variag de Khand", "troll", "Corsaire d'Umbar"):
     assert "→ " + peuple in contrat, peuple
 assert "jamais humiliant" in contrat
-print("TOUT PASSE (6)")
+print("TOUT PASSE — Ombre : conditionnelles et registres")
 
 # --- Un échec technique ne débite pas le quota de l'invité ------------------
 uid7 = bd.creer("Gil", "Test", {"metier": "x"}, main.LIBELLES_LIEUX)
@@ -271,7 +271,7 @@
 c2.post(f"/portrait/{uid7}/regenerer", follow_redirects=False)
 import time as _t; _t.sleep(0.4)
 assert bd.lire(uid7)["nb_tentatives"] == avant, "aucun appel au-delà du garde-fou"
-print("TOUT PASSE (7)")
+print("TOUT PASSE — un échec ne débite pas le quota")
 
 # --- Un échec de génération ne consomme aucun crédit ------------------------
 uid7 = bd.creer("Gil", "Test", {"metier": "x"}, main.LIBELLES_LIEUX)
@@ -285,20 +285,20 @@
 assert bd.lire(uid7)["nb_generations"] == 1
 # et les réponses ont survécu à tout
 assert "x" in bd.lire(uid7)["reponses_json"]
-print("TOUT PASSE (7)")
+print("TOUT PASSE — un échec ne consomme aucun crédit")
 
 # --- Le lien déclaré ne doit pas être étendu ---------------------------------
 otho = {"metier": "Dessinateur", "attachement": "Une bonne table entre amis",
         "defaut": "Je veux tout contrôler", "objet": "Mon décapsuleur",
         "allegeance": "La Lumière", "souvenir_avec": "Les deux",
-        "souvenir": "un test", "lien": "Famille de «mariée»"}
+        "souvenir": "un test", "lien": "Famille de Solène"}
 msg = ia._construire_message(main.CONFIG, {
     "lieu": "Les Havres Gris", "reponses": otho,
     "noms_interdits": [], "couple": main.COUPLE})
 assert "ne dit rien du lien de parenté" in msg, "le sélecteur est désambiguïsé"
-assert "Famille de «mariée»" in msg
+assert "Famille de Solène" in msg
 assert "N'étends jamais un lien" in main.CONFIG["contrat"]
-print("TOUT PASSE (7)")
+print("TOUT PASSE — le lien déclaré n'est pas étendu")
 
 # --- Locution, pendant d'ombre, unicité des noms fictifs --------------------
 lieu_mt = next(l for l in main.CONFIG["lieux"] if l["libelle"] == "Minas Tirith")
@@ -330,7 +330,7 @@
     "lieu": comte, "reponses": base, "noms_interdits": [],
     "noms_fictifs_pris": pris, "couple": main.COUPLE})
 assert "NOMS FICTIFS DÉJÀ ATTRIBUÉS" in msg and "Skarn Rouille" in msg
-print("TOUT PASSE (8)")
+print("TOUT PASSE — locution, pendant d'ombre, noms fictifs uniques")
 
 # --- Longueur adaptée au volume de réponses --------------------------------
 court = ia._construire_message(main.CONFIG, {
@@ -351,7 +351,7 @@
 assert ia.MODELE_DEFAUT == "claude-sonnet-5"
 import inspect
 assert '"max_tokens": 8000' in inspect.getsource(ia.generer)
-print("TOUT PASSE (9)")
+print("TOUT PASSE — longueur adaptée au volume")
 
 # --- Le vœu est au premier étage, et n'atteint jamais le modèle -------------
 assert [q["cle"] for q in main.CONFIG["obligatoires"]][-1] == "souhait", \
@@ -360,7 +360,7 @@
 assert main.NB_BONUS == 5 and main.NB_BONUS_MOT == "cinq"
 
 r = c2.post("/questionnaire", data={"prenom": "Hal", "nom": "Test"})
-assert "Que souhaites-tu à «mariée» et «marié»" in r.text.replace("&#39;", "'")
+assert "Que souhaites-tu à Solène et Gaspard" in r.text.replace("&#39;", "'")
 assert "cinq questions de plus" in r.text.lower()
 
 avec_voeu = dict(donnees)
@@ -372,7 +372,7 @@
 msg = ia._construire_message(main.CONFIG, {
     "lieu": comte, "reponses": _json.loads(stocke), "noms_interdits": [], "couple": main.COUPLE})
 assert "Tout le bonheur du monde" not in msg, "et n'atteint toujours pas le modèle"
-print("TOUT PASSE (10)")
+print("TOUT PASSE — le vœu n'atteint jamais le modèle")
 
 # --- Le contrôle de noms ne retient que les occurrences capitalisées --------
 # Cas réel du 18 août : « le nouveau-né tout juste arrivé au monde » signalait
@@ -383,8 +383,8 @@
 assert ia.verifier_noms("elle salua Pierre et repartit", ["Pierre"]) == ["Pierre"]
 assert ia.verifier_noms("Juste avant l'aube, il partit", ["Juste"]) == [], "début de phrase"
 assert ia.verifier_noms("il vit Jean-Pierre au loin", ["Jean-Pierre"]) == ["Jean-Pierre"]
-assert ia.verifier_noms("la scène avec «mariée» à ses côtés", ["«mariée»"]) == ["«mariée»"]
-print("TOUT PASSE (11)")
+assert ia.verifier_noms("la scène avec Solène à ses côtés", ["Solène"]) == ["Solène"]
+print("TOUT PASSE — fuites de noms : occurrences capitalisées")
 
 # --- Capitalisation des noms saisis et initiales ----------------------------
 import noms as mod_noms
@@ -408,7 +408,7 @@
 ligne = bd.lire(uid10)
 assert ligne["prenom"] == "Jean-Pierre" and ligne["nom"] == "Gagnebin"
 assert "Jean-Pierre" in bd.tous_les_prenoms() and "Gagnebin" in bd.tous_les_prenoms()
-print("TOUT PASSE (12)")
+print("TOUT PASSE — capitalisation et initiales")
 
 # --- Genre du personnage ----------------------------------------------------
 # Cas réel du 18 août : « Jean-Pascal » a produit un personnage féminin.
@@ -434,7 +434,7 @@
     "couple": main.COUPLE, "genre": None})
 assert "GENRE DU PERSONNAGE" not in msg
 assert "Un prénom réel ne" in main.CONFIG["contrat"]
-print("TOUT PASSE (13)")
+print("TOUT PASSE — genre du personnage")
 
 # --- Motifs de reprise : liste fermée, jamais de texte libre ----------------
 motifs = {m["cle"] for m in main.CONFIG["motifs_reprise"]}
@@ -457,4 +457,4 @@
 
 # la règle sur la deuxième personne est bien dans le contrat
 assert "« tu », « toi », « ta » et « vous » désignent TOUJOURS" in main.CONFIG["contrat"]
-print("TOUT PASSE (14)")
+print("TOUT PASSE — motifs de reprise : liste fermée")
```

## test_affichage.py
```diff
@@ -1,4 +1,4 @@
-"""Tests de fumée du banc d'essai. Lancer : python test_parcours.py"""
+"""Tests de fumée du rendu des chroniques. Lancer : python test_affichage.py"""
 import base64, os, pathlib, sys, time
 sys.path.insert(0, str(pathlib.Path(__file__).parent))
 os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
@@ -43,7 +43,7 @@
 assert ia.verifier_noms("Elwen la guérisseuse", ["Marie"]) == []
 assert ia.verifier_noms("il vit Jean-Pierre", ["Jean-Pierre"]) == ["Jean-Pierre"]
 assert ia.verifier_noms("il vit Pierre", ["Jean-Pierre"]) == ["Jean-Pierre"]
-print("TOUT PASSE")
+print("TOUT PASSE — affichage du portrait et échappement")
 
 # --- Révélation : souvenir et vœu montrés tels quels -------------------------
 uid2 = bd.creer("Jo", "Test", {"souvenir": "on a raté le dernier train",
@@ -55,7 +55,7 @@
 assert "on a raté le dernier train" in r.text, "souvenir brut à la révélation"
 assert "plein de belles choses" in r.text, "vœu brut à la révélation"
 assert "Ce qu'il ou elle vous souhaite" in r.text
-print("TOUT PASSE (bis)")
+print("TOUT PASSE — révélation : souvenir et vœu tels quels")
 
 # --- Initiales affichées au palier d'indice ---------------------------------
 uid3 = bd.creer("jean-pierre", "gagnebin", {"souvenir": "s"}, main.LIBELLES_LIEUX)
@@ -64,7 +64,7 @@
 r = c.get("/deviner", headers=auth)
 assert "J.-P. G." in r.text, "initiales d'un prénom composé"
 assert "Jean-Pierre Gagnebin" in r.text, "nom capitalisé à la révélation"
-print("TOUT PASSE (ter)")
+print("TOUT PASSE — initiales au palier d'indice")
 
 # --- Le tableau apparie région et pendant d'ombre ---------------------------
 uid4 = bd.creer("Mons", "Tre", {"metier": "x", "allegeance": "L'Ombre",
@@ -89,4 +89,4 @@
 # la répartition compte la région, pas le pendant
 lignes = [l for l in bd.lister() if l["lieu"] == "Minas Tirith"]
 assert len(lignes) >= 2, "les deux comptent pour Minas Tirith"
-print("TOUT PASSE (quater)")
+print("TOUT PASSE — appariement région / pendant d'ombre")
```

## requirements.txt
```diff
@@ -4,3 +4,9 @@
 python-multipart==0.0.20
 httpx==0.28.1
 pyyaml==6.0.2
+
+# EX-GEN-04 — affichage en heure locale (Europe/Zurich). Windows n'a pas de
+# base de fuseaux système, et les images Debian « slim » n'en embarquent pas :
+# sans ce paquet, ZoneInfo lève ZoneInfoNotFoundError. Vérifié au démarrage
+# par config.zone_affichage().
+tzdata==2025.1
```

## README.md
Réécrit intégralement pour le dépôt de production.

## Fichiers identiques au banc, non modifiés

- `ia.py`
- `noms.py`
- `questions.yaml`
- `Dockerfile`
- `static/style.css`
- `templates/accueil.html`
- `templates/base.html`
- `templates/bonus_intro.html`
- `templates/deviner.html`
- `templates/fin.html`
- `templates/fragment_portrait.html`
- `templates/portrait.html`
- `templates/questionnaire.html`
- `templates/tableau.html`

## Fichiers nouveaux

- `config.py`
- `test_config.py`
- `test_hygiene.py`
- `CONVENTIONS.md`
- `.gitignore`
- `.dockerignore`
- `.env.example`
- `exemples/config.yaml`
