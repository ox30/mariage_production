"""C2 — voir : l'administrateur peut enfin observer (EX-ADM-18, EX-ADM-21).

Ce qui est éprouvé ici : que la production et le test restent séparés, que les
photos ne soient jamais atteignables sans mot de passe, et qu'aucun segment
d'URL ne serve à construire un chemin de fichier.
"""

import html as html_module
import json
import os
import re
import struct

os.environ.setdefault("WORKER_ACTIF", "0")
os.environ.setdefault("INSTANTANE_ACTIF", "0")

import base_donnees as bd
import config
import main
import photos
import test_outils
from modeles import Photo

ADMIN = ("admin", os.environ.get("MOT_DE_PASSE_ADMIN", "essai-admin"))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", ADMIN[1])

client = test_outils.client(main.app)


def _texte(page: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(page))


def _jpeg() -> bytes:
    exif = b"Exif\x00\x00" + b"\x00" * 200
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
    sof = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
           + struct.pack(">HH", 3024, 4032) + b"\x03" + b"\x00" * 9)
    return b"\xff\xd8" + app1 + sof + b"\xff\xda\x00\x0c" + b"\x00" * 900


def _chronique(prenom, est_test=False):
    identifiant = test_outils.creer_chronique(
        prenom, "Fiche",
        {"metier": "aiguilleur", "attachement": "La nature",
         "allegeance": "La Lumière", "souvenir": "un quai désert",
         "souhait": "tout le bonheur du monde"},
        main.CODES_LIEUX, etat="prete")
    bd.enregistrer_portrait(identifiant, {
        "nom_fictif": f"{prenom} du Val", "peuple": "homme",
        "portrait": "Premier paragraphe.\n\nSecond paragraphe.",
        "indice": "Il veille aux aiguillages.", "fuites_noms": [],
        "modele": "claude-sonnet-5", "duree_s": 7.1,
        "jetons_entree": 900, "jetons_sortie": 300})
    if est_test:
        with bd.Seance() as seance:
            from modeles import Chronique
            seance.get(Chronique, identifiant).est_test = True
            seance.commit()
    return bd.lire(identifiant)


# --- l'administration est fermée, y compris aux fichiers ------------------- #

# Le client de test a franchi la porte des invités : s'il atteignait les
# écrans d'administration, tout ce qui suit ne prouverait rien.
maree = _chronique("Jocelyne")
photos.deposer(maree.personne_uuid, _jpeg())

for chemin in ("/admin/chroniques", f"/admin/chronique/{maree.uuid}",
               f"/admin/chronique/{maree.uuid}.json",
               f"/admin/photo/{maree.uuid}/originaux"):
    assert client.get(chemin).status_code == 401, chemin

print("TOUT PASSE — chroniques, fiches et fichiers sont fermés sans mot de passe")


# --- la liste sépare production et test ----------------------------------- #

essai = _chronique("Kevin", est_test=True)

liste = client.get("/admin/chroniques", auth=ADMIN)
assert liste.status_code == 200
assert "Jocelyne" in liste.text
# EX-TST-04 — la table de test est invisible par DÉFAUT, ici comme partout.
assert "Kevin" not in liste.text, "une chronique de test apparaît en production"

liste_test = client.get("/admin/chroniques?test=oui", auth=ADMIN)
assert "Kevin" in liste_test.text
assert "Jocelyne" not in liste_test.text
# Le tableau était devenu aveugle au test le jour où `lister()` l'a exclu :
# le lien qui y mène doit exister, sinon on ne l'atteint jamais.
assert 'href="/admin/chroniques?test=oui"' in liste.text

# L'onglet est dans la barre, sinon rien n'y mène.
assert 'href="/admin/chroniques"' in client.get(
    "/admin/invites", auth=ADMIN).text

print("TOUT PASSE — production et test séparés, et l'onglet est atteignable")


# --- la colonne photo distingue les quatre cas ---------------------------- #

sans = _chronique("Ludivine")


def _rangee(page: str, nom: str) -> str:
    """La LIGNE du tableau, pas la page.

    Un découpage sur le nom échoue ici pour une raison invisible à la lecture :
    « Ludivine » apparaît deux fois dans sa propre rangée — dans son prénom et
    dans son nom fictif « Ludivine du Val ». Le segment entre les deux
    occurrences ne contient pas la colonne cherchée. Cibler la structure.
    """
    rangees = [r for r in re.split(r"<tr[^>]*>", page) if nom in r]
    assert len(rangees) == 1, f"{len(rangees)} rangée(s) pour {nom}"
    return _texte(rangees[0])


page = client.get("/admin/chroniques", auth=ADMIN).text
assert "aucune" in _rangee(page, "Ludivine"), _rangee(page, "Ludivine")
assert "en traitement" in _rangee(page, "Jocelyne"), _rangee(page, "Jocelyne")

print("TOUT PASSE — la liste distingue une photo absente d'une photo en cours")


# --- la fiche montre les réponses, le portrait et la photo ---------------- #

# La fiche est désormais découpée en sous-onglets, chacun à SON adresse : on
# interroge celui qui porte ce qu'on éprouve, plutôt qu'une page unique.
fiche = client.get(f"/admin/chronique/{maree.uuid}?onglet=portrait", auth=ADMIN)
questions = client.get(f"/admin/chronique/{maree.uuid}?onglet=questionnaire",
                       auth=ADMIN)
onglet_photo = client.get(f"/admin/chronique/{maree.uuid}?onglet=photo",
                          auth=ADMIN)
assert fiche.status_code == 200
lu = _texte(fiche.text)

# Les réponses sont montrées sous leur INTITULÉ, pas sous leur clé nue : une
# fiche qui affiche « souvenir » ne se relit pas à côté de l'écran d'origine.
lu_questions = _texte(questions.text)
assert "aiguilleur" in lu_questions and "un quai désert" in lu_questions
assert "Quel est ton métier" in lu_questions, "l'intitulé de la question manque"
# La clé reste visible à côté : c'est elle qu'on cite dans questions.yaml.
assert "<code class=\"discret\">metier</code>" in questions.text

assert "Premier paragraphe." in lu and "Second paragraphe." in lu
assert "Il veille aux aiguillages." in lu

# La photo est là, et son état aussi.
assert "Reçue, pas encore convertie" in _texte(onglet_photo.text)
# `?v=` sur le LIEN autant que sur l'image : sans empreinte, le navigateur
# rendait l'ancien fichier. Les deux liens avaient été oubliés le 27 août.
assert f'href="/admin/photo/{maree.uuid}/originaux?v=' in onglet_photo.text

print("TOUT PASSE — la fiche montre réponses, portrait et état de la photo")


# --- l'export unitaire dit ce qu'il est ----------------------------------- #

# EX-ADM-21 — l'export complet est inexploitable pour vérifier un cas : cent
# chroniques dans un fichier ne se lisent pas.
export = client.get(f"/admin/chronique/{maree.uuid}.json", auth=ADMIN)
assert export.status_code == 200
donnees = export.json()
assert donnees["uuid"] == maree.uuid
assert donnees["reponses"]["metier"] == "aiguilleur"
assert donnees["portrait"].startswith("Premier paragraphe.")
# EX-TST-08 — le fichier dit ce qu'il est, dans son enveloppe ET dans son nom :
# l'une des deux marques se perd toujours.
assert donnees["portee"] == "production"
assert "-test" not in export.headers["content-disposition"]

export_test = client.get(f"/admin/chronique/{essai.uuid}.json", auth=ADMIN)
assert export_test.json()["portee"] == "test"
assert "-test.json" in export_test.headers["content-disposition"]

print("TOUT PASSE — l'export unitaire se distingue d'un export de test")


# --- le fichier vient de la base, jamais de l'URL ------------------------- #

photo = photos.courante(maree.personne_uuid)
originaux = config.projet().dossier_medias / "photos_invites" / "originaux"
assert (originaux / photo.chemin_original).is_file()

recu = client.get(f"/admin/photo/{maree.uuid}/originaux", auth=ADMIN)
assert recu.status_code == 200 and recu.content == _jpeg()

# `variante` est comparée à une liste close AVANT tout usage. Concaténée telle
# quelle, elle sortirait du dossier des médias — et la cible existe vraiment,
# sans quoi le test passerait grâce à son absence et non grâce au filtre.
cible = config.projet().dossier / "app.db"
assert cible.is_file(), "la cible de traversée doit exister"
for variante in ("..", "../..", "originaux/../../..", "logs"):
    reponse = client.get(f"/admin/photo/{maree.uuid}/{variante}", auth=ADMIN)
    assert reponse.status_code in (404, 400), (variante, reponse.status_code)

# Une variante légitime mais vide rend 404, jamais une erreur serveur.
assert client.get(f"/admin/photo/{maree.uuid}/web",
                  auth=ADMIN).status_code == 404
assert client.get(f"/admin/photo/{sans.uuid}/originaux",
                  auth=ADMIN).status_code == 404

print("TOUT PASSE — le chemin vient de la base, la variante d'une liste close")


# --- le tableau compte les photos ----------------------------------------- #

avant = client.get("/admin/tableau", auth=ADMIN).text
reference = int(re.search(r'chiffre">(\d+)</span>\s*<span class="etiquette">photos reçues',
                          avant).group(1))
photos.deposer(sans.personne_uuid, _jpeg())
apres = client.get("/admin/tableau", auth=ADMIN).text
obtenu = int(re.search(r'chiffre">(\d+)</span>\s*<span class="etiquette">photos reçues',
                       apres).group(1))
# Un écart, jamais une valeur absolue : le compteur ne part pas de zéro.
assert obtenu - reference == 1, (reference, obtenu)
assert "en conversion" in _texte(apres)

# La photo de test ne doit pas gonfler le compte de production.
photos.deposer(essai.personne_uuid, _jpeg(), est_test=True)
encore = int(re.search(r'chiffre">(\d+)</span>\s*<span class="etiquette">photos reçues',
                       client.get("/admin/tableau", auth=ADMIN).text).group(1))
assert encore == obtenu, "une photo de test compte dans le tableau de production"

print("TOUT PASSE — le tableau compte les photos, test exclu de la production")
