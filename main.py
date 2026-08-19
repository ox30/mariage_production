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
SQLAlchemy. La génération part toujours dans un `threading.Thread` nu.
"""

import json
import os
import secrets
import threading
from contextlib import asynccontextmanager

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import base_donnees as bd
import config
import ia
import noms

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
    yield


app = FastAPI(title="Le Livre des Convoqués", lifespan=cycle_de_vie)
app.mount("/static", StaticFiles(directory=os.path.join(RACINE, "static")), name="static")
gabarits = Jinja2Templates(directory=os.path.join(RACINE, "templates"))
gabarits.env.autoescape = True

# Les lieux sont des objets (libellé, locution, pendant d'ombre) ; la base ne
# stocke que le libellé, l'assignation ne raisonne donc que sur cette liste.
LIBELLES_LIEUX = [l["libelle"] for l in CONFIG["lieux"]]

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

def _lancer_generation(identifiant: str, motif: str | None = None) -> None:
    def travail() -> None:
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
                    "lieu": next((l for l in CONFIG["lieux"]
                                   if l["libelle"] == ligne["lieu"]), ligne["lieu"]),
                    "reponses": json.loads(ligne["reponses_json"]),
                    "noms_interdits": interdits,
                    "noms_fictifs_pris": bd.noms_fictifs_pris(sauf=identifiant),
                    "genre": ligne["genre"],
                    "motif_reprise": motif,
                    "couple": COUPLE,
                },
            )
            bd.enregistrer_portrait(identifiant, portrait)
        except Exception as exc:
            bd.enregistrer_echec(identifiant, f"{type(exc).__name__} — {exc}")

    threading.Thread(target=travail, daemon=True).start()


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
    if donnees.get("suite") == "bonus":
        identifiant = bd.creer(prenom, nom, reponses, LIBELLES_LIEUX,
                               etat="brouillon", genre=genre)
        return RedirectResponse(f"/bonus/{identifiant}/questions", status_code=303)

    identifiant = bd.creer(prenom, nom, reponses, LIBELLES_LIEUX, genre=genre)
    _lancer_generation(identifiant)
    return RedirectResponse(f"/portrait/{identifiant}", status_code=303)


@app.get("/portrait/{identifiant}", response_class=HTMLResponse)
def portrait(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse(
        "portrait.html",
        {"request": request, "p": ligne, "max_generations": MAX_GENERATIONS,
         "nb_bonus_mot": NB_BONUS_MOT, "motifs": CONFIG.get("motifs_reprise", [])},
    )


@app.get("/portrait/{identifiant}/etat", response_class=HTMLResponse)
def etat_portrait(request: Request, identifiant: str):
    """Fragment interrogé par HTMX pendant l'écriture."""
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return gabarits.TemplateResponse(
        "fragment_portrait.html",
        {"request": request, "p": ligne, "max_generations": MAX_GENERATIONS,
         "nb_bonus_mot": NB_BONUS_MOT, "motifs": CONFIG.get("motifs_reprise", [])},
    )


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
    if (ligne["nb_generations"] < MAX_GENERATIONS
            and ligne["nb_tentatives"] < bd.MAX_TENTATIVES):
        _lancer_generation(identifiant, motif=motif)
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
    if ligne["etage"] == 2:
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
            "prenom": ligne["prenom"],
            "nom": ligne["nom"],
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
        if not p["portrait"]:
            continue
        ligne = dict(p)
        # Le souvenir et le vœu sont montrés tels quels : la voix de la
        # personne vaut mieux que sa transposition, une fois qu'on l'a devinée.
        ligne["reponses"] = json.loads(p["reponses_json"])
        ligne["initiales"] = noms.initiales(p["prenom"], p["nom"])
        par_lieu.setdefault(p["lieu"], []).append(ligne)
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
    region = next((l for l in CONFIG["lieux"] if l["libelle"] == ligne["lieu"]), None)
    if region is None:
        return ligne["lieu"]
    reponses = json.loads(ligne["reponses_json"])
    monstre = str(reponses.get("monstre", "")).startswith("Un monstre")
    if monstre and region.get("ombre"):
        return f"{region['libelle']} / {region['ombre']}"
    return region["libelle"]


@app.get("/tableau", response_class=HTMLResponse)
def tableau(request: Request, _: str = Depends(admin)):
    participations = [dict(p) | {"lieu_affiche": _lieu_affiche(p)} for p in bd.lister()]
    jetons_entree = sum(p["jetons_entree"] or 0 for p in participations)
    jetons_sortie = sum(p["jetons_sortie"] or 0 for p in participations)
    durees = [p["duree_s"] for p in participations if p["duree_s"]]
    return gabarits.TemplateResponse(
        "tableau.html",
        {
            "request": request,
            "participations": participations,
            "jetons_entree": jetons_entree,
            "jetons_sortie": jetons_sortie,
            "duree_moyenne": round(sum(durees) / len(durees), 1) if durees else None,
            "duree_max": max(durees) if durees else None,
            "echecs": sum(1 for p in participations if p["etat"] == "echouee"),
            "fuites": sum(1 for p in participations if p["fuites_noms"] not in (None, "[]")),
        },
    )


@app.get("/tableau/export.json")
def export(_: str = Depends(admin)):
    return JSONResponse(
        [
            {
                "uuid": p["uuid"],
                "prenom": p["prenom"],
                "nom": p["nom"],
                "lieu": p["lieu"],
                "etage": p["etage"],
                "reponses": json.loads(p["reponses_json"]),
                "nom_fictif": p["nom_fictif"],
                "peuple": p["peuple"],
                "portrait": p["portrait"],
                "indice": p["indice"],
                "fuites_noms": json.loads(p["fuites_noms"] or "[]"),
                "modele": p["modele"],
                "duree_s": p["duree_s"],
                "jetons": [p["jetons_entree"], p["jetons_sortie"]],
                "nb_generations": p["nb_generations"],
                "nb_tentatives": p["nb_tentatives"],
                "etat": p["etat"],
                "derniere_erreur": p["derniere_erreur"],
            }
            for p in bd.lister()
        ]
    )
