"""Schéma et persistance. Lancer : python test_modeles.py

Couvre EX-GEN-02 (clés UUID), EX-GEN-04 (UTC en base), EX-GEN-07 et EX-IA-21
(aucun compteur stocké), EX-IA-06 et EX-IA-42 (équilibrage sur le code stable),
EX-IA-26 (une chronique par personne), EX-IA-43 (une seule génération en
attente), EX-PRJ-06 et EX-SAU-07.

L'essentiel porte sur ce que le schéma **rend impossible**, pas sur ce qu'il
permet : un garde-fou qui n'a jamais été éprouvé n'en est pas un.
"""
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
os.environ.setdefault("MOT_DE_PASSE_ADMIN", "secret")

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, StatementError

import base_donnees as bd
import config
import main
import modeles
from modeles import Chronique, Journal, Personne, Tache
import test_outils

bd.initialiser()
CODES = main.CODES_LIEUX

# --------------------------------------------------------------------------- #
# --- Les dix entités existent, et rien de plus ----------------------------
inspecteur = sa.inspect(bd.moteur)
tables = set(inspecteur.get_table_names())
attendues = {"table_groupe", "personne", "appareil", "chronique", "photo",
             "reclamation", "tache", "journal", "etat_soiree", "sauvegarde"}
manquantes = attendues - tables
assert not manquantes, f"entités absentes de la section 5.1 : {manquantes}"
assert "alembic_version" in tables, "la révision appliquée doit être tracée"

# EX-GEN-02 — clés primaires UUID. `etat_soiree` est l'écart assumé : une table
# à une seule ligne, dont la clé entière porte la garantie d'unicité.
for table in attendues - {"etat_soiree"}:
    cles = inspecteur.get_pk_constraint(table)["constrained_columns"]
    assert cles == ["uuid"], f"{table} : clé primaire {cles}, attendu ['uuid']"

# EX-GEN-07, EX-IA-21 — aucune colonne de comptage nulle part.
for table in attendues:
    colonnes = {c["name"] for c in inspecteur.get_columns(table)}
    interdites = {c for c in colonnes
                  if c.startswith("nb_") and c not in ("nb_objets",)}
    assert not interdites, \
        f"{table} porte un compteur stocké : {interdites} (EX-GEN-07)"

# EX-SAU-07 — WAL.
with bd.moteur.connect() as cx:
    assert cx.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
    assert cx.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    # La base est la seule chose non régénérable du projet (EX-GEN-08).
    assert cx.exec_driver_sql("PRAGMA synchronous").scalar() == 2, "FULL attendu"

print("TOUT PASSE — dix entités, clés UUID, aucun compteur stocké")

# --------------------------------------------------------------------------- #
# --- EX-GEN-04 : UTC en base, refus des horodatages naïfs -----------------
with bd.Seance() as s:
    personne = bd.creer_personne(s, "Ada", "Lovelace", genre="feminin")
    s.commit()
    identifiant_ada = personne.uuid

with bd.Seance() as s:
    relue = s.get(Personne, identifiant_ada)
    assert relue.prenom == "Ada" and relue.genre == "feminin"
    # EX-AUTH-21 — capitalisé une fois, à la création.
    p2 = bd.creer_personne(s, "jean-pierre", "de rham")
    s.commit()
    assert (p2.prenom, p2.nom) == ("Jean-Pierre", "de Rham"), (p2.prenom, p2.nom)

# Un horodatage naïf est refusé à l'écriture : rien ne le distinguerait
# ensuite d'une heure locale, et l'écart ne se verrait qu'une fois la durée
# faussée.
with bd.Seance() as s:
    s.add(Journal(action="essai", horodatage=datetime(2026, 9, 5, 20, 0)))
    try:
        s.commit()
    except (StatementError, ValueError) as exc:
        assert "naïf" in str(exc), exc
        s.rollback()
    else:
        raise AssertionError("un horodatage naïf doit être refusé (EX-GEN-04)")

with bd.Seance() as s:
    bd.journaliser(s, "essai_utc")
    s.commit()
    lu = s.scalar(sa.select(Journal).where(Journal.action == "essai_utc"))
    assert lu.horodatage.tzinfo is not None, "l'horodatage relu doit être conscient"
    assert lu.horodatage.utcoffset() == timezone.utc.utcoffset(None)
    assert config.en_heure_locale(lu.horodatage).utcoffset().total_seconds() in (3600, 7200)

print("TOUT PASSE — horodatages conscients, UTC en base, naïfs refusés")

# --------------------------------------------------------------------------- #
# --- EX-IA-26 : une seule chronique par personne --------------------------
premier = test_outils.creer_chronique("Ada", "Lovelace", {"metier": "calcul"}, CODES)
second = test_outils.creer_chronique("ada", "LOVELACE", {"metier": "calcul, corrigé"}, CODES)
assert premier == second, \
    "une deuxième création doit reconduire vers la chronique existante"

# « Reconduit vers », et non « écrase ». Défaut constaté le 20 août : un second
# passage sous le même nom avait effacé sept réponses et cinq complémentaires.
# Les réponses sont la seule chose irremplaçable du projet (EX-GEN-08).
assert "corrigé" not in bd.lire(premier).reponses_json, \
    "ressaisir son nom ne doit RIEN écraser (EX-IA-26, EX-GEN-08)"
assert "calcul" in bd.lire(premier).reponses_json, "les premières réponses tiennent"

# Ni l'étage, ni le quota, ni le lieu ne bougent.
bd.ajouter_bonus(premier, {"talent": "les nombres de Bernoulli"})
assert bd.lire(premier).etage == 2
lieu_initial = bd.lire(premier).lieu
generations = bd.lire(premier).nb_generations
test_outils.creer_chronique("Ada", "Lovelace", {"metier": "encore autre chose"}, CODES)
assert bd.lire(premier).etage == 2, "l'étage ne doit pas se désynchroniser"
assert bd.lire(premier).lieu == lieu_initial, "le lieu ne se rejoue pas (EX-IA-08)"
assert bd.lire(premier).nb_generations == generations, \
    "ressaisir son nom ne consomme aucune génération"
assert "Bernoulli" in bd.lire(premier).reponses_json, \
    "les réponses complémentaires survivent"

# La recherche par nom ne renvoie plus directement une chronique : depuis
# l'étape 2 elle renvoie les PERSONNES qui portent ce nom, et c'est l'écran
# d'identité qui tranche (EX-AUTH-05). `chronique_de(prenom, nom)` faisait un
# `scalar()` qui, sur deux homonymes, en désignait une au hasard.
assert bd.resoudre("  ADA ", "lovelace").unique.uuid == identifiant_ada, \
    "insensible à la casse et aux espaces"
assert bd.chronique_de_personne(identifiant_ada) == premier
assert bd.resoudre("Ada", "Byron").candidates == []
assert bd.resoudre("", "").candidates == []

# Et la contrainte est portée par le schéma, pas seulement par le code.
with bd.Seance() as s:
    s.add(Chronique(personne_uuid=identifiant_ada, lieu="lieu_01",
                    reponses_json="{}"))
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
    else:
        raise AssertionError("deux chroniques pour une personne (EX-IA-26)")

print("TOUT PASSE — une seule chronique par personne, rien n'est écrasé")

# --------------------------------------------------------------------------- #
# --- EX-IA-42 et EX-IA-06 : équilibrage sur le code stable ----------------
assert all(c.startswith("lieu_") for c in CODES), CODES
assert len(CODES) == len(set(CODES)) == 10

for i in range(40):
    test_outils.creer_chronique(f"Equilibre{i}", "Essai", {"metier": "x"}, CODES)

with bd.Seance() as s:
    effectifs = {code: n for code, n in s.execute(
        sa.select(Chronique.lieu, sa.func.count()).group_by(Chronique.lieu))}
assert set(effectifs) <= set(CODES), \
    f"un libellé s'est glissé dans la colonne lieu : {set(effectifs) - set(CODES)}"
assert max(effectifs.values()) - min(effectifs.values()) <= 1, effectifs

# Renommer une région ne doit orpheliner aucune chronique (EX-ADM-22).
ancien = main.LIEUX_PAR_CODE["lieu_07"]["libelle"]
main.LIEUX_PAR_CODE["lieu_07"]["libelle"] = "Table des mariés"
assert main.libelle_lieu("lieu_07") == "Table des mariés"
with bd.Seance() as s:
    survivantes = s.scalar(sa.select(sa.func.count()).select_from(Chronique)
                           .where(Chronique.lieu == "lieu_07"))
assert survivantes > 0, "les chroniques survivent au renommage"
main.LIEUX_PAR_CODE["lieu_07"]["libelle"] = ancien

print(f"TOUT PASSE — répartition {sorted(effectifs.values())} sur codes stables")

# --------------------------------------------------------------------------- #
# --- EX-IA-21 : les compteurs viennent du journal -------------------------
uid = test_outils.creer_chronique("Grace", "Hopper", {"metier": "amiral"}, CODES)
assert (bd.lire(uid).nb_generations, bd.lire(uid).nb_tentatives) == (0, 0)

for _ in range(4):
    bd.enregistrer_echec(uid, "HTTP 529 — overloaded_error")
assert bd.lire(uid).nb_generations == 0, "quatre pannes, aucun crédit débité"
assert bd.lire(uid).nb_tentatives == 4, "les appels tentés sont suivis à part"

bd.enregistrer_portrait(uid, {"nom_fictif": "Uriel", "peuple": "elfe",
                              "portrait": "p", "indice": "i",
                              "fuites_noms": [], "jetons_sortie": 2689})
assert bd.lire(uid).nb_generations == 1
assert bd.lire(uid).nb_tentatives == 5

# La valeur est dérivée : effacer le journal la ramène à zéro, ce qu'aucune
# colonne ne ferait.
with bd.Seance() as s:
    s.execute(sa.delete(Journal).where(Journal.objet_uuid == uid,
                                       Journal.action == Journal.CHRONIQUE_GENEREE))
    s.commit()
assert bd.lire(uid).nb_generations == 0, "le compteur suit le journal, rien d'autre"

# Les réponses survivent à tout : c'est la seule vérité (EX-GEN-08).
assert "amiral" in bd.lire(uid).reponses_json

print("TOUT PASSE — compteurs dérivés du journal, un échec ne débite rien")

# --------------------------------------------------------------------------- #
# --- EX-IA-43 : une seule génération non terminée par chronique -----------
# Les compteurs étant dérivés, deux demandes simultanées liraient la même
# valeur. Un double appui sur « Réécrivez-moi ça », sur une 4G lente, est le
# cas nominal : l'index partiel doit rendre la course impossible.
with bd.Seance() as s:
    s.add(Tache(type="generation_chronique", objet_uuid=uid,
                priorite=Tache.PRIORITE_GENERATION))
    s.commit()

with bd.Seance() as s:
    s.add(Tache(type="generation_chronique", objet_uuid=uid,
                priorite=Tache.PRIORITE_GENERATION))
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
    else:
        raise AssertionError("deux générations en attente pour une chronique "
                             "(EX-IA-43)")

# Une fois la première terminée, une nouvelle est admise : le plafond porte
# sur les tâches vivantes, pas sur l'historique.
with bd.Seance() as s:
    vivante = s.scalar(sa.select(Tache).where(Tache.objet_uuid == uid))
    vivante.etat = "terminee"
    vivante.terminee_le = config.maintenant()
    s.commit()
    s.add(Tache(type="generation_chronique", objet_uuid=uid))
    s.commit()

# Et la contrainte ne concerne que la génération : une conversion d'image et
# une copie peuvent coexister sur le même objet.
with bd.Seance() as s:
    s.add(Tache(type="conversion_image", objet_uuid=uid,
                priorite=Tache.PRIORITE_CONVERSION))
    s.add(Tache(type="copie_stockage_objet", objet_uuid=uid,
                priorite=Tache.PRIORITE_COPIE))
    s.commit()

# EX-ARC-12 — la génération passe avant la conversion : un invité attend
# devant son écran, une photo se traite en silence.
assert Tache.PRIORITE_GENERATION < Tache.PRIORITE_CONVERSION < Tache.PRIORITE_COPIE

print("TOUT PASSE — une seule génération vivante par chronique")

# --------------------------------------------------------------------------- #
# --- Contraintes de valeur ------------------------------------------------
for valeurs, motif in (
    ({"phase": "en_route"}, "phase hors liste"),
    ({"phase": "ouvert", "id": 2}, "seconde ligne d'état de soirée"),
):
    with bd.Seance() as s:
        s.add(modeles.EtatSoiree(**valeurs))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
        else:
            raise AssertionError(motif + " accepté")

with bd.Seance() as s:
    s.add(Personne(prenom="X", nom="Y", genre="indifferent"))
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
    else:
        raise AssertionError("genre hors liste accepté — NULL vaut « au choix "
                             "du modèle », il n'y a pas de troisième valeur")

# --- EX-PRJ-06 : refus des opérations destructives en production ----------
projet = config.projet()
assert projet.type == "preparation", "le projet de développement est en préparation"
projet.refuser_si_production("remise à zéro")   # permis ici

# --- EX-GEN-03 : suppression douce ---------------------------------------
with bd.Seance() as s:
    chronique = s.get(Chronique, uid)
    chronique.supprimee = True
    s.commit()
assert uid not in [c.uuid for c in bd.lister()], "une chronique supprimée sort des listes"
with bd.Seance() as s:
    assert s.get(Chronique, uid) is not None, "la ligne existe toujours (EX-GEN-03)"
# Et la personne peut repartir de zéro, l'index unique étant conditionnel.
nouveau = test_outils.creer_chronique("Grace", "Hopper", {"metier": "amiral, deuxième"}, CODES)
assert nouveau != uid, "une nouvelle chronique est possible après suppression douce"

print("TOUT PASSE — contraintes de valeur, suppression douce, refus production")
