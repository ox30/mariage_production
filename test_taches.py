"""File de tâches et worker. Lancer : python test_taches.py

Couvre EX-ARC-09 à EX-ARC-14 (file persistée, worker, reprise au démarrage,
priorité, trois tentatives), EX-ARC-20 (fils réglables à chaud), EX-ARC-21
(barrière globale de débit), EX-IA-43 (une seule génération vivante) et
EX-IA-25 / EX-IA-32 (position dans la file, temps réellement écoulé).

Le worker est **éteint** ici : les tâches sont exécutées à la demande par
`traiter_une()`. Une attente arbitraire produit des tests qui passent une fois
sur deux, et un test intermittent finit toujours par être ignoré.
"""
import os
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ["MOT_DE_PASSE_ADMIN"] = "secret"
os.environ["WORKER_ACTIF"] = "0"

import sqlalchemy as sa

import base_donnees as bd
import config
import main
import taches
from modeles import Tache

bd.initialiser()
taches.lever_suspension()


def vider():
    with bd.Seance() as seance:
        seance.execute(sa.delete(Tache))
        seance.commit()
    taches.lever_suspension()
    taches._traitants.pop("conversion_image", None)


# --------------------------------------------------------------------------- #
# --- EX-ARC-09 et EX-ARC-12 : la file sert par priorité, puis par âge -----
vider()

# Une photo se traite en silence, un invité attend devant son écran : la
# génération passe devant, quel que soit l'ordre d'arrivée (EX-ARC-12).
taches.mettre_en_file("copie_stockage_objet", "copie")
time.sleep(0.01)
taches.mettre_en_file("conversion_image", "image")
time.sleep(0.01)
taches.mettre_en_file("generation_chronique", "chronique")

ordre = []
while (t := taches.reclamer()) is not None:
    ordre.append(t.type)
assert ordre == ["generation_chronique", "conversion_image",
                 "copie_stockage_objet"], ordre
assert (Tache.PRIORITE_GENERATION < Tache.PRIORITE_CONVERSION
        < Tache.PRIORITE_COPIE)

# Un type inconnu n'est pas « une tâche déjà en file » : la contrainte
# `ck_tache_type` doit remonter, sinon le défaut resterait invisible.
try:
    taches.mettre_en_file("type_invente", "x")
except Exception as exc:
    assert "IntegrityError" in type(exc).__name__, type(exc).__name__
else:
    raise AssertionError("un type inconnu doit échouer bruyamment")

print("TOUT PASSE — la génération passe avant l'image, l'image avant la copie")

# --------------------------------------------------------------------------- #
# --- La réclamation est atomique : huit fils, aucune tâche servie deux fois
vider()
for i in range(60):
    taches.mettre_en_file("conversion_image", f"objet-{i}")

prises: list[str] = []
verrou = threading.Lock()


def rafler():
    while True:
        t = taches.reclamer()
        if t is None:
            return
        with verrou:
            prises.append(t.uuid)


fils = [threading.Thread(target=rafler) for _ in range(8)]
for f in fils:
    f.start()
for f in fils:
    f.join()

assert len(prises) == 60, f"{len(prises)} prises pour 60 tâches"
assert len(set(prises)) == 60, "une tâche a été servie deux fois"

print("TOUT PASSE — 8 fils, 60 tâches, aucune servie deux fois")

# --------------------------------------------------------------------------- #
# --- EX-IA-43 : une seule génération vivante par chronique ----------------
vider()
premier = taches.mettre_en_file("generation_chronique", "chr-1")
second = taches.mettre_en_file("generation_chronique", "chr-1")
assert premier is not None and second is None, \
    "le double appui ne doit pas produire deux générations (EX-IA-43)"

# Une fois la première terminée, une nouvelle est admise : le plafond porte
# sur les tâches vivantes, pas sur l'historique.
taches.terminer(premier)
assert taches.mettre_en_file("generation_chronique", "chr-1") is not None

# Et la contrainte ne vise que la génération : une conversion peut coexister.
assert taches.mettre_en_file("conversion_image", "chr-1") is not None

print("TOUT PASSE — le double appui ne produit qu'une génération")

# --------------------------------------------------------------------------- #
# --- EX-ARC-11 : ce qu'un redéploiement interrompt repart -----------------
vider()
taches.mettre_en_file("conversion_image", "interrompue")
prise = taches.reclamer()
assert prise is not None and prise.tentatives == 1, \
    "la tentative se décompte à la prise, pas à l'échec : une tâche perdue " \
    "dans un redémarrage a bien coûté un essai"
with bd.Seance() as seance:
    assert seance.get(Tache, prise.uuid).etat == "en_cours"

# Le conteneur meurt ici. Au démarrage suivant :
assert taches.reprendre_interrompues() == 1
with bd.Seance() as seance:
    reprise = seance.get(Tache, prise.uuid)
    assert reprise.etat == "en_attente" and reprise.demarree_le is None
    assert reprise.tentatives == 1, "les tentatives déjà usées ne sont pas rendues"
assert taches.reclamer() is not None, "la tâche repart"

print("TOUT PASSE — une tâche interrompue repart, sans rendre ses tentatives")

# --------------------------------------------------------------------------- #
# --- EX-ARC-13 : trois tentatives, puis abandon ---------------------------
vider()
essais = {"n": 0}


def toujours_temporaire(objet):
    essais["n"] += 1
    raise taches.EchecTemporaire("529 — saturation")


taches.enregistrer_traitant("conversion_image", toujours_temporaire)
taches.mettre_en_file("conversion_image", "obstinee")

for attendu in (1, 2, 3):
    with bd.Seance() as seance:
        tache = seance.scalar(sa.select(Tache).where(Tache.objet_uuid == "obstinee"))
        if tache.reprendre_apres is not None:
            # L'attente croissante est réelle ; on la neutralise pour ne pas
            # faire dormir le test sept secondes.
            tache.reprendre_apres = None
            seance.commit()
    assert taches.traiter_une(), f"tentative {attendu} non exécutée"

assert essais["n"] == 3, f"{essais['n']} appels, trois attendus (EX-ARC-13)"
with bd.Seance() as seance:
    tache = seance.scalar(sa.select(Tache).where(Tache.objet_uuid == "obstinee"))
    assert tache.etat == "echouee", tache.etat
    assert "abandon après 3 tentatives" in tache.derniere_erreur
assert not taches.traiter_une(), "une tâche abandonnée ne se rejoue pas"

# Un échec définitif ne consomme pas trois tentatives contre un mur.
vider()
essais["n"] = 0


def toujours_definitif(objet):
    essais["n"] += 1
    raise taches.EchecDefinitif("401 — clé refusée")


taches.enregistrer_traitant("conversion_image", toujours_definitif)
taches.mettre_en_file("conversion_image", "mur")
assert taches.traiter_une()
assert essais["n"] == 1, "un 401 ne se réessaie pas"
with bd.Seance() as seance:
    assert seance.scalar(sa.select(Tache.etat)
                         .where(Tache.objet_uuid == "mur")) == "echouee"

print("TOUT PASSE — trois tentatives, puis abandon ; un mur n'en consomme qu'une")

# --------------------------------------------------------------------------- #
# --- Le délai de retry-after prime sur l'attente croissante ---------------
vider()


def limite_avec_delai(objet):
    raise taches.EchecTemporaire("429", reprendre_apres_s=12.0,
                                 suspendre_tout_s=12.0)


taches.enregistrer_traitant("conversion_image", limite_avec_delai)
taches.mettre_en_file("conversion_image", "429")
taches.traiter_une()
with bd.Seance() as seance:
    tache = seance.scalar(sa.select(Tache).where(Tache.objet_uuid == "429"))
    attente = (tache.reprendre_apres - config.maintenant()).total_seconds()
    assert 10 <= attente <= 13, f"{attente} s au lieu des 12 annoncées"
    assert tache.etat == "en_attente"

# Et la tâche n'est pas servie avant l'échéance.
assert taches.reclamer() is None, "une tâche différée ne se réclame pas"

# --- EX-ARC-21 : la limitation ralentit TOUS les fils ---------------------
# Sans barrière globale, huit fils se cognent chacun à leur tour au même mur
# et consomment le quota pour rien.
assert taches.secondes_de_suspension() > 10, "la barrière globale doit être posée"
taches.mettre_en_file("conversion_image", "autre-objet")
assert taches.secondes_de_suspension() > 0
taches.lever_suspension()
assert taches.secondes_de_suspension() == 0

# Un 529 ne pose PAS la barrière : la saturation du fournisseur se traite
# tâche par tâche, seul le 429 est propre au compte (EX-IA-22).
vider()
taches.enregistrer_traitant("conversion_image", toujours_temporaire)
taches.mettre_en_file("conversion_image", "529")
taches.traiter_une()
assert taches.secondes_de_suspension() == 0, \
    "un 529 ne doit pas suspendre tout le service"

print("TOUT PASSE — retry-after honoré, barrière globale sur 429 seulement")

# --------------------------------------------------------------------------- #
# --- EX-ARC-20 : le nombre de fils se règle sans redéployer ---------------
assert taches.fils_actifs() == taches.FILS_DEFAUT, "valeur par défaut"

volume = pathlib.Path(config.racine_donnees())
dossier = volume / "projets" / "reglage"
dossier.mkdir(parents=True, exist_ok=True)
(dossier / "config.yaml").write_text(
    'projet:\n  identifiant: reglage\n  nom: "Réglage"\n  type: preparation\n'
    '  langue: fr\nworker:\n  fils: 3\n', encoding="utf-8")
import shutil  # noqa: E402
shutil.copy(pathlib.Path(main.RACINE) / "questions.yaml", dossier / "questions.yaml")
(volume / "projet-actif.txt").write_text("reglage\n", encoding="utf-8")
ancien_exiger = os.environ.pop("EXIGER_VOLUME", None)
ancienne_racine = os.environ.get("RACINE_DONNEES")
os.environ["EXIGER_VOLUME"] = "1"
os.environ["RACINE_DONNEES"] = str(volume)
config.oublier()
assert taches.fils_actifs() == 3, taches.fils_actifs()

# La modification prend effet sans redémarrer, une fois le délai de relecture
# écoulé : EX-SAU-09 gèle les déploiements pendant toute la soirée.
(dossier / "config.yaml").write_text(
    (dossier / "config.yaml").read_text(encoding="utf-8").replace("fils: 3", "fils: 12"),
    encoding="utf-8")
config._cache_parametres.clear()
assert taches.fils_actifs() == 12, "le réglage doit s'appliquer à chaud"

# Une valeur aberrante est bornée plutôt que d'être prise au mot.
(dossier / "config.yaml").write_text(
    (dossier / "config.yaml").read_text(encoding="utf-8").replace("fils: 12", "fils: 400"),
    encoding="utf-8")
config._cache_parametres.clear()
assert taches.fils_actifs() == taches.FILS_MAX, "400 fils doivent être bornés"

if ancien_exiger is None:
    os.environ.pop("EXIGER_VOLUME", None)
if ancienne_racine is None:
    os.environ.pop("RACINE_DONNEES", None)
else:
    os.environ["RACINE_DONNEES"] = ancienne_racine
shutil.rmtree(dossier)
(volume / "projet-actif.txt").unlink(missing_ok=True)
config.oublier()

print("TOUT PASSE — fils réglables à chaud, valeurs aberrantes bornées")

# --------------------------------------------------------------------------- #
# --- EX-IA-25 et EX-IA-32 : ce que l'invité lit ---------------------------
vider()
taches.enregistrer_traitant("conversion_image", lambda o: None)
identifiants = [taches.mettre_en_file("generation_chronique", f"file-{i}")
                for i in range(5)]
assert taches.position("file-0") == 1
assert taches.position("file-3") == 4
assert taches.position("inconnu") is None, "aucune tâche vivante, aucune position"

# Un ordre de grandeur, jamais une promesse — mais jamais zéro non plus.
# Défaut du 25 août : la formule `rang ÷ fils × durée` mesurait l'attente
# AVANT l'appel en oubliant l'appel. Le premier de la file recevait 4 secondes,
# arrondies à la dizaine, et l'écran annonçait « environ 0 secondes » pendant
# les trente secondes de la génération.
moyenne = taches.duree_moyenne_s()
assert taches.attente_estimee_s("file-0") >= moyenne, \
    "même seul dans la file, on attend la durée d'une génération"
assert round(taches.attente_estimee_s("file-0") / 10) * 10 > 0, \
    "l'estimation ne doit jamais s'arrondir à zéro"

# EX-IA-32 — le temps écoulé depuis la mise en file, non la durée de l'appel.
ecoule = taches.secondes_depuis_mise_en_file("file-3")
assert ecoule is not None and ecoule >= 0

# Une tâche en cours occupe un fil : elle précède, donc elle est première.
prise = taches.reclamer()
assert taches.position(prise.objet_uuid) == 1

# Les fils servent par fournées : les huit premiers ensemble, puis les
# suivants. File vidée d'abord, sans quoi les tâches précédentes décaleraient
# les rangs et l'assertion mesurerait autre chose que ce qu'elle annonce.
vider()
taches.enregistrer_traitant("conversion_image", lambda o: None)
for i in range(20):
    taches.mettre_en_file("conversion_image", f"fournee-{i}")
assert taches.position("fournee-0") == 1 and taches.position("fournee-19") == 20
assert taches.attente_estimee_s("fournee-0") == taches.attente_estimee_s("fournee-3"), \
    "deux rangs de la même fournée attendent autant"
assert (taches.attente_estimee_s("fournee-19")
        > taches.attente_estimee_s("fournee-0")), \
    "une fournée plus loin, on attend plus longtemps"

# Aucune durée mesurée : la valeur par défaut sert, sans mentir sur sa nature.
vider()
assert taches.duree_moyenne_s() == 32.0

print("TOUT PASSE — position, ordre de grandeur et temps réellement écoulé")

# --------------------------------------------------------------------------- #
# --- Le worker s'éteint quand on le lui demande ---------------------------
assert taches.demarrer() == 0, "WORKER_ACTIF=0 doit inhiber le worker"
os.environ["WORKER_ACTIF"] = "1"
vider()
compte = {"n": 0}
taches.enregistrer_traitant("conversion_image", lambda o: compte.__setitem__("n", compte["n"] + 1))
for i in range(12):
    taches.mettre_en_file("conversion_image", f"worker-{i}")
assert taches.demarrer() == taches.FILS_MAX
fin = time.monotonic() + 10
while compte["n"] < 12 and time.monotonic() < fin:
    time.sleep(0.05)
taches.arreter()
os.environ["WORKER_ACTIF"] = "0"
assert compte["n"] == 12, f"{compte['n']} tâches traitées sur 12"
with bd.Seance() as seance:
    restantes = seance.scalar(sa.select(sa.func.count()).select_from(Tache)
                              .where(Tache.etat != "terminee"))
assert restantes == 0, f"{restantes} tâches non terminées"

print("TOUT PASSE — le worker vide la file, puis s'arrête proprement")
vider()

# --- La ligne de démarrage du worker ne fabrique pas de fausse anomalie ----
# « 16 fil(s) démarré(s), limite courante 8 » se lisait comme une incohérence :
# les fils au-delà de la limite dorment, mais la ligne ne le disait pas. Ce
# qu'on éprouve : les deux nombres sont présents ET leur rapport est expliqué.
import main as _main, taches as _t

_vrai_demarrer, _vrai_actifs = _t.demarrer, _t.fils_actifs
_t.demarrer = lambda: 16
_t.fils_actifs = lambda: 8
import io, contextlib, asyncio
_sortie = io.StringIO()
try:
    with contextlib.redirect_stdout(_sortie):
        async def _passer():
            async with _main.cycle_de_vie(_main.app):
                pass
        asyncio.run(_passer())
finally:
    _t.demarrer, _t.fils_actifs = _vrai_demarrer, _vrai_actifs
_ligne = [l for l in _sortie.getvalue().splitlines() if l.startswith("worker")]
assert len(_ligne) == 1, _sortie.getvalue()
assert "8" in _ligne[0] and "16" in _ligne[0], _ligne[0]
# Sans ce mot, les deux nombres restent une contradiction apparente.
assert "dorment" in _ligne[0], _ligne[0]
print("TOUT PASSE — la ligne du worker explique l'écart entre réserve et travail")
