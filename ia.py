"""Appel au modèle et contrôle de la sortie.

Le portrait est un dérivé jetable : les réponses brutes restent la seule
vérité en base. Si cet appel échoue, rien n'est perdu.
"""

import json
import os
import re
import time
import unicodedata

import httpx

URL_API = "https://api.anthropic.com/v1/messages"
MODELE_DEFAUT = "claude-sonnet-5"


class ErreurGeneration(Exception):
    pass


def _normaliser(mot: str) -> str:
    sans_accent = unicodedata.normalize("NFKD", mot.lower())
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", sans_accent)


def verifier_noms(texte: str, noms_interdits: list[str]) -> list[str]:
    """Renvoie la liste des noms réels qui ont fui dans le texte généré.

    On ne corrige pas silencieusement : on signale, et l'humain tranche à la
    relecture. Un remplacement automatique produirait des phrases cassées.

    Seules les occurrences **capitalisées** comptent : en français un nom propre
    porte toujours la majuscule, alors que les prénoms qui sont aussi des mots
    courants — Juste, Pierre, Rose, Olivier — apparaissent en minuscules dans
    leur sens ordinaire. « le nouveau-né tout juste arrivé » n'est pas une
    fuite ; « il croisa Juste » en est une. Le premier mot d'une phrase est
    ignoré : sa majuscule ne prouve rien.
    """
    mots_texte = set()
    for phrase in re.split(r"(?<=[.!?\u2026\u00bb])\s+", texte):
        mots = re.findall(r"\w+", phrase)
        for mot in mots[1:]:
            if mot[:1].isupper():
                mots_texte.add(_normaliser(mot))
    fuites = []
    for nom in noms_interdits:
        # « Jean-Pierre » doit être cherché en entier ET partie par partie :
        # le texte généré peut n'en reprendre qu'une moitié.
        parties = [nom] + re.split(r"[-\s']+", nom)
        for partie in parties:
            n = _normaliser(partie)
            if len(n) >= 3 and n in mots_texte:
                fuites.append(nom)
                break
    return sorted(set(fuites))


def _construire_message(config: dict, participation: dict) -> str:
    """Assemble les réponses en un bloc lisible pour le modèle."""
    couple = participation.get("couple") or {}
    lignes = []
    if couple:
        lignes += [
            "LES MARIÉS (pour ta compréhension seulement, à ne jamais écrire) :",
            f"- la mariée s'appelle {couple.get('mariee')}",
            f"- le marié s'appelle {couple.get('marie')}",
            "Si la personne a mal orthographié l'un de ces prénoms, comprends-le",
            "sans le relever et sans le reproduire.",
            "",
        ]
    motif = participation.get("motif_reprise")
    if motif:
        consigne = next((m["consigne"] for m in config.get("motifs_reprise", [])
                         if m["cle"] == motif), None)
        if consigne:
            lignes += [
                "REPRISE DEMANDÉE PAR LA PERSONNE : " + consigne.strip(),
                "Cette consigne s'ajoute au contrat, elle ne le remplace pas. "
                "Le peuple, le lieu et les règles absolues restent inchangés.",
                "",
            ]

    genre = participation.get("genre")
    if genre in ("masculin", "feminin"):
        lignes += [
            f"GENRE DU PERSONNAGE : {genre}. Le nom fictif, les pronoms et tous "
            "les accords suivent ce genre, sans exception.",
            "",
        ]
    lieu = participation["lieu"]
    if isinstance(lieu, str):
        lieu = {"libelle": lieu, "locution": f"à {lieu}", "ombre": None}
    monstre = str(participation["reponses"].get("monstre", "")).startswith("Un monstre")
    if monstre and lieu.get("ombre"):
        situation = (
            f"RÉGION ASSIGNÉE : {lieu['libelle']}. La créature n'y est pas admise : "
            f"elle se tient {lieu['ombre']}, aux abords, et c'est de là qu'elle "
            "observe la région. Écris la scène depuis ce voisinage."
        )
    else:
        situation = (
            f"RÉGION ASSIGNÉE : {lieu['libelle']}. Écris « {lieu['locution']} » "
            "et non une autre forme : la préposition est imposée."
        )
    lignes += [
        situation,
        "C'est le décor du portrait, pas son sujet. Le personnage y a été",
        "convoqué et ne l'a pas choisi — mais n'ouvre pas le portrait sur cette",
        "convocation : commence par le personnage, son geste ou sa réputation,",
        "et laisse le lieu apparaître en cours de route.",
        "",
        "RÉPONSES DE LA PERSONNE :",
    ]
    reponses = participation["reponses"]
    pour_portrait, pour_indice = [], []
    obligatoires_donnees = 0
    for bloc in ("obligatoires", "bonus"):
        for q in config[bloc]:
            usage = q.get("usage", "portrait")
            # `revelation` : montré tel quel aux mariés, jamais au modèle.
            # `chapitre`  : dort en base jusqu'à l'écriture des chapitres.
            # Une donnée absente ne peut pas être mal employée ; une consigne,
            # si. Elle peut d'ailleurs contenir des prénoms réels.
            ignoree = usage in ("revelation", "chapitre")
            cible = pour_indice if usage == "indice" else pour_portrait
            prealable = q.get("prealable")
            if prealable and reponses.get(prealable["cle"]):
                usage_p = prealable.get("usage", usage)
                if usage_p != "chapitre" and usage_p != "revelation":
                    cible_p = pour_indice if usage_p == "indice" else pour_portrait
                    cible_p.append(
                        f"- {prealable.get('intitule_modele', prealable['question'])}"
                        f" → {reponses[prealable['cle']]}"
                        " (qui figure dans la scène du souvenir ; ne dit rien"
                        " du lien de parenté)"
                    )
            valeur = reponses.get(q["cle"])
            if valeur and not ignoree:
                cible.append(f"- {q['question']} → {valeur}")
                if bloc == "obligatoires" and usage == "portrait":
                    obligatoires_donnees += 1

    lignes += pour_portrait
    if pour_indice:
        lignes += [
            "",
            "RÉSERVÉ À L'INDICE — interdit dans le portrait :",
            *pour_indice,
        ]

    # La règle d'usage dépend du volume reçu : six réponses tiennent toutes en
    # 150 mots, douze non. Les six premières restent obligatoires dans les deux
    # cas — ce sont les ancres les plus fortes.
    bonus_donnees = sum(
        1 for q in config["bonus"]
        if reponses.get(q["cle"]) and q.get("usage", "portrait") == "portrait"
    )
    mots = config.get("mots_max", {})
    plafond = mots.get("avec_complement" if bonus_donnees else "sans_complement",
                       220 if bonus_donnees else 150)
    if bonus_donnees:
        lignes += [
            "",
            f"VOLUME REÇU : {obligatoires_donnees} réponses principales et "
            f"{bonus_donnees} complémentaires, soit davantage d'ancres que la "
            "normale. Exploite-les toutes : chacune est une prise pour deviner.",
            f"LONGUEUR IMPOSÉE : {plafond} mots maximum pour le portrait.",
        ]
    else:
        lignes += [
            "",
            f"VOLUME REÇU : {obligatoires_donnees} réponses, sans complément. "
            "Exploite-les toutes : chacune est une prise pour deviner.",
            f"LONGUEUR IMPOSÉE : {plafond} mots maximum pour le portrait.",
        ]

    lignes += [
        "",
        "NOMS RÉELS STRICTEMENT INTERDITS EN SORTIE :",
        ", ".join(participation["noms_interdits"]) or "(aucun)",
    ]
    deja = participation.get("noms_fictifs_pris") or []
    if deja:
        lignes += [
            "",
            "NOMS FICTIFS DÉJÀ ATTRIBUÉS — n'en reprends aucun, ni le nom entier "
            "ni l'un de ses mots : deux personnages homonymes seraient "
            "indiscernables sur la carte.",
            ", ".join(deja),
        ]
    return "\n".join(lignes)


def generer(config: dict, participation: dict) -> dict:
    """Appelle le modèle et renvoie le portrait validé.

    Trois tentatives, attente croissante — même politique que la file de
    tâches de l'application réelle (EX-ARC-13).
    """
    cle = os.environ.get("ANTHROPIC_API_KEY")
    if not cle:
        raise ErreurGeneration("ANTHROPIC_API_KEY absente de l'environnement")

    modele = os.environ.get("MODELE_IA", MODELE_DEFAUT)
    corps = {
        "model": modele,
        # Le compteur de sortie dépasse largement le texte visible : 1786 jetons
        # pour 144 mots ont été mesurés. La troncature ne vient donc pas de la
        # longueur du portrait et ne se corrige pas en le raccourcissant. Le
        # plafond borne sans facturer : le mettre large ne coûte rien.
        "max_tokens": 8000,
        "system": config["contrat"],
        "messages": [{"role": "user", "content": _construire_message(config, participation)}],
    }
    entetes = {
        "x-api-key": cle,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    derniere_erreur = ""
    for tentative in range(3):
        if tentative:
            time.sleep(2 ** tentative)
        try:
            debut = time.monotonic()
            reponse = httpx.post(URL_API, json=corps, headers=entetes, timeout=60.0)
            duree = time.monotonic() - debut
            if reponse.status_code != 200:
                derniere_erreur = f"HTTP {reponse.status_code} — {reponse.text[:300]}"
                continue
            charge = reponse.json()
        except Exception as exc:  # réseau, timeout, JSON illisible
            derniere_erreur = f"{type(exc).__name__} — {exc}"
            continue

        brut = "".join(
            bloc.get("text", "") for bloc in charge.get("content", []) if bloc.get("type") == "text"
        ).strip()
        brut = re.sub(r"^```(?:json)?|```$", "", brut, flags=re.MULTILINE).strip()

        # Une réponse coupée au plafond n'est pas un JSON invalide : c'est un
        # portrait trop long. Le dire pour ne pas chercher au mauvais endroit.
        if charge.get("stop_reason") == "max_tokens":
            derniere_erreur = (
                "réponse tronquée au plafond de jetons — le modèle a dépassé "
                "les 150 mots demandés"
            )
            continue

        try:
            portrait = json.loads(brut)
        except json.JSONDecodeError:
            derniere_erreur = f"JSON illisible : {brut[:300]}"
            continue

        manquants = [c for c in ("nom_fictif", "peuple", "portrait", "indice") if not portrait.get(c)]
        if manquants:
            derniere_erreur = f"champs manquants : {', '.join(manquants)}"
            continue

        pris = {_normaliser(n) for n in (participation.get("noms_fictifs_pris") or [])}
        mots_pris = {m for n in (participation.get("noms_fictifs_pris") or [])
                     for m in map(_normaliser, n.split()) if len(m) >= 4}
        propose = _normaliser(portrait["nom_fictif"])
        mots_proposes = {m for m in map(_normaliser, portrait["nom_fictif"].split()) if len(m) >= 4}
        if propose in pris or (mots_proposes & mots_pris):
            derniere_erreur = f"nom fictif déjà attribué : {portrait['nom_fictif']}"
            continue

        peuple = _normaliser(portrait["peuple"])
        if peuple not in {_normaliser(p) for p in config["peuples"]}:
            derniere_erreur = f"peuple hors liste : {portrait['peuple']}"
            continue

        usage = charge.get("usage", {})
        portrait["modele"] = modele
        portrait["duree_s"] = round(duree, 1)
        portrait["jetons_entree"] = usage.get("input_tokens")
        portrait["jetons_sortie"] = usage.get("output_tokens")
        portrait["fuites_noms"] = verifier_noms(
            portrait["portrait"] + " " + portrait["indice"], participation["noms_interdits"]
        )
        return portrait

    raise ErreurGeneration(derniere_erreur or "échec inconnu")
