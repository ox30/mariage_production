"""B3 — la copie des photos hors du volume (EX-SAU-01, EX-SAU-19, EX-SAU-20).

Ce qui compte ici n'est pas que la copie marche, c'est qu'un dépôt objet
indisponible ne casse **rien** : la photo reste sur le volume, elle s'affiche,
l'invité n'en sait rien — et le tableau de bord, lui, le dit.

Les dépôts réels ne sont pas joignables depuis un poste de test : on éprouve
contre `DepotLocal`, qui écrit dans un dossier, et contre un dépôt qui refuse.
"""

import io
import os
import shutil
import tempfile

os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")

from PIL import Image
from sqlalchemy import select

import base_donnees as bd
import config
import depot_objet
import main
import photos
import taches
import test_outils
from modeles import Journal, Photo, Tache

ADMIN = ("admin", os.environ.get("MOT_DE_PASSE_ADMIN", "essai-admin"))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", ADMIN[1])

client = test_outils.client(main.app)


def _img(largeur=1200, hauteur=900) -> bytes:
    tampon = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), (70, 100, 60)).save(tampon, "JPEG")
    return tampon.getvalue()


def _vider_la_file(bornes=30):
    """Traite jusqu'à ce qu'il n'y ait plus rien de réclamable.

    Compter les appels à `traiter_une()` supposait que la file ne contienne que
    ses propres tâches — faux dès qu'un bloc précédent en a laissé une, et le
    test éprouvait alors la tâche de quelqu'un d'autre. Les tâches différées
    portent un `reprendre_apres` futur : elles ne sont pas réclamées ici.
    """
    for _ in range(bornes):
        if not taches.traiter_une():
            return
    raise AssertionError("la file ne se vide pas")


def _chronique(prenom):
    identifiant = test_outils.creer_chronique(
        prenom, "Copie", {"metier": "x", "allegeance": "La Lumière"},
        main.CODES_LIEUX, etat="prete")
    bd.enregistrer_portrait(identifiant, {
        "nom_fictif": f"{prenom} le Gardien", "peuple": "homme",
        "portrait": "Un paragraphe.", "indice": "Un indice.",
        "fuites_noms": [], "modele": "claude-sonnet-5", "duree_s": 5.0,
        "jetons_entree": 800, "jetons_sortie": 250})
    return bd.lire(identifiant)


class DepotRefusant(depot_objet.DepotObjet):
    """Un fournisseur qui répond, mais mal — le cas réel d'une clé périmée."""

    nom = "refusant"

    def deposer(self, identifiant, contenu):
        raise OSError("403 Forbidden")

    def lire(self, identifiant):
        raise OSError("403 Forbidden")


_greniers = []


def _deux_depots_locaux():
    depots = []
    for nom in ("railway", "r2"):
        dossier = tempfile.mkdtemp(prefix=f"depot-{nom}-")
        _greniers.append(dossier)
        depot = depot_objet.DepotLocal(dossier)
        depot.nom = nom
        depots.append(depot)
    return depots


# --- sans destination configurée, la copie ne casse rien ----------------- #

# Un poste de développement n'a aucun dépôt. Échouer ici remplirait la file de
# rouge sur une machine où il n'y a rien à sauvegarder.
assert depot_objet.depots_actifs() == []
sans_depot = _chronique("Noémie")
photo_sans = photos.deposer(sans_depot.personne_uuid, _img())
_vider_la_file()
with bd.Seance() as seance:
    tache = seance.scalar(select(Tache).where(
        Tache.objet_uuid == photo_sans.uuid,
        Tache.type == "copie_stockage_objet"))
assert tache.etat == "terminee", tache.etat
assert photos.copiees() == set()
assert photos.reprendre_copies_manquantes() == 0

print("TOUT PASSE — sans destination, la copie passe sans rien salir")


# --- la copie dépose les trois fichiers sur les deux dépôts -------------- #

depots = _deux_depots_locaux()
_reels = depot_objet.depots_actifs
depot_objet.depots_actifs = lambda: depots
photos.depot_objet.depots_actifs = depot_objet.depots_actifs

olivier = _chronique("Olivier")
photo = photos.deposer(olivier.personne_uuid, _img(2400, 1800))
_vider_la_file()
with bd.Seance() as seance:
    assert seance.get(Photo, photo.uuid).etat == "prete"

# EX-SAU-19 — un seul bucket, préfixé par le projet, et le préfixe vient de
# `projet-actif.txt`. Jamais tapé à la main : c'est ce qui a manqué le jour où
# des sauvegardes sont parties dans un préfixe orphelin.
prefixe = depot_objet.prefixe_projet()
assert config.projet().identifiant in prefixe

for grenier in _greniers:
    deposes = [str(c) for c in __import__("pathlib").Path(grenier).rglob("*")
               if c.is_file()]
    # Les trois variantes, l'original d'abord : lui seul est irremplaçable,
    # les deux autres se reconstruisent à partir de lui.
    for variante in ("originaux", "web", "vignettes"):
        assert any(f"photos/{variante}/" in c.replace("\\", "/")
                   for c in deposes), (variante, deposes)
    assert any(prefixe.split("/")[-1] in c for c in deposes), deposes

# Le contenu déposé est bien celui du volume, pas une reconstruction.
original = (config.projet().dossier_medias / "photos_invites" / "originaux"
            / photo.chemin_original)
copie = next(c for c in __import__("pathlib").Path(_greniers[0]).rglob("*")
             if c.is_file() and "originaux" in str(c))
assert copie.read_bytes() == original.read_bytes()

assert photo.uuid in photos.copiees()


def _en_file_copie(identifiant):
    with bd.Seance() as seance:
        return seance.scalar(select(Tache).where(
            Tache.type == "copie_stockage_objet",
            Tache.objet_uuid == identifiant,
            Tache.etat.in_(("en_attente", "en_cours")))) is not None


# La reprise ne redemande PAS celle-ci. Elle en remet d'autres en file — la
# photo du premier bloc, déposée quand aucun dépôt n'existait —, et c'est
# précisément ce qu'on attend d'elle : compter sur zéro aurait éprouvé le
# nombre de photos en base plutôt que la règle.
photos.reprendre_copies_manquantes()
assert not _en_file_copie(photo.uuid), \
    "une photo déjà copiée a été remise en file"
assert _en_file_copie(photo_sans.uuid), \
    "la photo déposée sans dépôt actif n'a pas été rattrapée"

print("TOUT PASSE — trois variantes déposées sur les deux dépôts, sous le préfixe")


# --- un dépôt qui refuse ne touche PAS à la photo ------------------------ #

# Un fournisseur indisponible est un défaut de SAUVEGARDE, pas de photo :
# l'invité n'a rien à savoir et sa chronique s'affiche exactement pareil.
depot_objet.depots_actifs = lambda: [depots[0], DepotRefusant()]
photos.depot_objet.depots_actifs = depot_objet.depots_actifs

pauline = _chronique("Pauline")
photo_ko = photos.deposer(pauline.personne_uuid, _img())
budget_avant = photos.budget(pauline.personne_uuid).restants
_vider_la_file()

with bd.Seance() as seance:
    ligne = seance.get(Photo, photo_ko.uuid)
    assert ligne.etat == "prete", "un dépôt objet en panne a abîmé la photo"
    assert ligne.supprimee is False
assert photos.budget(pauline.personne_uuid).restants == budget_avant, \
    "un échec de sauvegarde a été décompté à l'invité"

# L'invité voit sa vignette comme si de rien n'était.
with bd.Seance() as seance:
    vignette = seance.get(Photo, photo_ko.uuid).chemin_vignette
assert vignette
assert f'src="/photo/{pauline.uuid}/vignette?v=' in client.get(
    f"/portrait/{pauline.uuid}").text

# TEMPORAIRE, jamais définitif : un fournisseur muet maintenant répondra
# peut-être dans quatre secondes, et la photo est sur le volume en attendant.
with bd.Seance() as seance:
    tache = seance.scalar(select(Tache).where(
        Tache.objet_uuid == photo_ko.uuid,
        Tache.type == "copie_stockage_objet"))
assert tache.etat == "en_attente", tache.etat
assert tache.reprendre_apres is not None
assert photo_ko.uuid not in photos.copiees()

# Et la trace dit ce qui a manqué, pas seulement qu'il a manqué.
with bd.Seance() as seance:
    trace = seance.scalar(select(Journal).where(
        Journal.objet_uuid == photo_ko.uuid,
        Journal.action == Journal.PHOTO_COPIE_ECHOUEE))
assert trace is not None and "refusant" in trace.details_json

print("TOUT PASSE — un dépôt en panne n'abîme ni la photo ni le budget")


# --- la copie repart quand le dépôt revient ------------------------------ #

depot_objet.depots_actifs = lambda: depots
photos.depot_objet.depots_actifs = depot_objet.depots_actifs

# La reprise ne double PAS le travail : la tâche différée est déjà en file, il
# n'y a rien à y remettre.
assert photos.reprendre_copies_manquantes() == 0
assert _en_file_copie(photo_ko.uuid)

# On fait écouler le délai plutôt que d'attendre : une temporisation réelle
# rendrait le test lent et intermittent, et un test intermittent finit par
# être ignoré.
with bd.Seance() as seance:
    seance.get(Tache, seance.scalar(select(Tache.uuid).where(
        Tache.objet_uuid == photo_ko.uuid,
        Tache.type == "copie_stockage_objet"))).reprendre_apres = \
        config.maintenant()
    seance.commit()
_vider_la_file()
assert photo_ko.uuid in photos.copiees(), \
    "la copie n'est pas repartie une fois le dépôt revenu"
# Ne boucle pas : une copie réussie sort la photo de la requête.
assert photos.reprendre_copies_manquantes() == 0
assert not _en_file_copie(photo_ko.uuid)

print("TOUT PASSE — la copie repart au retour du dépôt, et ne boucle pas")


# --- le tableau de bord compte ce qui n'est QUE sur le volume ------------ #

# C'est le seul chiffre de sauvegarde qui ne se lit nulle part ailleurs : les
# instantanés portent les chroniques, jamais les fichiers.
import re

def _chiffre(page, etiquette):
    trouve = re.search(
        rf'chiffre[^"]*">(\d+)</span>\s*<span class="etiquette">{etiquette}',
        page)
    assert trouve, f"« {etiquette} » absent du tableau"
    return int(trouve.group(1))

page = client.get("/admin/tableau", auth=ADMIN).text
reference = _chiffre(page, "photos hors du stockage objet")

quentin = _chronique("Quentin")
photos.deposer(quentin.personne_uuid, _img())
assert taches.traiter_une() is True                    # conversion seule
apres = _chiffre(client.get("/admin/tableau", auth=ADMIN).text,
                 "photos hors du stockage objet")
# Un ÉCART, jamais une valeur absolue : d'autres photos traînent en base.
assert apres - reference == 1, (reference, apres)

assert taches.traiter_une() is True                    # la copie
final = _chiffre(client.get("/admin/tableau", auth=ADMIN).text,
                 "photos hors du stockage objet")
assert final == reference, (reference, final)

print("TOUT PASSE — le tableau compte les photos qui n'existent que sur le volume")

depot_objet.depots_actifs = _reels
photos.depot_objet.depots_actifs = _reels
for _grenier in _greniers:
    shutil.rmtree(_grenier, ignore_errors=True)
