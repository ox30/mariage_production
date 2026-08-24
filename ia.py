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
    """Échec d'une tentative de génération.

    Porte la **nature** de l'échec, pour que le worker décide seul s'il faut
    réessayer et quand (EX-ARC-13). Le client d'API ne boucle pas : trois
    niveaux de reprise composés produiraient jusqu'à trente appels facturés là
    où trois sont prévus.
    """

    temporaire = False
    categorie = "definitive"

    def __init__(self, message: str, *, reprendre_apres_s: float | None = None,
                 trace: dict | None = None):
        super().__init__(message)
        # Délai lu dans l'en-tête `retry-after`, que le worker posera dans
        # `tache.reprendre_apres`. Une attente en puissances de deux l'ignore
        # par construction (EX-IA-19).
        self.reprendre_apres_s = reprendre_apres_s
        # EX-IA-45 — ce qui a été envoyé et reçu, même en cas d'échec.
        self.trace = trace or {}


class ErreurTemporaire(ErreurGeneration):
    """À réessayer : rien n'indique que la même demande échouera toujours."""

    temporaire = True
    categorie = "temporaire"


class ErreurDebit(ErreurTemporaire):
    """429 — limitation de débit, **propre au compte** (EX-IA-22).

    Seule celle-ci justifie d'espacer les validations ou de monter de palier.
    """

    categorie = "debit"


class ErreurSaturation(ErreurTemporaire):
    """529 — surcharge du fournisseur, indépendante du palier (EX-IA-22)."""

    categorie = "saturation"


class ErreurReseau(ErreurTemporaire):
    """Délai dépassé, connexion coupée, réponse illisible au niveau transport."""

    categorie = "reseau"


class ErreurReponse(ErreurTemporaire):
    """La réponse est arrivée mais ne convient pas.

    JSON illisible, champ manquant, peuple hors liste, texte tronqué au
    plafond. Réessayable : le modèle varie d'un appel à l'autre.
    """

    categorie = "reponse"


class ErreurDefinitive(ErreurGeneration):
    """Réessayer ne servirait à rien : clé absente ou refusée, requête invalide.

    Le worker passe directement l'objet en `echouee` sans consommer ses trois
    tentatives sur un mur.
    """

    categorie = "definitive"


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


def _delai_retry_after(reponse) -> float | None:
    """Lit l'en-tête `retry-after`, en secondes ou en date HTTP.

    C'est la seule information qui dise **quand** réessayer sans aggraver la
    limitation. Une attente en puissances de deux l'ignore par construction
    (EX-IA-19, EX-ARC-13).
    """
    brut = reponse.headers.get("retry-after")
    if not brut:
        return None
    try:
        return max(0.0, float(brut.strip()))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        cible = parsedate_to_datetime(brut)
        if cible.tzinfo is None:
            cible = cible.replace(tzinfo=timezone.utc)
        return max(0.0, (cible - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def generer(config: dict, participation: dict) -> dict:
    """Appelle le modèle **une fois** et renvoie le portrait validé.

    **Une tentative, jamais plus** (EX-ARC-13, précisé v3.13). Le réessai
    appartient au worker et à lui seul : une boucle interne composée avec
    celle de la file produirait jusqu'à trente appels facturés là où trois
    sont prévus, et ne saurait pas honorer l'en-tête `retry-after` d'un 429.

    Lève une sous-classe d'`ErreurGeneration` portant la nature de l'échec —
    `ErreurDebit`, `ErreurSaturation`, `ErreurReseau`, `ErreurReponse`,
    `ErreurDefinitive` — le délai éventuel, et la trace de ce qui a été
    envoyé et reçu (EX-IA-45). Le worker décide.
    """
    cle = os.environ.get("ANTHROPIC_API_KEY")
    if not cle:
        raise ErreurDefinitive("ANTHROPIC_API_KEY absente de l'environnement")

    modele = os.environ.get("MODELE_IA", MODELE_DEFAUT)
    invite = _construire_message(config, participation)
    corps = {
        "model": modele,
        # Le compteur de sortie dépasse largement le texte visible : 4 836
        # jetons pour 217 mots ont été mesurés en production. La troncature ne
        # vient donc pas de la longueur du portrait et ne se corrige pas en le
        # raccourcissant. Le plafond borne sans facturer : le mettre large ne
        # coûte rien.
        "max_tokens": 8000,
        "system": config["contrat"],
        "messages": [{"role": "user", "content": invite}],
    }
    entetes = {
        "x-api-key": cle,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # EX-IA-45 — ce qui a été envoyé et reçu, consigné même en cas d'échec.
    # Le contrat système n'y figure pas : il vient de `questions.yaml`, dont
    # l'empreinte est jointe par l'appelant. Le recopier cent trente fois
    # n'apprendrait rien de plus.
    trace = {"invite": invite, "modele": modele}

    debut = time.monotonic()
    try:
        reponse = httpx.post(URL_API, json=corps, headers=entetes, timeout=60.0)
    except Exception as exc:  # réseau, délai dépassé
        trace["duree_s"] = round(time.monotonic() - debut, 1)
        raise ErreurReseau(f"{type(exc).__name__} — {exc}", trace=trace) from exc

    duree = time.monotonic() - debut
    trace["duree_s"] = round(duree, 1)
    trace["code_http"] = reponse.status_code

    if reponse.status_code != 200:
        detail = f"HTTP {reponse.status_code} — {reponse.text[:300]}"
        trace["reponse_brute"] = reponse.text[:2000]
        # EX-IA-22 — 429 et 529 se réessaient tous deux, mais seul le premier
        # est propre au compte et justifie d'espacer les validations.
        if reponse.status_code == 429:
            raise ErreurDebit(detail, reprendre_apres_s=_delai_retry_after(reponse),
                              trace=trace)
        if reponse.status_code == 529:
            raise ErreurSaturation(detail, reprendre_apres_s=_delai_retry_after(reponse),
                                   trace=trace)
        if reponse.status_code in (408, 500, 502, 503, 504):
            raise ErreurReseau(detail, trace=trace)
        # 400, 401, 403 : la même demande échouera identiquement.
        raise ErreurDefinitive(detail, trace=trace)

    try:
        charge = reponse.json()
    except Exception as exc:
        trace["reponse_brute"] = reponse.text[:2000]
        raise ErreurReseau(f"réponse illisible : {exc}", trace=trace) from exc

    usage = charge.get("usage", {})
    trace["jetons_entree"] = usage.get("input_tokens")
    trace["jetons_sortie"] = usage.get("output_tokens")

    brut = "".join(
        bloc.get("text", "") for bloc in charge.get("content", []) if bloc.get("type") == "text"
    ).strip()
    brut = re.sub(r"^```(?:json)?|```$", "", brut, flags=re.MULTILINE).strip()
    trace["reponse_brute"] = brut[:4000]

    # Une réponse coupée au plafond n'est pas un JSON invalide : c'est un
    # portrait trop long. Le dire pour ne pas chercher au mauvais endroit.
    if charge.get("stop_reason") == "max_tokens":
        raise ErreurReponse(
            "réponse tronquée au plafond de jetons — le modèle a dépassé "
            "les 150 mots demandés", trace=trace)

    try:
        portrait = json.loads(brut)
    except json.JSONDecodeError:
        raise ErreurReponse(f"JSON illisible : {brut[:300]}", trace=trace) from None

    manquants = [c for c in ("nom_fictif", "peuple", "portrait", "indice") if not portrait.get(c)]
    if manquants:
        raise ErreurReponse(f"champs manquants : {', '.join(manquants)}", trace=trace)

    peuple = _normaliser(portrait["peuple"])
    if peuple not in {_normaliser(p) for p in config["peuples"]}:
        raise ErreurReponse(f"peuple hors liste : {portrait['peuple']}", trace=trace)

    # EX-IA-31, modifié v3.15 — un nom fictif en double n'est plus REJETÉ.
    # La règle du rejet, validée sur huit chroniques, portait sur tout mot de
    # quatre lettres partagé : à cent chroniques ce sont deux cents mots
    # interdits dans un espace onomastique restreint, et chaque rejet gaspille
    # un appel déjà payé en occupant un fil trente secondes — précisément
    # quand la file est la plus chargée. La liste reste transmise au modèle
    # comme suggestion ; le doublon est détecté côté serveur et signalé à
    # l'écran de relecture (EX-IA-44), comme le fait déjà EX-IA-13 pour les
    # noms réels : « il signale, il ne corrige pas ».

    portrait["modele"] = modele
    portrait["duree_s"] = round(duree, 1)
    portrait["jetons_entree"] = usage.get("input_tokens")
    portrait["jetons_sortie"] = usage.get("output_tokens")
    portrait["fuites_noms"] = verifier_noms(
        portrait["portrait"] + " " + portrait["indice"], participation["noms_interdits"]
    )
    portrait["trace"] = trace
    return portrait
