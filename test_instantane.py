"""Instantanés et dépôts objets. Lancer : python test_instantane.py

Couvre EX-SAU-13 (instantané toutes les 3 minutes), EX-SAU-14 (aucune purge),
EX-SAU-15 (horodatage par destination), EX-SAU-17 (autocommit), EX-SAU-18
(hors file), EX-SAU-19 (préfixe de projet), EX-SAU-20 (écritures
indépendantes) et EX-SAU-21 (sonde au démarrage).

Aucun appel réseau : les dépôts distants sont remplacés par des dépôts locaux
et par un dépôt qui échoue à volonté. Ce qui est éprouvé, c'est la **décision**
prise face à une destination muette, pas la disponibilité de Cloudflare.
"""
import os
import pathlib
import sqlite3
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
os.environ["WORKER_ACTIF"] = "0"
os.environ["INSTANTANE_ACTIF"] = "0"

import sqlalchemy as sa

import base_donnees as bd
import config
import depot_objet
import instantane
import main
import test_outils
from modeles import Sauvegarde

bd.initialiser()
for i in range(25):
    test_outils.creer_chronique(f"Instant{i}", "Essai", {"metier": "x" * 400}, main.CODES_LIEUX)


class DepotMuet(depot_objet.DepotObjet):
    """Un dépôt dont la clé est fausse : il accepte, mais ne rend rien.

    C'est le défaut que doubler les destinations rend deux fois plus probable,
    et que seule une relecture révèle (EX-SAU-21).
    """

    def __init__(self, nom="muet", lent=0.0, ecriture_ko=False):
        self.nom = nom
        self.lent = lent
        self.ecriture_ko = ecriture_ko
        self.recus = []

    def deposer(self, cle, contenu):
        time.sleep(self.lent)
        if self.ecriture_ko:
            raise ConnectionError("endpoint injoignable")
        self.recus.append(cle)
        return len(contenu)

    def lire(self, cle):
        raise KeyError("objet introuvable")

    def supprimer(self, cle):
        pass


# --------------------------------------------------------------------------- #
# --- EX-SAU-17 : l'autocommit, sans quoi rien ne marche -------------------
# Le pilote sqlite3 ouvre une transaction implicite ; sans AUTOCOMMIT,
# « cannot VACUUM from within a transaction ».
seance = bd.Seance()
seance.execute(sa.text(
    "INSERT INTO personne (uuid, prenom, nom, est_responsable, est_marie, "
    "est_test, source, active) VALUES ('fantome','Fantome','X',0,0,0,"
    "'saisie_libre',1)"))

debut = time.monotonic()
chemin = instantane.produire()
duree = time.monotonic() - debut
seance.rollback()
seance.close()

assert chemin.is_file() and chemin.stat().st_size > 0
assert duree < 2.0, f"{duree:.1f} s — l'instantané doit rester bref"

copie = sqlite3.connect(chemin)
assert copie.execute("select count(*) from personne").fetchone()[0] == 25
assert copie.execute(
    "select count(*) from personne where uuid='fantome'").fetchone()[0] == 0, \
    "une transaction non validée ne doit pas figurer dans l'instantané"
assert len(copie.execute(
    "select name from sqlite_master where type='table'").fetchall()) >= 11
copie.close()

# Pourquoi l'autocommit est indispensable, démontré plutôt qu'affirmé.
# Le pilote sqlite3 n'ouvre une transaction que sur une ÉCRITURE, jamais pour
# un VACUUM : une connexion neuve passerait donc même sans autocommit, et un
# test qui n'éprouve que ce cas-là ne prouve rien. C'est une connexion ayant
# déjà écrit qui révèle le défaut — exactement la situation d'un service en
# activité, où le moteur recycle ses connexions.
import sqlalchemy.exc as _exc  # noqa: E402

essai = pathlib.Path(config.projet().dossier) / "essai-autocommit.db"
essai.unlink(missing_ok=True)
try:
    with bd.moteur.connect() as cx:
        cx.exec_driver_sql("INSERT INTO journal (uuid, action, horodatage) "
                           "VALUES ('sonde-vacuum','essai','2026-01-01 00:00:00')")
        cx.exec_driver_sql("VACUUM INTO ?", (str(essai),))
except _exc.OperationalError as exc:
    assert "cannot VACUUM from within a transaction" in str(exc), exc
else:
    raise AssertionError("le défaut d'EX-SAU-17 ne se reproduit plus : "
                         "vérifier que le contrôle a encore un sens")

# En autocommit, la même séquence passe.
essai.unlink(missing_ok=True)
autocommit = bd.moteur.execution_options(isolation_level="AUTOCOMMIT")
with autocommit.connect() as cx:
    cx.exec_driver_sql("INSERT INTO journal (uuid, action, horodatage) "
                       "VALUES ('sonde-vacuum-2','essai','2026-01-01 00:00:00')")
    cx.exec_driver_sql("VACUUM INTO ?", (str(essai),))
assert essai.is_file()
essai.unlink(missing_ok=True)

# Et `produire()` emploie bien cette option, non la connexion ordinaire.
import inspect  # noqa: E402
assert 'isolation_level="AUTOCOMMIT"' in inspect.getsource(instantane.produire), \
    "produire() doit passer par une connexion en autocommit (EX-SAU-17)"

print(f"TOUT PASSE — instantané cohérent en {duree*1000:.0f} ms, "
      f"transaction ouverte exclue, autocommit démontré")

# --------------------------------------------------------------------------- #
# --- EX-SAU-19 : un bucket par fournisseur, préfixé par projet ------------
prefixe = depot_objet.prefixe_projet()
assert prefixe.endswith(config.projet().identifiant), prefixe
assert depot_objet.cle("instantanes", "app.db") == f"{prefixe}/instantanes/app.db"
# Le préfixe ne se tape jamais à la main : il vient de projet-actif.txt.
assert config.projet().identifiant in depot_objet.cle("x")

# --- EX-SAU-20 : les écritures sont indépendantes -------------------------
# Séquentiellement, un dépôt lent ferait passer la boucle de trois minutes à
# six sans que rien ne le dise.
racine = pathlib.Path(config.projet().dossier) / "essai-depots"
bon = depot_objet.DepotLocal(racine / "bon", "bon")
lent = DepotMuet("lent", lent=0.5)
lent2 = DepotMuet("lent2", lent=0.5)
casse = DepotMuet("casse", ecriture_ko=True)

debut = time.monotonic()
resultats = depot_objet.deposer_partout("instantanes/x.db", b"contenu",
                                        [bon, lent, lent2, casse])
ecoule = time.monotonic() - debut
# Deux dépôts à 0,5 s : en parallèle 0,5 s, en séquentiel 1,0 s. Le seuil doit
# séparer les deux, sans quoi le contrôle passerait dans les deux cas.
assert ecoule < 0.8, f"{ecoule:.2f} s — les écritures doivent être parallèles"

par_nom = {r.destination: r for r in resultats}
assert par_nom["bon"].succes and par_nom["lent"].succes and par_nom["lent2"].succes
assert not par_nom["casse"].succes, "l'échec doit être rapporté"
assert "ConnectionError" in par_nom["casse"].erreur
assert par_nom["bon"].octets == 7
# Et surtout : l'échec de l'un n'a pas empêché l'autre.
assert (racine / "bon" / depot_objet.cle("instantanes/x.db")).is_file()

print(f"TOUT PASSE — écritures parallèles en {ecoule:.2f} s, un échec n'en bloque aucune")

# --------------------------------------------------------------------------- #
# --- EX-SAU-21 : la sonde relit, elle ne se contente pas d'écrire ---------
# Une clé en écriture seule, un bucket mal nommé ou une région erronée
# laissent un `put` réussir en apparence.
sondes = {r.destination: r for r in depot_objet.sonder([bon, lent, casse])}
assert sondes["bon"].succes, "un dépôt sain doit passer"
assert not sondes["lent"].succes, \
    "écrire ne suffit pas : la relecture est le seul contrôle qui prouve"
assert "KeyError" in sondes["lent"].erreur
assert not sondes["casse"].succes

# La sonde ne laisse rien traîner sur un dépôt sain.
restes = list((racine / "bon").rglob("sonde-*"))
assert not restes, f"sondes non nettoyées : {restes}"

print("TOUT PASSE — la sonde écrit ET relit, et ne laisse rien derrière elle")

# --------------------------------------------------------------------------- #
# --- EX-SAU-22 : identifiants dans l'environnement, destinations en config -
for cle_env in ("STOCKAGE_R2_ENDPOINT", "STOCKAGE_R2_CLE",
                "STOCKAGE_R2_SECRET", "STOCKAGE_R2_BUCKET"):
    os.environ.pop(cle_env, None)
assert depot_objet._depuis_environnement("r2") is None, \
    "sans les quatre variables, pas de dépôt — et pas d'erreur au démarrage"

os.environ.update({
    "STOCKAGE_R2_ENDPOINT": "https://compte.r2.cloudflarestorage.com",
    "STOCKAGE_R2_CLE": "cle-fictive",
    "STOCKAGE_R2_SECRET": "secret-fictif",
    "STOCKAGE_R2_BUCKET": "mariage",
})
depot = depot_objet._depuis_environnement("r2")
assert depot is not None and depot.nom == "r2"
# R2 exige region_name="auto" : une région AWS ordinaire y produit une erreur
# de signature difficile à lire.
assert depot._region == "auto"
# Construire un dépôt n'ouvre aucune connexion : sinon la seule lecture de la
# configuration ferait tomber le démarrage si un fournisseur est injoignable.
assert depot._client is None

# Le résumé de démarrage nomme les destinations sans identifiants plutôt que
# de les taire.
os.environ.pop("STOCKAGE_R2_CLE")
resume = depot_objet.resume_sonde()
assert "r2 SANS IDENTIFIANTS" in resume, resume
assert "STOCKAGE_R2_ENDPOINT" in resume, "le message doit nommer les variables"
os.environ["STOCKAGE_R2_CLE"] = "cle-fictive"

print("TOUT PASSE — identifiants hors config.yaml, destination muette annoncée")

# --------------------------------------------------------------------------- #
# --- EX-SAU-15 : un horodatage par destination, jamais un seul ------------
with bd.Seance() as s:
    s.execute(sa.delete(Sauvegarde))
    s.commit()

instantane.depot_objet.deposer_partout  # noqa: B018 — lisibilité du lien
_vrais_depots = depot_objet.depots_actifs
depot_objet.depots_actifs = lambda: [bon, casse]
resultats = instantane.un_passage()
depot_objet.depots_actifs = _vrais_depots

etat = instantane.dernier_par_destination()
assert etat["bon"]["reussite"] is not None
assert etat["casse"]["reussite"] is None and etat["casse"]["echec"] is not None
assert "ConnectionError" in etat["casse"]["echec"]["erreur"]
# Un chiffre unique aurait laissé croire à une sauvegarde de deux minutes
# alors qu'une moitié n'a plus rien reçu.
assert set(etat) == {"bon", "casse"}, etat

print("TOUT PASSE — l'état est rapporté destination par destination")

# --------------------------------------------------------------------------- #
# --- EX-SAU-14 : aucune purge pendant la soirée ---------------------------
avant = len(list(config.projet().dossier_instantanes.glob("app-*.db")))
depot_objet.depots_actifs = lambda: [bon]
# Sans attente entre les passages : le nom porte les millisecondes, donc
# deux instantanés rapprochés ne peuvent plus s'effacer l'un l'autre.
for _ in range(3):
    instantane.un_passage()
depot_objet.depots_actifs = _vrais_depots
apres = len(list(config.projet().dossier_instantanes.glob("app-*.db")))
assert apres >= avant + 3, f"{avant} → {apres} : rien ne doit être purgé"

# --- EX-SAU-18 : l'instantané n'est PAS une tâche de la file --------------
from modeles import Tache  # noqa: E402

with bd.Seance() as s:
    types = {t for (t,) in s.execute(sa.select(Tache.type).distinct())}
assert "instantane_base" not in types, \
    "mis en file, l'instantané attendrait derrière cent générations"
import taches  # noqa: E402
assert "instantane" not in " ".join(taches.PRIORITES), taches.PRIORITES

# --- EX-SAU-13 : la période est bien de trois minutes ---------------------
assert instantane.PERIODE_S == 180.0

# --- La boucle s'éteint quand on le lui demande ---------------------------
assert instantane.demarrer() is False, "INSTANTANE_ACTIF=0 doit l'inhiber"
os.environ["INSTANTANE_ACTIF"] = "1"
instantane.PERIODE_S = 0.2
depot_objet.depots_actifs = lambda: [bon]
assert instantane.demarrer() is True
time.sleep(0.6)
instantane.arreter()
depot_objet.depots_actifs = _vrais_depots
instantane.PERIODE_S = 180.0
os.environ["INSTANTANE_ACTIF"] = "0"
assert len(list(config.projet().dossier_instantanes.glob("app-*.db"))) > apres, \
    "la boucle doit avoir produit au moins un instantané de plus"
assert not any(f.name == "instantane" and f.is_alive()
               for f in threading.enumerate()), "le fil doit s'être arrêté"

print("TOUT PASSE — aucune purge, hors file, boucle démarrable et arrêtable")

import shutil  # noqa: E402
shutil.rmtree(racine, ignore_errors=True)

# --- Rien n'a changé, rien ne part ------------------------------------------
# Deux instantanés d'une base inchangée sont identiques au bit près : sans ce
# contrôle, dix jours d'attente avant l'événement déposeraient 4 800 fois le
# même fichier, soit 788 Mo pour zéro information.
#
# LE PIÈGE : écrire la ligne `sauvegarde` d'un dépôt modifie la base, donc
# l'instantané suivant diffère, donc il se redépose — la boucle se nourrirait
# d'elle-même. L'empreinte porte donc sur le CONTENU MÉTIER, `sauvegarde` et
# `tache` exclues.
class DepotCompteur(depot_objet.DepotObjet):
    def __init__(self):
        self.nom = "compteur"
        self.recus = []

    def deposer(self, cle, contenu):
        self.recus.append(cle)
        return len(contenu)

    def lire(self, cle):
        return b"sonde de demarrage"

    def supprimer(self, cle):
        pass


compteur = DepotCompteur()
depot_objet.depots_actifs = lambda: [compteur]
instantane._chemin_empreinte().unlink(missing_ok=True)
# Les blocs précédents ont laissé des lignes : on repart d'une table vide,
# sinon le décompte ci-dessous mesurerait leur travail.
with bd.Seance() as s:
    s.execute(sa.delete(Sauvegarde))
    s.commit()

assert instantane.un_passage(), "le premier passage dépose toujours"
for tour in range(12):
    assert instantane.un_passage() == [], \
        f"passage {tour + 2} : rien n'a changé, rien ne doit partir"
assert len(compteur.recus) == 1, \
    f"{len(compteur.recus)} dépôts pour treize passages — la boucle " \
    f"s'auto-alimente : la comptabilité des sauvegardes doit être exclue " \
    f"de l'empreinte"

# Et le journal des sauvegardes n'a bien qu'une ligne : un passage sans dépôt
# n'écrit rien, sinon il modifierait la base qu'il observe.
with bd.Seance() as s:
    lignes = s.scalar(sa.select(sa.func.count()).select_from(Sauvegarde))
assert lignes == 1, f"{lignes} lignes de sauvegarde pour un seul dépôt"

# Une vraie modification relance le dépôt, immédiatement.
test_outils.creer_chronique("Changement", "Reel", {"metier": "nouveau"}, main.CODES_LIEUX)
assert instantane.un_passage(), "un changement de contenu doit repartir"
assert len(compteur.recus) == 2
assert instantane.un_passage() == [], "et le passage suivant se tait de nouveau"

# Une tâche qui s'incrémente n'est PAS une modification à sauvegarder :
# `EX-ARC-11` la rattrape au redémarrage, et la compter relancerait un dépôt
# à chaque tentative.
import taches  # noqa: E402

taches.mettre_en_file("generation_chronique", "objet-sans-importance")
assert instantane.un_passage() == [], \
    "la file de tâches ne doit pas déclencher de sauvegarde"

# --- Le plancher : un dépôt même sans changement --------------------------
# Sans lui, dix jours de calme seraient indiscernables d'une panne silencieuse
# des deux dépôts, et personne ne s'en apercevrait avant d'en avoir besoin.
assert instantane.PLANCHER_S == 6 * 3600.0
_plancher = instantane.PLANCHER_S
instantane.PLANCHER_S = 0.0
assert instantane.un_passage(), "le plancher doit forcer un dépôt"
instantane.PLANCHER_S = _plancher

# --- L'empreinte survit au redémarrage ------------------------------------
# Sans cela, chaque redéploiement reverserait un instantané identique — et il
# y en aura plusieurs d'ici au 5 septembre.
avant = len(compteur.recus)
empreinte, _ = instantane._derniere_deposee()
assert empreinte and len(empreinte) == 64
assert instantane.un_passage() == [], "l'empreinte mémorisée doit tenir"

# Un échec des DEUX dépôts ne doit pas être pris pour un succès : le contenu
# doit repartir au passage suivant.
casse2 = DepotMuet("casse2", ecriture_ko=True)
depot_objet.depots_actifs = lambda: [casse2]
test_outils.creer_chronique("Apres", "Echec", {"metier": "z"}, main.CODES_LIEUX)
instantane.un_passage()
depot_objet.depots_actifs = lambda: [compteur]
assert instantane.un_passage(), \
    "après un échec total, le contenu doit repartir à la tentative suivante"

depot_objet.depots_actifs = _vrais_depots
print("TOUT PASSE — rien ne part si rien ne change, la boucle ne s'auto-alimente pas")
