"""« Le Livre des Convoqués » — application événementielle du 5 septembre 2026.

Le soir de la fête, une centaine d'invités répondent à un questionnaire depuis
leur téléphone ; une IA transpose chacun en personnage de la Terre du Milieu.
Le montage du recueil — carte, chapitres, épilogue — se fait après l'événement.
Le 5 septembre, l'application collecte, rien d'autre.

Le parcours invité, le questionnaire, le prompt, l'assignation des lieux et le
plafond de trois réécritures viennent du banc d'essai, éprouvés contre l'API
réelle les 16 et 17 août.

État — étape 1 du socle. Manquent encore : mot de passe unique, import Excel,
photo, Gardien des chroniques perdues, formulaire des mariés, phases de soirée,
administration, réclamations, kiosque, sauvegardes, file de tâches persistée,
SQLAlchemy, et la génération passe par la file de tâches persistée.
"""

import json
import os
from pathlib import Path
import secrets
from contextlib import asynccontextmanager

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import base_donnees as bd
import config
import depot_objet
import ia
import instantane
import noms
import taches

RACINE = os.path.dirname(os.path.abspath(__file__))
MAX_GENERATIONS = 3

# Prénoms des mariés : en variables d'environnement, jamais dans le dépôt, pour
# que l'outil serve à un autre mariage sans toucher au code ni à la config.
COUPLE = {
    "mariee": os.environ.get("PRENOM_MARIEE", "la mariée"),
    "marie": os.environ.get("PRENOM_MARIE", "le marié"),
}


def _substituer(valeur):
    """Remplace {mariee} et {marie} partout dans la configuration chargée.

    Remplacement explicite et non `str.format` : le contrat de style contient
    des accolades JSON que format interpréterait comme des champs.
    """
    if isinstance(valeur, str):
        for cle, prenom in COUPLE.items():
            valeur = valeur.replace("{" + cle + "}", prenom)
        return valeur
    if isinstance(valeur, list):
        return [_substituer(v) for v in valeur]
    if isinstance(valeur, dict):
        return {c: _substituer(v) for c, v in valeur.items()}
    return valeur


# EX-PRJ-12 — `questions.yaml` vit dans le dossier de projet, sur le volume, et
# non dans le dépôt : c'est le seul moyen de corriger un libellé le 4 septembre
# au soir sans redéployer. Une seule lecture, là où il y en avait deux.
CONFIG = _substituer(
    yaml.safe_load(config.projet().chemin_questions.read_text(encoding="utf-8"))
)

MOTIFS_REPRISE = {m["cle"] for m in CONFIG.get("motifs_reprise", [])}

@asynccontextmanager
async def cycle_de_vie(_: FastAPI):
    # Une ligne par démarrage, dont l'empreinte de questions.yaml : c'est la
    # seule chose qui aurait révélé la configuration périmée du 17 août.
    print(config.resume_demarrage(), flush=True)
    bd.initialiser()
    fils = taches.demarrer()
    print(f"worker          : {fils} fil(s) démarré(s), limite courante "
          f"{taches.fils_actifs()} — réglable dans config.yaml sans "
          f"redéployer (EX-ARC-20)", flush=True)
    # EX-SAU-21 — une destination muette doit se signaler au démarrage, pas à
    # minuit. La sonde écrit puis relit un objet d'essai sur chaque dépôt.
    print(depot_objet.resume_sonde(), flush=True)
    if instantane.demarrer():
        print(f"instantanés     : toutes les {int(instantane.PERIODE_S)} s, "
              f"hors file de tâches (EX-SAU-13, EX-SAU-18)", flush=True)
    yield
    instantane.arreter()
    taches.arreter()


app = FastAPI(title="Le Livre des Convoqués", lifespan=cycle_de_vie)
app.mount("/static", StaticFiles(directory=os.path.join(RACINE, "static")), name="static")
gabarits = Jinja2Templates(directory=os.path.join(RACINE, "templates"))
gabarits.env.autoescape = True

# Les lieux sont des objets (libellé, locution, pendant d'ombre) ; la base ne
# stocke que le libellé, l'assignation ne raisonne donc que sur cette liste.
# EX-IA-42 — l'assignation et le stockage portent sur le code stable ; le
# libellé n'est qu'un paramètre d'affichage, éditable en pleine soirée
# (EX-ADM-22) sans orpheliner aucune chronique déjà produite.
for _lieu in CONFIG["lieux"]:
    if not _lieu.get("code"):
        raise RuntimeError(
            "questions.yaml : chaque région doit porter un `code` stable "
            "(lieu_01…lieu_10) à côté du libellé — EX-IA-42. Le fichier du "
            "dossier de projet est vraisemblablement antérieur : le remplacer "
            "sur le volume, l'empreinte au démarrage le confirmera.")

CODES_LIEUX = [l["code"] for l in CONFIG["lieux"]]
LIEUX_PAR_CODE = {l["code"]: l for l in CONFIG["lieux"]}


def libelle_lieu(code: str) -> str:
    """Le libellé d'affichage d'un code de région."""
    lieu = LIEUX_PAR_CODE.get(code)
    return lieu["libelle"] if lieu else code


gabarits.env.globals["libelle_lieu"] = libelle_lieu

# Sans marqueur de version, un navigateur qui a déjà chargé la feuille de style
# la réutilise : une correction d'affichage faite à 22 h resterait invisible
# pour tous ceux qui ont ouvert la page plus tôt — c'est-à-dire pour tout le
# monde. L'empreinte change avec le fichier, donc l'adresse aussi.
# EX-IA-45 — sous quelle version du questionnaire ce portrait a-t-il été
# écrit ? Le fichier évolue jusqu'au 4 septembre au soir (EX-PLA-06) : sans
# cette empreinte, le cheminement d'un portrait n'est plus reconstituable.
EMPREINTE_QUESTIONS = config.empreinte(config.projet().chemin_questions)

gabarits.env.globals["empreinte_style"] = config.empreinte(
    Path(RACINE) / "static" / "style.css")

# L'étage se déduit des réponses présentes (EX-QUE-11) ; `base_donnees` n'a pas
# à relire questions.yaml pour savoir lesquelles relèvent du second étage.
bd.CLES_SECOND_ETAGE = {q["cle"] for q in CONFIG["bonus"]}

# Les libellés annonçant « N questions de plus » sont dérivés de la
# configuration : déplacer une question d'un étage à l'autre ne doit jamais
# obliger à corriger un texte à la main.
NB_BONUS = len(CONFIG["bonus"])
NB_BONUS_MOT = {1: "une", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq",
                6: "six", 7: "sept", 8: "huit"}.get(NB_BONUS, str(NB_BONUS))

securite = HTTPBasic()


def admin(identifiants: HTTPBasicCredentials = Depends(securite)) -> str:
    attendu = os.environ.get("MOT_DE_PASSE_ADMIN", "")
    if not attendu or not secrets.compare_digest(identifiants.password, attendu):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return identifiants.username


# --------------------------------------------------------------------------- #
# Génération, hors du fil de la requête : l'invité n'attend jamais l'API pour
# que sa contribution existe en base.
# --------------------------------------------------------------------------- #

# Le motif de reprise ne survit pas à la mise en file : il n'a de sens que
# pour la génération qu'il accompagne. Conservé en mémoire le temps que le
# worker prenne la tâche — le perdre au redémarrage ne coûte qu'un portrait
# réécrit sans indication, jamais une réponse.
_motifs_en_attente: dict[str, str] = {}


def _generer_chronique(identifiant: str) -> None:
    """Traitant de la file pour une chronique (EX-ARC-14).

    Traduit les exceptions du client d'API en décisions de la file. Seul le
    429 déclenche la barrière globale : il est propre au compte, alors qu'un
    529 est une saturation du fournisseur qui se traite tâche par tâche
    (EX-IA-22, EX-ARC-21).
    """
    ligne = bd.lire(identifiant)
    if ligne is None:
        return
    bd.marquer_en_cours(identifiant)
    interdits = [m for m in bd.tous_les_prenoms() if len(m) >= 3]
    # Les prénoms des mariés servent à comprendre les réponses, jamais à
    # être écrits : ils sont donc aussi interdits en sortie.
    interdits += [v for v in COUPLE.values() if len(v) >= 3]
    try:
        portrait = ia.generer(
            CONFIG,
            {
                "lieu": LIEUX_PAR_CODE.get(ligne.lieu, ligne.lieu),
                "reponses": json.loads(ligne.reponses_json),
                "noms_interdits": interdits,
                "noms_fictifs_pris": bd.noms_fictifs_pris(sauf=identifiant),
                "genre": ligne.genre,
                "motif_reprise": _motifs_en_attente.pop(identifiant, None),
                "couple": COUPLE,
            },
        )
    except ia.ErreurGeneration as exc:
        exc.trace["empreinte_config"] = EMPREINTE_QUESTIONS
        bd.enregistrer_echec(identifiant, f"{exc.categorie} — {exc}",
                             trace=exc.trace)
        if not exc.temporaire:
            raise taches.EchecDefinitif(f"{exc.categorie} — {exc}") from exc
        raise taches.EchecTemporaire(
            f"{exc.categorie} — {exc}",
            reprendre_apres_s=exc.reprendre_apres_s,
            suspendre_tout_s=(exc.reprendre_apres_s or 30.0)
            if exc.categorie == "debit" else None,
        ) from exc

    portrait["empreinte_config"] = EMPREINTE_QUESTIONS
    bd.enregistrer_portrait(identifiant, portrait)


taches.enregistrer_traitant("generation_chronique", _generer_chronique)


def _lancer_generation(identifiant: str, motif: str | None = None) -> None:
    """Met la génération en file. EX-IA-43 refuse le doublon d'elle-même.

    Plus de vérification préalable de l'état : entre le contrôle et l'écriture,
    un double appui sur « Réécrivez-moi ça » avait tout le temps de passer.
    L'index unique partiel rend la course impossible au lieu de la rendre
    improbable.
    """
    if motif:
        _motifs_en_attente[identifiant] = motif
    if taches.mettre_en_file("generation_chronique", identifiant) is None:
        # Une génération est déjà en attente ou en cours pour cette chronique.
        _motifs_en_attente.pop(identifiant, None)


def _reponses_du_formulaire(donnees: dict, bloc: str) -> dict:
    reponses = {}
    for question in CONFIG[bloc]:
        prealable = question.get("prealable")
        if prealable:
            valeur = (donnees.get(prealable["cle"]) or "").strip()
            if valeur:
                reponses[prealable["cle"]] = valeur[:60]
        valeur = (donnees.get(question["cle"]) or "").strip()
        if valeur:
            limite = question.get("limite", 200)
            reponses[question["cle"]] = valeur[:limite]
    return reponses


# --------------------------------------------------------------------------- #
# Parcours invité
# --------------------------------------------------------------------------- #

@app.get("/", response_class=HTMLResponse)
def accueil(request: Request):
    return gabarits.TemplateResponse("accueil.html", {"request": request})


@app.post("/questionnaire", response_class=HTMLResponse)
def questionnaire(request: Request, prenom: str = Form(...), nom: str = Form(...),
                  genre: str = Form("")):
    # EX-IA-26 — le nom est confronté aux chroniques existantes DÈS SA SAISIE,
    # et non à la validation des réponses. Laisser quelqu'un répondre à sept
    # questions pour lui annoncer ensuite qu'il en avait déjà donné sept
    # serait la plus mauvaise façon de faire respecter la règle.
    deja = bd.chronique_de(prenom, nom)
    if deja:
        return RedirectResponse(f"/portrait/{deja}", status_code=303)

    return gabarits.TemplateResponse(
        "questionnaire.html",
        {
            "request": request,
            "prenom": prenom.strip()[:40],
            "nom": nom.strip()[:40],
            "genre": genre if genre in ("masculin", "feminin") else "",
            "questions": CONFIG["obligatoires"],
            "action": "/valider",
            "titre": "Six questions",
            "bifurcation": True,
            "nb_bonus_mot": NB_BONUS_MOT,
            "facultatif": False,
        },
    )


@app.post("/valider")
async def valider(request: Request):
    donnees = dict(await request.form())
    prenom = (donnees.get("prenom") or "").strip()[:40]
    nom = (donnees.get("nom") or "").strip()[:40]
    if not prenom or not nom:
        return RedirectResponse("/", status_code=303)
    genre = (donnees.get("genre") or "").strip()
    genre = genre if genre in ("masculin", "feminin") else None
    reponses = _reponses_du_formulaire(donnees, "obligatoires")

    # Le choix se fait avant la génération : celui qui veut en dire plus n'attend
    # pas deux fois, et on ne lui demande pas de rouvrir un cadeau déjà ouvert.
    # Deuxième barrage : le formulaire de /valider peut être posté sans passer
    # par /questionnaire. Sans lui, la porte dérobée resterait ouverte.
    deja = bd.chronique_de(prenom, nom)
    if deja:
        return RedirectResponse(f"/portrait/{deja}", status_code=303)

    if donnees.get("suite") == "bonus":
        identifiant = bd.creer(prenom, nom, reponses, CODES_LIEUX,
                               etat="brouillon", genre=genre)
        return RedirectResponse(f"/bonus/{identifiant}/questions", status_code=303)

    identifiant = bd.creer(prenom, nom, reponses, CODES_LIEUX, genre=genre)
    _lancer_generation(identifiant)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


def _contexte_portrait(request: Request, ligne) -> dict:
    """Contexte commun à la page et au fragment interrogé par HTMX.

    EX-IA-25 — la file est visible : position et ordre de grandeur, jamais un
    renvoi. EX-IA-32 — l'attente affichée est le temps réellement écoulé
    depuis la validation, file et tentatives échouées comprises, et non la
    durée du seul appel réussi.
    """
    contexte = {"request": request, "p": ligne,
                "max_generations": MAX_GENERATIONS,
                "nb_bonus_mot": NB_BONUS_MOT,
                "motifs": CONFIG.get("motifs_reprise", [])}
    if ligne.etat in ("en_attente", "en_cours"):
        contexte["position"] = taches.position(ligne.uuid)
        contexte["attente_s"] = taches.attente_estimee_s(ligne.uuid)
        contexte["ecoule_s"] = taches.secondes_depuis_mise_en_file(ligne.uuid)
    return contexte


@app.get("/portrait/{identifiant}", response_class=HTMLResponse)
def portrait(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse("portrait.html",
                                     _contexte_portrait(request, ligne))


@app.get("/portrait/{identifiant}/etat", response_class=HTMLResponse)
def etat_portrait(request: Request, identifiant: str):
    """Fragment interrogé par HTMX pendant l'écriture."""
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse("fragment_portrait.html",
                                     _contexte_portrait(request, ligne))


@app.post("/portrait/{identifiant}/regenerer")
async def regenerer(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    # Liste fermée : aucun texte libre ne part vers le modèle. Un invité
    # pourrait sinon se choisir un peuple ou un lieu et ruiner l'équilibrage.
    motif = (dict(await request.form()).get("motif") or "").strip()
    motif = motif if motif in MOTIFS_REPRISE else None
    # Un échec ne débite rien : on autorise la relance tant que le quota de
    # portraits obtenus n'est pas atteint, avec un garde-fou technique contre
    # la boucle infinie d'appels payants.
    if (ligne.nb_generations < MAX_GENERATIONS
            and ligne.nb_tentatives < bd.MAX_TENTATIVES):
        _lancer_generation(identifiant, motif=motif)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


@app.get("/portrait/{identifiant}/reprendre", response_class=HTMLResponse)
def reprendre(request: Request, identifiant: str):
    """EX-IA-05 — reprendre son questionnaire après lecture du portrait.

    Les questions montrées sont **celles déjà données** : les sept du premier
    étage, plus les cinq du second si l'invité les a fournies. Jamais moins,
    puisque l'étage ne redescend pas. Celui qui n'a fait qu'un étage se voit
    proposer le second ailleurs, sur l'écran du portrait, et non ici — mêler
    « corriger ce que j'ai dit » et « en dire plus » ferait deux gestes d'un
    seul bouton.

    L'écran s'ouvre sur un sommaire d'où l'on saute directement à la question
    qu'on veut corriger : douze écrans à traverser pour changer la huitième
    réponse serait une façon polie de dissuader les gens de corriger.
    """
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    # Reprendre sans pouvoir régénérer n'aurait pas de sens : le portrait
    # resterait celui des anciennes réponses.
    if ligne.nb_generations >= MAX_GENERATIONS:
        return RedirectResponse(f"/portrait/{identifiant}", status_code=303)

    questions = list(CONFIG["obligatoires"])
    if ligne.etage == 2:
        questions += list(CONFIG["bonus"])
    return gabarits.TemplateResponse(
        "questionnaire.html",
        {
            "request": request,
            "prenom": ligne.prenom,
            "nom": ligne.nom,
            "genre": ligne.genre or "",
            "questions": questions,
            "reponses": json.loads(ligne.reponses_json),
            "action": f"/portrait/{identifiant}/reprendre",
            "titre": "Reprendre mes réponses",
            "bifurcation": False,
            "nb_bonus_mot": NB_BONUS_MOT,
            "facultatif": False,
            "reprise": True,
            "retour_vers": f"/portrait/{identifiant}",
            "restantes": MAX_GENERATIONS - ligne.nb_generations,
        },
    )


@app.post("/portrait/{identifiant}/reprendre")
async def enregistrer_reprise(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    donnees = dict(await request.form())
    reponses = _reponses_du_formulaire(donnees, "obligatoires")
    if ligne.etage == 2:
        reponses |= _reponses_du_formulaire(donnees, "bonus")
    bd.reprendre_reponses(identifiant, reponses)
    # EX-IA-04 — modifier ses réponses puis régénérer consomme la même unité
    # que régénérer sans rien changer.
    if (ligne.nb_generations < MAX_GENERATIONS
            and ligne.nb_tentatives < bd.MAX_TENTATIVES):
        _lancer_generation(identifiant)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


@app.post("/portrait/{identifiant}/valider")
def valider_portrait(identifiant: str):
    bd.valider(identifiant)
    return RedirectResponse(f"/bonus/{identifiant}", status_code=303)


@app.get("/bonus/{identifiant}", response_class=HTMLResponse)
def proposer_bonus(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    if ligne.etage == 2:
        return RedirectResponse("/fin", status_code=303)
    return gabarits.TemplateResponse(
        "bonus_intro.html",
        {"request": request, "p": ligne, "nb_bonus_mot": NB_BONUS_MOT}
    )


@app.get("/bonus/{identifiant}/questions", response_class=HTMLResponse)
def questions_bonus(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse(
        "questionnaire.html",
        {
            "request": request,
            "prenom": ligne.prenom,
            "nom": ligne.nom,
            "questions": CONFIG["bonus"],
            "action": f"/bonus/{identifiant}",
            "titre": f"{NB_BONUS_MOT.capitalize()} de plus",
            "bifurcation": False,
            "nb_bonus_mot": NB_BONUS_MOT,
            "facultatif": True,
        },
    )


@app.post("/bonus/{identifiant}")
async def enregistrer_bonus(request: Request, identifiant: str):
    donnees = dict(await request.form())
    passe = donnees.get("suite") == "sortie"
    reponses = {} if passe else _reponses_du_formulaire(donnees, "bonus")
    bd.ajouter_bonus(identifiant, reponses)
    _lancer_generation(identifiant)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


@app.get("/fin", response_class=HTMLResponse)
def fin(request: Request):
    return gabarits.TemplateResponse("fin.html", {"request": request})


# --------------------------------------------------------------------------- #
# Pages d'administration provisoires — reprises du banc d'essai.
# Remplacées à l'étape 4 par l'écran de relecture (EX-ADM-19) et le tableau
# de bord complet (EX-ADM-18).
# --------------------------------------------------------------------------- #

@app.get("/deviner", response_class=HTMLResponse)
def deviner(request: Request, _: str = Depends(admin)):
    """La page à montrer à quelqu'un qui connaît les participants."""
    par_lieu: dict[str, list] = {}
    for p in bd.lister():
        if not p.portrait:
            continue
        # Le souvenir et le vœu sont montrés tels quels : la voix de la
        # personne vaut mieux que sa transposition, une fois qu'on l'a devinée.
        p.reponses = json.loads(p.reponses_json)
        p.initiales = noms.initiales(p.prenom, p.nom)
        par_lieu.setdefault(libelle_lieu(p.lieu), []).append(p)
    total = sum(len(v) for v in par_lieu.values())
    return gabarits.TemplateResponse(
        "deviner.html", {"request": request, "par_lieu": par_lieu, "total": total}
    )


def _lieu_affiche(ligne) -> str:
    """« Minas Tirith / les ruines d'Osgiliath » pour une créature.

    La région reste unique — c'est elle qui découpe les chapitres. Le pendant
    d'ombre n'est qu'un décor de texte, mais l'administrateur doit savoir
    lequel des deux a servi.
    """
    region = LIEUX_PAR_CODE.get(ligne.lieu)
    if region is None:
        return ligne.lieu
    reponses = json.loads(ligne.reponses_json)
    monstre = str(reponses.get("monstre", "")).startswith("Un monstre")
    if monstre and region.get("ombre"):
        return f"{region['libelle']} / {region['ombre']}"
    return region["libelle"]


@app.get("/tableau", response_class=HTMLResponse)
def tableau(request: Request, _: str = Depends(admin)):
    participations = bd.lister()
    for p in participations:
        p.lieu_affiche = _lieu_affiche(p)
    jetons_entree = sum(p.jetons_entree or 0 for p in participations)
    jetons_sortie = sum(p.jetons_sortie or 0 for p in participations)
    durees = [p.duree_s for p in participations if p.duree_s]
    return gabarits.TemplateResponse(
        "tableau.html",
        {
            "request": request,
            "participations": participations,
            "jetons_entree": jetons_entree,
            "jetons_sortie": jetons_sortie,
            "duree_moyenne": round(sum(durees) / len(durees), 1) if durees else None,
            "duree_max": max(durees) if durees else None,
            "echecs": sum(1 for p in participations if p.etat == "echouee"),
            "fuites": sum(1 for p in participations if p.fuites_noms),
        },
    )


@app.get("/tableau/export.json")
def export(_: str = Depends(admin)):
    return JSONResponse(
        [
            {
                "uuid": p.uuid,
                "prenom": p.prenom,
                "nom": p.nom,
                # Le code fait foi ; le libellé est joint pour la relecture.
                "lieu": p.lieu,
                "lieu_libelle": libelle_lieu(p.lieu),
                "etage": p.etage,
                "reponses": json.loads(p.reponses_json),
                "nom_fictif": p.nom_fictif,
                "peuple": p.peuple,
                "portrait": p.portrait,
                "indice": p.indice,
                "fuites_noms": p.fuites_noms,
                "modele": p.modele,
                "duree_s": p.duree_s,
                "jetons": [p.jetons_entree, p.jetons_sortie],
                "nb_generations": p.nb_generations,
                "nb_tentatives": p.nb_tentatives,
                "etat": p.etat,
                "derniere_erreur": p.derniere_erreur,
            }
            for p in bd.lister()
        ]
    )
