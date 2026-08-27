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
import pathlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import yaml
from sqlalchemy import select
from fastapi import (Depends, FastAPI, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import acces
import base_donnees as bd
import config
import debit
import depot_objet
import ia
import identite
import import_invites
import instantane
import modeles
import noms
import panne
import photos
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
# Deux points de capture, parce qu'une ErreurConfiguration peut sortir ici, à
# l'import — pointeur absent, dossier inexistant, questions.yaml manquant — ou
# plus tard au cycle de vie. Dans les deux cas on écrit la consigne en clair
# avant de laisser l'exception partir : le processus doit bien mourir, mais
# l'opérateur doit pouvoir lire pourquoi sans dérouler une trace.
try:
    CONFIG = _substituer(
        yaml.safe_load(config.projet().chemin_questions.read_text(encoding="utf-8"))
    )
except config.ErreurConfiguration as _exc:
    print(config.bloc_erreur(_exc), flush=True)
    raise

MOTIFS_REPRISE = {m["cle"] for m in CONFIG.get("motifs_reprise", [])}

# Posé quand la configuration est refusée au cycle de vie. Le service démarre
# alors mais ne sert RIEN : ni migration, ni worker, ni instantané, ni route du
# parcours. Mourir en boucle rendrait le volume inatteignable, donc le fichier
# fautif incorrigible — c'est le blocage circulaire du 25 août.
PANNE: Exception | None = None


@asynccontextmanager
async def cycle_de_vie(_: FastAPI):
    global PANNE
    # Une ligne par démarrage, dont l'empreinte de questions.yaml : c'est la
    # seule chose qui aurait révélé la configuration périmée du 17 août.
    print(config.resume_demarrage(), flush=True)
    # EX-AUTH-18 — sans mot de passe, la soirée est ouverte à tous ou fermée à
    # tous. Le refus est ici et non à la première requête : découvrir à 21 h
    # que le `config.yaml` déposé n'en portait pas serait le pire moment.
    try:
        acces.verifier_au_demarrage()
    except config.ErreurConfiguration as exc:
        PANNE = exc
        print(config.bloc_erreur(exc), flush=True)
        # Aucune migration : appliquer un schéma à une base dont on ne sait
        # plus si elle est au bon endroit serait pire que l'arrêt.
        yield
        return
    PANNE = None
    print(acces.resume(), flush=True)
    bd.initialiser()
    # EX-ADM-22 — questions.yaml porte les valeurs par défaut, la base fait
    # autorité ensuite. Le semis n'écrase JAMAIS un libellé déjà modifié :
    # sans cela, chaque redémarrage effacerait le travail de la soirée.
    # EX-PRJ-10 — la table de test reste ACTIVE en production : le test de
    # fumée du jour J se fait sur la vraie base, avec la vraie clé et le vrai
    # modèle. Une répétition ailleurs n'éprouverait pas ce qui va servir.
    testeurs = bd.semer_table_test(
        actif=bool(config.parametre("table_test.active", True)),
        combien=int(config.parametre("table_test.utilisateurs",
                                     bd.NB_UTILISATEURS_TEST)))
    if testeurs:
        print(f"table de test   : {testeurs} compte(s) test_01… créé(s) "
              "— invisibles dans les listes et les totaux (EX-TST-04)",
              flush=True)
    semees = bd.semer_regions(CONFIG["lieux"])
    print(f"régions         : {len(bd.regions())} en base"
          + (f", dont {semees} semée(s) depuis questions.yaml" if semees
             else " — libellés modifiables dans /admin/regions (EX-ADM-22)"),
          flush=True)
    # Une photo restée « en traitement » sans tâche vivante n'avancera jamais
    # seule, et l'écran de l'invité continuera d'affirmer qu'on la prépare.
    # Couvre le redémarrage en plein travail — et les photos déposées avant que
    # le traitant n'existe (26 août).
    reprises = photos.reprendre_conversions_perdues()
    if reprises:
        print(f"photos          : {reprises} conversion(s) perdue(s) remise(s) "
              "en file", flush=True)
    fils = taches.demarrer()
    # « 16 démarrés, limite 8 » se lisait comme une incohérence — trois
    # relectures pour comprendre que les fils au-delà de la limite dorment.
    # Une ligne de démarrage doit se comprendre du premier coup : c'est celle
    # qu'on scrute à 21 h en cherchant une anomalie, et elle en fabriquait une.
    if fils:
        actifs = taches.fils_actifs()
        print(f"worker          : {actifs} fil(s) au travail sur {fils} en "
              f"réserve — les autres dorment. `worker.fils` s'ajuste dans "
              f"config.yaml sans redéployer (EX-ARC-20)", flush=True)
    else:
        print("worker          : inhibé (WORKER_ACTIF=0) — aucune tâche ne "
              "sera traitée", flush=True)
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

# --------------------------------------------------------------------------- #
# La porte et les en-têtes (EX-AUTH-18, EX-SEC-04, EX-SEC-07, EX-SEC-08)
# --------------------------------------------------------------------------- #

# **Fermé par défaut, ouvert par liste.** Un middleware plutôt qu'un `Depends`
# sur chaque route : une route ajoutée plus tard est protégée d'office. Une
# liste de routes à protéger aurait laissé passer celle qu'on oublie d'y
# inscrire, et masquer un bouton n'est pas une protection (EX-SEC-04).
#
# Les chemins d'administration sont hors de la porte parce qu'ils ont la leur —
# HTTPBasic sur `MOT_DE_PASSE_ADMIN` (EX-ADM-01). Faire saisir à
# l'administrateur le mot de passe des invités en plus du sien n'ajouterait
# rien à ce qu'il peut déjà faire.
CHEMINS_LIBRES = ("/entrer", "/static/", "/admin", "/tableau", "/deviner",
                  "/sante")


def _hors_porte(chemin: str) -> bool:
    return any(chemin == c or chemin.startswith(c.rstrip("/") + "/")
               or chemin.startswith(c) for c in CHEMINS_LIBRES)


# EX-SEC-08 — une seule source pour la CSP. `CSP_AVEC_BLOB` s'en DÉRIVE :
# écrites à la main toutes les deux, elles divergeraient au premier ajout, et
# c'est la variante la moins souvent relue qui garderait l'ancienne règle.
CSP = ("default-src 'self'; "
       "script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; "
       "img-src 'self' data:; "
       "connect-src 'self'; "
       "base-uri 'none'; "
       "form-action 'self'; "
       "frame-ancestors 'none'")

# L'aperçu local d'EX-PHO-26 passe par `URL.createObjectURL`, donc une URL
# `blob:`. Sans elle, l'aperçu est bloqué — et silencieusement : une image
# vide, aucun message. Écart étroit : autorise l'AFFICHAGE d'un fichier déjà
# choisi par l'invité, aucune exécution. Posé sur la seule route qui en a
# besoin, jamais globalement.
CSP_AVEC_BLOB = CSP.replace("img-src 'self' data:",
                            "img-src 'self' data: blob:")
assert CSP_AVEC_BLOB != CSP, "la dérivation de la CSP ne mord plus sur `img-src`"


@app.middleware("http")
async def porte_et_entetes(request: Request, appel_suivant):
    chemin = request.url.path
    # Avant la porte : en panne de configuration, il n'y a rien derrière la
    # porte à protéger, et un écran de mot de passe qui n'ouvre sur rien
    # ferait croire à un mot de passe erroné.
    if PANNE is not None:
        return HTMLResponse(panne.page(str(PANNE)), status_code=panne.CODE)
    if not _hors_porte(chemin) and not acces.cookie_valide(
            request.cookies.get(acces.NOM_COOKIE)):
        # `vers` conserve la destination : celui qui ouvre le lien de son
        # portrait depuis un message doit y arriver, pas atterrir à l'accueil.
        cible = chemin + (f"?{request.url.query}" if request.url.query else "")
        reponse = RedirectResponse(
            f"/entrer?vers={quote(cible, safe='')}", status_code=303)
    else:
        reponse = await appel_suivant(request)

    # EX-SEC-08. `unsafe-inline` sur les scripts est un écart assumé : le
    # questionnaire, l'accueil et le fragment de portrait portent leur
    # comportement en `<script>` inline, et les extraire à onze jours de
    # l'événement coûterait plus de risque qu'il n'en retire. Le rempart contre
    # l'injection reste l'échappement Jinja2 (EX-SEC-02), qui est actif.
    # `fonts.googleapis.com` et `fonts.gstatic.com` sont les seules origines
    # tierces restantes ; htmx est servi depuis /static.
    reponse.headers.setdefault("Content-Security-Policy", CSP)
    reponse.headers.setdefault("X-Content-Type-Options", "nosniff")
    reponse.headers.setdefault("Referrer-Policy", "same-origin")
    return reponse


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
    """Le libellé d'affichage, tel qu'il est AUJOURD'HUI (EX-ADM-22).

    Lu en base et non dans `questions.yaml` : le fichier est chargé au
    démarrage, donc un renommage fait à 21 h n'y prendrait effet qu'au
    redéploiement suivant — que l'on s'interdit ce soir-là (EX-SAU-09). Le
    fichier reste le repli, pour la fenêtre entre la migration et le semis.
    """
    region = bd.regions().get(code)
    if region:
        return region["libelle"]
    lieu = LIEUX_PAR_CODE.get(code)
    return lieu["libelle"] if lieu else code


def locution_lieu(code: str) -> str:
    """« en Comté », « à Fondcombe », « aux Havres Gris » — la préposition juste.

    Elle vit dans `questions.yaml` depuis l'étape 1, mais n'était branchée que
    sur le prompt : les gabarits écrivaient « en » en dur, ce qui donnait
    « convoqué en Les Havres Gris » sur l'écran que tous les invités voient
    pendant l'écriture de leur chronique.
    """
    region = bd.regions().get(code)
    if region and region["locution"]:
        return region["locution"]
    lieu = LIEUX_PAR_CODE.get(code)
    if not lieu:
        return code
    # Repli sur « à » plutôt que sur rien : un libellé ajouté à la main dans
    # questions.yaml le 4 septembre sans sa locution doit encore produire une
    # phrase lisible.
    return lieu.get("locution") or f"à {lieu['libelle']}"


gabarits.env.globals["libelle_lieu"] = libelle_lieu
gabarits.env.globals["locution_lieu"] = locution_lieu


def heure_locale(instant) -> str:
    """EX-GEN-04 — stocké en UTC, AFFICHÉ en Europe/Zurich.

    Une seule source, `config.en_heure_locale`. Un gabarit qui formaterait
    l'horodatage lui-même afficherait de l'UTC sans que rien ne le dise, et
    « déposée à 19 h 34 » pour une photo de 21 h 34 est le genre d'écart qu'on
    ne remarque qu'en cherchant autre chose.
    """
    return "—" if instant is None else config.en_heure_locale(
        instant).strftime("%d/%m %H:%M")


gabarits.env.globals["heure_locale"] = heure_locale

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
gabarits.env.globals["empreinte_htmx"] = config.empreinte(
    Path(RACINE) / "static" / "htmx.min.js")

# L'étage se déduit des réponses présentes (EX-QUE-11) ; `base_donnees` n'a pas
# à relire questions.yaml pour savoir lesquelles relèvent du second étage.
bd.CLES_SECOND_ETAGE = {q["cle"] for q in CONFIG["bonus"]}
bd.CODES_LIEUX_CONNUS = list(CODES_LIEUX)

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
                # Section 4.6 — le modèle et le plafond viennent du bloc `ia:`
                # du config.yaml du projet, relus à chaud (EX-ADM-02,
                # EX-IA-20). L'écart « lu dans MODELE_IA » se referme ici.
                "modele": config.parametre("ia.modele", ia.MODELE_DEFAUT),
                "jetons_max": config.parametre("ia.jetons_max",
                                               ia.JETONS_MAX_DEFAUT),
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
# Le crochet d'échec est ce qui recoud l'état terminal de la tâche à l'objet
# qu'elle servait. Sans lui, une photo dont la conversion échoue reste « en
# préparation » pour toujours — et le crédit n'est jamais rendu (EX-PHO-33).
taches.enregistrer_traitant("conversion_image", photos.convertir,
                            sur_echec=photos.marquer_echec)


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

def _destination_sure(vers: str | None) -> str:
    """Ne renvoie qu'un chemin **de ce site**.

    Sans ce filtre, `/entrer?vers=https://ailleurs` ferait de la porte un
    tremplin : on saisit le mot de passe du mariage et on se retrouve sur un
    site tiers, avec la confiance de celui qui vient de s'authentifier.
    """
    if not vers or not vers.startswith("/") or vers.startswith("//"):
        return "/"
    # L'antislash est le trou que le contrôle précédent laisse ouvert :
    # `/\ailleurs.example` commence bien par une seule barre, et `urlparse` n'y
    # voit aucun hôte — mais les navigateurs normalisent `\` en `/` avant de
    # suivre l'en-tête, ce qui en fait `//ailleurs.example`, donc un site tiers.
    # Trouvé en réintroduisant le défaut : le test d'origine ne le voyait pas,
    # ses trois cas hostiles étaient tous arrêtés par le contrôle suivant.
    if "\\" in vers:
        return "/"
    if urlparse(vers).netloc or urlparse(vers).scheme:
        return "/"
    return vers


@app.get("/entrer", response_class=HTMLResponse)
def entrer(request: Request, vers: str = "/"):
    """EX-AUTH-18 — le mot de passe unique, imprimé sur les cartons."""
    if acces.cookie_valide(request.cookies.get(acces.NOM_COOKIE)):
        return RedirectResponse(_destination_sure(vers), status_code=303)
    return gabarits.TemplateResponse(
        "entrer.html",
        {"request": request, "vers": _destination_sure(vers), "erreur": None})


@app.post("/entrer")
async def valider_entree(request: Request):
    donnees = dict(await request.form())
    vers = _destination_sure(donnees.get("vers"))
    if not acces.correspond(donnees.get("mot_de_passe") or ""):
        acces.freiner()
        # EX-AUTH-11 — le message dit quoi faire, pas seulement que c'est
        # raté. Le carton est sur la table : le rappeler vaut mieux que
        # « Mot de passe incorrect ».
        return gabarits.TemplateResponse(
            "entrer.html",
            {"request": request, "vers": vers,
             "erreur": "Ce n'est pas le bon mot. Il est écrit sur le carton "
                       "posé sur votre table."},
            status_code=401)
    reponse = RedirectResponse(vers, status_code=303)
    acces.poser_cookie(reponse, request.headers)
    return reponse


@app.get("/", response_class=HTMLResponse)
def accueil(request: Request):
    """EX-AUTH-09 — deux entrées : créer son personnage, ou revoir le sien."""
    reprise = None
    personne = bd.personne_de_l_appareil(identite.du_requete(request))
    if personne is not None:
        chronique = bd.chronique_de_personne(personne.uuid)
        if chronique:
            reprise = {"prenom": personne.prenom,
                       "lien": f"/portrait/{chronique}"}
    return gabarits.TemplateResponse("accueil.html",
                                     {"request": request, "reprise": reprise})


@app.get("/identite", response_class=HTMLResponse)
def ecran_identite(request: Request, intention: str = "creer",
                   erreur: str | None = None):
    """EX-AUTH-19 — l'invité choisit son nom dans la liste importée."""
    annuaire = bd.annuaire()
    if not annuaire:
        # Avant l'import il n'y a rien à choisir : envoyer sur une liste vide
        # serait une impasse.
        return RedirectResponse(f"/identite/libre?intention={_intention(intention)}",
                                status_code=303)
    return gabarits.TemplateResponse(
        "identite.html",
        {"request": request, "intention": _intention(intention),
         "annuaire": annuaire, "erreur": erreur})


@app.get("/identite/libre", response_class=HTMLResponse)
def ecran_identite_libre(request: Request, intention: str = "creer"):
    """EX-AUTH-19 — « je ne suis pas dans la liste »."""
    return gabarits.TemplateResponse(
        "identite_libre.html",
        {"request": request, "intention": _intention(intention),
         "prenom": None, "nom": None, "tables": bd.tables(), "erreur": None})


def _intention(valeur: str | None) -> str:
    """Liste fermée. Une intention inconnue vaut « créer », jamais un plantage."""
    return "revoir" if valeur == "revoir" else "creer"


def _suite_pour(request: Request, personne, intention: str,
                genre: str | None = None):
    """Ce qui se passe une fois qu'on sait de QUI il s'agit.

    Le cookie d'appareil est posé ici, et seulement ici : c'est le moment où
    l'on connaît la personne. Il ne donne aucun droit (EX-AUTH-02) — il évite
    de ressaisir son nom au prochain passage.
    """
    if genre in ("masculin", "feminin") and personne.genre != genre:
        bd.definir_genre(personne.uuid, genre)

    chronique = bd.chronique_de_personne(personne.uuid)
    if chronique:
        if intention == "revoir":
            reponse = RedirectResponse(f"/portrait/{chronique}", status_code=303)
        else:
            # EX-AUTH-09 — la reconduction n'est plus muette. On choisissait son
            # nom pour créer et on se retrouvait devant un portrait sans savoir
            # pourquoi ; l'écran le dit, et rien n'est écrasé.
            reponse = gabarits.TemplateResponse(
                "identite_deja.html",
                {"request": request, "prenom": personne.prenom,
                 "chronique_uuid": chronique})
    elif intention == "revoir":
        return RedirectResponse(
            "/identite?intention=revoir&erreur="
            + quote("Ce nom est bien sur la liste, mais aucun personnage n'a "
                    "encore été écrit pour lui. Revenez à l'écran d'entrée et "
                    "choisissez « Créer mon personnage ».", safe=""),
            status_code=303)
    else:
        reponse = _ecran_questionnaire(request, personne)

    appareil = identite.du_requete(request) or identite.nouveau()
    bd.rattacher_appareil(appareil, personne.uuid)
    identite.poser(reponse, request.headers, appareil)
    return reponse


def _ecran_questionnaire(request: Request, personne):
    return gabarits.TemplateResponse(
        "questionnaire.html",
        {
            "request": request,
            "personne_uuid": personne.uuid,
            "prenom": personne.prenom,
            "nom": personne.nom,
            "genre": personne.genre or "",
            "questions": CONFIG["obligatoires"],
            "action": "/valider",
            "titre": "Six questions",
            "bifurcation": True,
            "nb_bonus_mot": NB_BONUS_MOT,
            "facultatif": False,
        },
    )


@app.post("/identite/choisir", response_class=HTMLResponse)
async def choisir_identite(request: Request):
    donnees = dict(await request.form())
    personne = bd.personne((donnees.get("personne_uuid") or "").strip())
    if personne is None:
        return RedirectResponse("/identite?intention=creer", status_code=303)
    intention = _intention(donnees.get("intention"))

    # Venant de l'écran de rapprochement, l'invité a saisi un nom plus complet
    # que celui de la liste : on le lui reprend plutôt que de le lui refaire
    # taper.
    saisi_nom = (donnees.get("nom_complet") or "").strip()
    if saisi_nom and not personne.nom:
        bd.completer_nom(personne.uuid,
                         donnees.get("prenom_complet") or personne.prenom,
                         saisi_nom)
        personne = bd.personne(personne.uuid)

    # 48 invités sur 93 ont été importés sans nom de famille. On le demande une
    # fois, ici, plutôt que de laisser la lacune jusqu'au bout — et le refus
    # est sans conséquence.
    if not personne.nom and intention != "revoir":
        return gabarits.TemplateResponse(
            "identite_completer.html",
            {"request": request, "personne": personne, "intention": intention})

    return _suite_pour(request, personne, intention)


@app.post("/identite/completer", response_class=HTMLResponse)
async def completer_identite(request: Request):
    donnees = dict(await request.form())
    personne = bd.personne((donnees.get("personne_uuid") or "").strip())
    if personne is None:
        return RedirectResponse("/identite?intention=creer", status_code=303)
    bd.completer_nom(personne.uuid,
                     (donnees.get("prenom") or personne.prenom)[:40],
                     (donnees.get("nom") or "")[:40])
    return _suite_pour(request, bd.personne(personne.uuid),
                       _intention(donnees.get("intention")))


@app.post("/identite/libre", response_class=HTMLResponse)
async def valider_identite_libre(request: Request):
    donnees = dict(await request.form())
    intention = _intention(donnees.get("intention"))
    prenom = (donnees.get("prenom") or "").strip()[:40]
    nom = (donnees.get("nom") or "").strip()[:40]
    genre = donnees.get("genre") if donnees.get("genre") in ("masculin",
                                                             "feminin") else None
    code_table = (donnees.get("code_table") or "").strip()[:40]
    if not prenom:
        return RedirectResponse(f"/identite/libre?intention={intention}",
                                status_code=303)

    exactes = bd.resoudre(prenom, nom)
    if exactes.ambigue:
        return gabarits.TemplateResponse(
            "identite_choix.html",
            {"request": request, "prenom": prenom, "nom": nom,
             "candidates": exactes.candidates, "intention": intention})
    if exactes.unique is not None:
        return _suite_pour(request, exactes.unique, intention, genre)

    # EX-AUTH-05 — ressemblance, avec confirmation. `confirme` dit que l'invité
    # a déjà vu cet écran et répondu « je suis quelqu'un d'autre » : le
    # reproposer en boucle l'enfermerait.
    if donnees.get("confirme") != "oui":
        proches = bd.rapprochements(prenom, nom)
        if proches:
            return gabarits.TemplateResponse(
                "identite_rapprochement.html",
                {"request": request, "prenom": prenom, "nom": nom,
                 "candidats": proches, "intention": intention,
                 "genre": genre, "code_table": code_table})

    if intention == "revoir":
        return RedirectResponse(
            "/identite?intention=revoir&erreur="
            + quote("Aucun personnage n'a été écrit sous ce nom.", safe=""),
            status_code=303)

    # EX-AUTH-19 — la saisie libre, pour qui n'est pas dans la liste.
    personne_uuid = bd.creer_personne_libre(prenom, nom, genre=genre)
    if code_table:
        bd.affecter_table(personne_uuid, code_table)
    return _suite_pour(request, bd.personne(personne_uuid), "creer", genre)


@app.post("/valider")
async def valider(request: Request):
    donnees = dict(await request.form())
    # L'identité vient du champ posé par l'écran d'identité, jamais d'un
    # (prénom, nom) reposté : deux homonymes se distinguent par leur uuid, et
    # une seconde résolution par le nom serait une seconde source de vérité.
    personne = bd.personne((donnees.get("personne_uuid") or "").strip())
    if personne is None:
        return RedirectResponse("/identite?intention=creer", status_code=303)

    reponses = _reponses_du_formulaire(donnees, "obligatoires")
    appareil = identite.du_requete(request)

    # Deuxième barrage : /valider peut être posté sans passer par l'écran
    # d'identité. Sans lui, la porte dérobée vers une seconde chronique
    # resterait ouverte (EX-IA-26).
    deja = bd.chronique_de_personne(personne.uuid)
    if deja:
        return RedirectResponse(f"/portrait/{deja}", status_code=303)

    # Le choix se fait avant la génération : celui qui veut en dire plus
    # n'attend pas deux fois, et on ne lui demande pas de rouvrir un cadeau
    # déjà ouvert.
    if donnees.get("suite") == "bonus":
        identifiant = bd.creer(personne.uuid, reponses, CODES_LIEUX,
                               etat="brouillon", appareil_uuid=appareil)
        return RedirectResponse(f"/bonus/{identifiant}/questions",
                                status_code=303)

    identifiant = bd.creer(personne.uuid, reponses, CODES_LIEUX,
                           appareil_uuid=appareil)
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
                "motifs": CONFIG.get("motifs_reprise", []),
                # EX-PHO-10 laisse TOUJOURS une fenêtre où la photo est reçue
                # mais pas encore affichable : c'est le principe même de la
                # conversion en tâche de fond. L'invité doit être renseigné
                # dans cette fenêtre, sinon il renvoie — et un renvoi consomme
                # une modification (EX-PHO-37). Le silence brûlait du budget.
                "photo": photos.courante(ligne.personne_uuid),
                "budget_photo": photos.budget(ligne.personne_uuid)}
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


def _apres_le_portrait(ligne) -> str:
    """Où l'on va quand l'invité a dit « c'est bien moi ».

    **La station photo est une OFFRE, pas un péage.** Elle ne se propose qu'à
    qui n'a rien déposé. Sans ce contrôle, valider son portrait renvoyait vers
    l'écran de dépôt même après une photo reçue — et comme le portrait garde
    son bouton de validation, on tournait en rond sans autre sortie que
    « Plus tard ». *Constaté en production le 26 août.*
    """
    if photos.courante(ligne.personne_uuid) is not None:
        return "/fin"
    return f"/photo/{ligne.uuid}"


@app.get("/bonus/{identifiant}", response_class=HTMLResponse)
def proposer_bonus(request: Request, identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    if ligne.etage == 2:
        return RedirectResponse(_apres_le_portrait(ligne), status_code=303)
    return gabarits.TemplateResponse(
        "bonus_intro.html",
        {"request": request, "p": ligne, "nb_bonus_mot": NB_BONUS_MOT,
         "sortie": _apres_le_portrait(ligne)}
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


# --------------------------------------------------------------------------- #
# La photo personnelle (EX-PHO-36 à EX-PHO-38)
# --------------------------------------------------------------------------- #

def _chronique_ou_404(identifiant: str):
    ligne = bd.lire(identifiant)
    if ligne is None:
        raise HTTPException(status_code=404, detail="Introuvable")
    return ligne


@app.get("/photo/{identifiant}", response_class=HTMLResponse)
def ecran_photo(request: Request, identifiant: str):
    ligne = _chronique_ou_404(identifiant)
    reponse = gabarits.TemplateResponse(
        "photo.html",
        {
            "request": request,
            "p": ligne,
            "budget": photos.budget(ligne.personne_uuid),
            # L'écran ne disait rien de la photo déjà reçue : l'invité y
            # revenait sans savoir où il en était, et le seul décompte visible
            # était celui du bouton — « il vous restera N », qui parle du
            # futur, pas de ce qui est déjà là.
            "photo": photos.courante(ligne.personne_uuid),
            "taille_max": photos.TAILLE_MAX_OCTETS,
            "action": f"/photo/{identifiant}",
            "suite": f"/portrait/{identifiant}",
        },
    )
    # `blob:` est indispensable a l'apercu local d'EX-PHO-26 et absent de la
    # CSP du projet. Ecart etroit, consigne sous EX-SEC-08 : il autorise
    # l'AFFICHAGE d'un fichier local, aucune execution.
    reponse.headers["Content-Security-Policy"] = CSP_AVEC_BLOB
    return reponse


@app.post("/photo/{identifiant}")
async def deposer_photo(identifiant: str, fichier: UploadFile = File(...)):
    ligne = _chronique_ou_404(identifiant)
    octets = await fichier.read()
    try:
        photo = photos.deposer(ligne.personne_uuid, octets,
                               est_test=bool(ligne.est_test))
    except photos.RefusPhoto as refus:
        # 422 et non 400 : la requete est bien formee, c'est son contenu qui
        # est refuse. Le message part tel quel a l'invite (EX-AUTH-11).
        return JSONResponse({"refus": str(refus)}, status_code=422)
    # EX-PHO-10 — on rend la main tout de suite ; la conversion suit en file.
    return JSONResponse({"photo": photo.uuid, "etat": photo.etat})


@app.get("/photo/{identifiant}/vignette")
def vignette_photo(identifiant: str):
    """La vignette de SA photo, servie depuis le volume.

    **Jamais par `/static`**, qui est monté publiquement : quatre-vingt-treize
    photos d'invités derrière un chemin devinable serait le seul vrai incident
    possible de cette soirée. Le chemin se construit depuis la LIGNE EN BASE et
    jamais depuis un segment d'URL — `identifiant` désigne la chronique, pas le
    fichier, donc aucune traversée n'est représentable.

    L'autorisation est celle du reste du parcours : l'UUID de la chronique est
    la capacité, comme pour `/portrait/{uuid}`. Le risque est celui qu'assume
    déjà EX-AUTH-18, pas un nouveau.
    """
    ligne = _chronique_ou_404(identifiant)
    photo = photos.courante(ligne.personne_uuid)
    if photo is None or not photo.chemin_vignette:
        raise HTTPException(status_code=404, detail="Aucune vignette")
    chemin = (config.projet().dossier_medias / "photos_invites" / "vignettes"
              / photo.chemin_vignette)
    if not chemin.is_file():
        raise HTTPException(status_code=404, detail="Aucune vignette")
    return FileResponse(chemin, media_type="image/jpeg")


@app.get("/fin", response_class=HTMLResponse)
def fin(request: Request):
    return gabarits.TemplateResponse("fin.html", {"request": request})


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Import de la liste des invités (EX-ADM-05, EX-ADM-16)
# --------------------------------------------------------------------------- #

def _dossier_imports() -> Path:
    """Les classeurs importés sont conservés sur le volume.

    Trois raisons : la confirmation relit le fichier plutôt qu'un plan calculé
    dix minutes plus tôt sur une base qui a pu changer ; le fichier part dans
    les instantanés, donc dans les sauvegardes ; et savoir exactement ce qui a
    été importé, et quand, vaut le kilo-octet que ça coûte.
    """
    dossier = config.projet().dossier / "imports"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _contexte_invites(request: Request, **extra) -> dict:
    with bd.Seance() as seance:
        actifs = list(seance.scalars(
            select(modeles.Personne).where(modeles.Personne.active.is_(True))))
    base = {
        "request": request,
        "mode_test": bd.mode_test_actif(),
        "total_actifs": len(actifs),
        "total_import": sum(1 for p in actifs if p.source == "import"),
        "total_libre": sum(1 for p in actifs if p.source != "import"),
        "plan": None, "applique": False, "fichier": "", "liste_complete": False,
    }
    base.update(extra)
    return base


@app.get("/admin/invites", response_class=HTMLResponse)
def admin_invites(request: Request, _: str = Depends(admin)):
    return gabarits.TemplateResponse("admin_invites.html",
                                     _contexte_invites(request))


@app.post("/admin/invites/simuler", response_class=HTMLResponse)
async def admin_invites_simuler(request: Request, _: str = Depends(admin)):
    donnees = await request.form()
    envoi = donnees.get("classeur")
    if envoi is None or not getattr(envoi, "filename", ""):
        return RedirectResponse("/admin/invites", status_code=303)

    horodatage = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    chemin = _dossier_imports() / f"{horodatage}.xlsx"
    chemin.write_bytes(await envoi.read())

    liste_complete = donnees.get("liste_complete") == "oui"
    try:
        plan = import_invites.preparer(chemin, liste_complete=liste_complete)
    except Exception as exc:  # openpyxl lève des types très variés
        plan = import_invites.Plan(erreurs=[
            f"le fichier n'a pas pu être lu ({type(exc).__name__}). "
            "Est-ce bien un classeur .xlsx, et non un .xls ou un .csv "
            "renommé ? Le gabarit est dans exemples/invites-gabarit.xlsx."])
    return gabarits.TemplateResponse(
        "admin_invites.html",
        _contexte_invites(request, plan=plan, fichier=chemin.name,
                          liste_complete=liste_complete))


@app.post("/admin/invites/appliquer", response_class=HTMLResponse)
async def admin_invites_appliquer(request: Request, _: str = Depends(admin)):
    donnees = dict(await request.form())
    nom = pathlib.PurePosixPath(donnees.get("fichier") or "").name
    chemin = _dossier_imports() / nom
    # Le nom vient d'un champ du formulaire : le réduire à son dernier segment
    # et vérifier qu'il existe bien dans le dossier d'imports empêche qu'un
    # `../../config.yaml` soit lu comme un classeur.
    if not nom or not chemin.is_file():
        return RedirectResponse("/admin/invites", status_code=303)

    plan = import_invites.appliquer(
        chemin, liste_complete=donnees.get("liste_complete") == "oui")
    return gabarits.TemplateResponse(
        "admin_invites.html",
        _contexte_invites(request, plan=plan, applique=plan.recevable,
                          fichier=nom))


# --------------------------------------------------------------------------- #
# Tables et régions (EX-ADM-22)
# --------------------------------------------------------------------------- #

@app.get("/admin/tables", response_class=HTMLResponse)
def admin_tables(request: Request, _: str = Depends(admin)):
    return gabarits.TemplateResponse(
        "admin_tables.html",
        {"request": request, "tables": bd.tables(avec_test=True), "enregistre": 0,
         "mode_test": bd.mode_test_actif()})


@app.post("/admin/tables", response_class=HTMLResponse)
async def admin_tables_enregistrer(request: Request, _: str = Depends(admin)):
    donnees = dict(await request.form())
    enregistre = sum(
        1 for cle, valeur in donnees.items()
        if cle.startswith("nom_") and bd.renommer_table(cle[4:], valeur))
    return gabarits.TemplateResponse(
        "admin_tables.html",
        {"request": request, "tables": bd.tables(avec_test=True), "enregistre": enregistre,
         "mode_test": bd.mode_test_actif()})


@app.get("/admin/regions", response_class=HTMLResponse)
def admin_regions(request: Request, _: str = Depends(admin)):
    return gabarits.TemplateResponse(
        "admin_regions.html",
        {"request": request, "regions": _regions_ordonnees(), "enregistre": 0,
         "mode_test": bd.mode_test_actif()})


def _regions_ordonnees() -> list[dict]:
    return [dict(code=code, **valeurs) for code, valeurs
            in sorted(bd.regions().items(), key=lambda p: p[1]["ordre"])]


@app.post("/admin/regions", response_class=HTMLResponse)
async def admin_regions_enregistrer(request: Request, _: str = Depends(admin)):
    donnees = dict(await request.form())
    enregistre = 0
    for region in _regions_ordonnees():
        code = region["code"]
        if bd.modifier_region(
                code,
                donnees.get(f"libelle_{code}", region["libelle"]),
                donnees.get(f"locution_{code}", region["locution"]),
                donnees.get(f"ombre_{code}", region["ombre"])):
            enregistre += 1
    return gabarits.TemplateResponse(
        "admin_regions.html",
        {"request": request, "regions": _regions_ordonnees(),
         "enregistre": enregistre, "mode_test": bd.mode_test_actif()})


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


def _intitules_questions() -> dict[str, str]:
    """Clé -> intitulé lu, pour que la fiche montre la QUESTION et non la clé.

    `questions.yaml` est la référence éditoriale (EX-QUE-12) : les intitulés
    s'y corrigent jusqu'au 4 septembre, et la fiche suit sans redéploiement.
    """
    intitules = {}
    for bloc in ("obligatoires", "bonus"):
        for question in CONFIG.get(bloc, []):
            intitules[question["cle"]] = _substituer(
                question.get("question", question["cle"]))
            prealable = question.get("prealable")
            if prealable:
                intitules[prealable["cle"]] = _substituer(
                    prealable.get("question", prealable["cle"]))
    return intitules


def _fiche(ligne) -> dict:
    """Ce qu'une chronique montre à l'administrateur, réponses comprises."""
    intitules = _intitules_questions()
    reponses = json.loads(ligne.reponses_json or "{}")
    return {
        "p": ligne,
        "lieu_affiche": _lieu_affiche(ligne),
        # L'ordre du questionnaire, pas celui du dictionnaire : une fiche qui
        # réordonne les réponses ne se relit pas à côté de l'écran d'origine.
        "reponses": [(intitules.get(cle, cle), cle, valeur)
                     for cle, valeur in sorted(
                         reponses.items(),
                         key=lambda kv: list(intitules).index(kv[0])
                         if kv[0] in intitules else 999)],
        "photo": photos.courante(ligne.personne_uuid),
        "budget_photo": photos.budget(ligne.personne_uuid),
        "max_generations": MAX_GENERATIONS,
        "motifs": CONFIG.get("motifs_reprise", []),
        "codes_lieux": CODES_LIEUX,
        # Le lieu découpe les dix chapitres : le déplacer déséquilibre la
        # répartition. L'effectif est montré À CÔTÉ du champ, sinon la
        # conséquence ne se découvre qu'en octobre.
        "effectifs": bd.effectifs_par_lieu(),
    }


@app.get("/admin/chroniques", response_class=HTMLResponse)
def admin_chroniques(request: Request, test: str = "",
                     _: str = Depends(admin)):
    """EX-TST-05 — production par défaut, test sur demande explicite."""
    sur_le_test = test == "oui"
    lignes = [p for p in bd.lister(avec_test=True)
              if bool(p.est_test) == sur_le_test]
    for p in lignes:
        p.lieu_affiche = _lieu_affiche(p)
        p.photo = photos.courante(p.personne_uuid)
    return gabarits.TemplateResponse(
        "admin_chroniques.html",
        {"request": request, "lignes": lignes, "sur_le_test": sur_le_test,
         "mode_test": bd.mode_test_actif()},
    )


# ORDRE SIGNIFICATIF — `.json` est déclarée AVANT la page HTML. Starlette
# apparie dans l'ordre de déclaration, et `{identifiant}` apparie volontiers
# « <uuid>.json » : la page HTML avalerait l'export et rendrait 404 sur un
# UUID suffixé. Même piège que deux règles CSS de même spécificité — dépendre
# de l'ordre, c'est dépendre de l'endroit où quelqu'un posera la suivante.
# `test_admin_chroniques.py` éprouve les deux, et tombe si on les réordonne.
@app.get("/admin/chronique/{identifiant}.json")
def admin_chronique_json(identifiant: str, _: str = Depends(admin)):
    """EX-ADM-21 — une chronique, à URL stable, pour la repasser au modèle.

    L'export complet est la sauvegarde de référence ; il est inexploitable
    pour vérifier un cas. Cent chroniques dans un seul fichier ne se lisent
    pas.
    """
    ligne = _chronique_ou_404(identifiant)
    return JSONResponse(
        {
            # Le fichier dit ce qu'il est : une chronique de test et une
            # chronique productive seraient sinon interchangeables une fois
            # sur le disque (EX-TST-08).
            "projet": config.projet().identifiant,
            "portee": "test" if ligne.est_test else "production",
            "uuid": ligne.uuid,
            "prenom": ligne.prenom, "nom": ligne.nom,
            "lieu": ligne.lieu, "lieu_libelle": libelle_lieu(ligne.lieu),
            "etage": ligne.etage,
            "reponses": json.loads(ligne.reponses_json or "{}"),
            "nom_fictif": ligne.nom_fictif, "peuple": ligne.peuple,
            "portrait": ligne.portrait, "indice": ligne.indice,
            "fuites_noms": ligne.fuites_noms, "modele": ligne.modele,
            "duree_s": ligne.duree_s,
            "jetons": [ligne.jetons_entree, ligne.jetons_sortie],
            "nb_generations": ligne.nb_generations,
            "nb_tentatives": ligne.nb_tentatives,
            "etat": ligne.etat, "derniere_erreur": ligne.derniere_erreur,
        },
        headers={"Content-Disposition": 'attachment; filename='
                 f'"chronique-{ligne.uuid[:8]}'
                 f'{"-test" if ligne.est_test else ""}.json"'},
    )


@app.get("/admin/chronique/{identifiant}", response_class=HTMLResponse)
def admin_chronique(request: Request, identifiant: str,
                    _: str = Depends(admin)):
    ligne = _chronique_ou_404(identifiant)
    contexte = _fiche(ligne)
    contexte.update({"request": request, "mode_test": bd.mode_test_actif()})
    return gabarits.TemplateResponse("admin_chronique.html", contexte)


@app.post("/admin/chronique/{identifiant}/regenerer")
async def admin_regenerer(request: Request, identifiant: str,
                          _: str = Depends(admin)):
    """Régénère **sans limite** (EX-ADM-10, EX-IA-22).

    Ni le quota de l'invité ni `MAX_TENTATIVES` ne s'y opposent. Le second est
    un garde-fou contre une BOUCLE d'appels payants ; un administrateur qui
    appuie sur un bouton n'est pas une boucle, c'est un acte par appui. Ce qui
    protège la dépense reste `ia.plafond_appels`, et lui n'est jamais levé.
    """
    ligne = _chronique_ou_404(identifiant)
    donnees = await request.form()
    motif = (donnees.get("motif") or "").strip()
    _lancer_generation(identifiant,
                       motif=motif if motif in MOTIFS_REPRISE else None)
    return _retour_fiche(ligne)


def _retour_fiche(ligne) -> RedirectResponse:
    """Après chaque action, on revient VOIR le résultat.

    Un écran d'administration qui agit sans remontrer l'objet oblige à
    retrouver la page à la main — et à 21 h, c'est là qu'on se trompe de
    chronique.
    """
    return RedirectResponse(f"/admin/chronique/{ligne.uuid}", status_code=303)


@app.post("/admin/chronique/{identifiant}/modifier")
async def admin_modifier_chronique(request: Request, identifiant: str,
                                   _: str = Depends(admin)):
    ligne = _chronique_ou_404(identifiant)
    donnees = await request.form()
    bd.modifier_chronique(identifiant, dict(donnees))
    return _retour_fiche(ligne)


@app.post("/admin/chronique/{identifiant}/crediter")
async def admin_crediter(request: Request, identifiant: str,
                         _: str = Depends(admin)):
    """Rend un crédit, ou les rend tous, sur les photos ou les générations."""
    ligne = _chronique_ou_404(identifiant)
    donnees = await request.form()
    tout = donnees.get("portee") == "tout"
    if donnees.get("quoi") == "photo":
        photos.crediter(ligne.personne_uuid, tout=tout)
    else:
        bd.crediter_chronique(identifiant, tout=tout)
    return _retour_fiche(ligne)


@app.post("/admin/chronique/{identifiant}/photo")
async def admin_photo_action(request: Request, identifiant: str,
                             fichier: UploadFile | None = File(None),
                             _: str = Depends(admin)):
    """Dépose au nom de l'invité, ou retire sa photo. Sans jamais consommer."""
    ligne = _chronique_ou_404(identifiant)
    donnees = await request.form()
    if donnees.get("action") == "retirer":
        photo = photos.courante(ligne.personne_uuid)
        if photo is not None:
            photos.retirer(photo.uuid, par="admin")
        return _retour_fiche(ligne)
    if fichier is not None:
        octets = await fichier.read()
        try:
            photos.deposer_pour(ligne.personne_uuid, octets,
                                est_test=bool(ligne.est_test))
        except photos.RefusPhoto as refus:
            return JSONResponse({"refus": str(refus)}, status_code=422)
    return _retour_fiche(ligne)


@app.post("/admin/chronique/{identifiant}/supprimer")
async def admin_supprimer_chronique(request: Request, identifiant: str,
                                    _: str = Depends(admin)):
    """Masque ou remontre. Toujours réversible (EX-GEN-03)."""
    ligne = _chronique_ou_404(identifiant)
    donnees = await request.form()
    bd.supprimer_chronique(identifiant,
                           supprimee=donnees.get("action") != "restaurer")
    return _retour_fiche(ligne)


@app.get("/admin/photo/{identifiant}/{variante}")
def admin_photo_fichier(identifiant: str, variante: str,
                        _: str = Depends(admin)):
    """La photo, servie depuis le volume, derrière MOT_DE_PASSE_ADMIN.

    **Jamais par `/static`.** Et `variante` est comparée à une liste close
    avant tout usage : concaténée telle quelle, « ../../.. » sortirait du
    dossier des médias. Le nom du fichier, lui, vient de la BASE.
    """
    if variante not in ("originaux", "web", "vignettes"):
        raise HTTPException(status_code=404, detail="Variante inconnue")
    ligne = _chronique_ou_404(identifiant)
    photo = photos.courante(ligne.personne_uuid)
    relatif = None if photo is None else {
        "originaux": photo.chemin_original,
        "web": photo.chemin_web,
        "vignettes": photo.chemin_vignette,
    }[variante]
    if not relatif:
        raise HTTPException(status_code=404, detail="Aucun fichier")
    chemin = config.projet().dossier_medias / "photos_invites" / variante / relatif
    if not chemin.is_file():
        raise HTTPException(status_code=404, detail="Aucun fichier")
    return FileResponse(chemin)


@app.get("/tableau")
def tableau_ancienne_adresse(test: str = ""):
    """L'adresse d'avant, gardée : elle est en signet et sur des notes."""
    return RedirectResponse(f"/admin/tableau?test={test}", status_code=308)


def _decompte_photos(lignes) -> dict:
    """Reçues, prêtes, en traitement, en échec — et combien de chroniques sans.

    Les quatre se lisent ensemble : « 40 reçues » ne dit rien si l'on ignore
    combien sont encore en conversion. Dérivé, jamais stocké (EX-GEN-07).
    """
    etats = {"prete": 0, "traitement": 0, "echouee": 0}
    sans = 0
    for ligne in lignes:
        photo = photos.courante(ligne.personne_uuid)
        if photo is None:
            sans += 1
        else:
            etats[photo.etat] = etats.get(photo.etat, 0) + 1
    etats["recues"] = sum(etats[e] for e in ("prete", "traitement", "echouee"))
    etats["sans"] = sans
    return etats


@app.get("/admin/tableau", response_class=HTMLResponse)
def tableau(request: Request, test: str = "", _: str = Depends(admin)):
    """EX-TST-05 — production par défaut, test sur demande explicite.

    Le tableau montrait la production SEULE depuis que `lister()` exclut le
    test : c'était l'endroit même où l'on vérifie le test de fumée du jour J,
    et il était devenu aveugle à ce qu'on venait d'y faire.
    """
    sur_le_test = test == "oui"
    participations = [p for p in bd.lister(avec_test=True)
                      if bool(p.est_test) == sur_le_test]
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
            # EX-ADM-18 — « photos reçues ». Dérivé des chroniques affichées,
            # donc la séparation production / test vaut aussi pour elles.
            "photos": _decompte_photos(participations),
            "fuites": sum(1 for p in participations if p.fuites_noms),
            "sur_le_test": sur_le_test,
            "mode_test": bd.mode_test_actif(),
            "debit": debit.dernier(),
        },
    )


@app.get("/tableau/export.json")
def export_ancienne_adresse(test: str = ""):
    return RedirectResponse(f"/admin/tableau/export.json?test={test}",
                            status_code=308)


@app.get("/admin/tableau/export.json")
def export(test: str = "", _: str = Depends(admin)):
    """EX-TST-08 — l'export productif exclut le test. Toujours.

    **Le fichier dit ce qu'il est.** Un tableau JSON nu ne se distingue pas
    d'un autre une fois sur le disque : deux exports, l'un productif l'autre de
    test, seraient interchangeables au moment où l'on s'en sert. L'enveloppe et
    le nom du fichier le disent tous les deux, parce que l'un des deux se perd
    toujours — le nom en le renommant, l'enveloppe en ouvrant le fichier au
    milieu.
    """
    sur_le_test = test == "oui"
    lignes = [p for p in bd.lister(avec_test=True)
              if bool(p.est_test) == sur_le_test]
    nom_fichier = ("chroniques-TEST" if sur_le_test else "chroniques") + \
        f"-{config.projet().identifiant}.json"
    return JSONResponse(
        {
            "contenu": "test" if sur_le_test else "production",
            "projet": config.projet().identifiant,
            "type_projet": config.projet().type,
            "genere_le": config.en_heure_locale(
                config.maintenant()).isoformat(timespec="seconds"),
            "nombre": len(lignes),
            "chroniques": [
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
                for p in lignes
            ],
        },
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


# --- Morceau A, JETABLE — à retirer avec `mesure_photo.py` et `mesure.html` ---
# Éteint par défaut : sans `MESURE_PHOTO=1`, la route n'est même pas déclarée.
# Un fichier oublié dans le dépôt ne sert alors rien (EX-SEC-04).
import mesure_photo  # noqa: E402

if mesure_photo.actif():
    app.include_router(mesure_photo.routeur)
    print("mesure photo   : /mesure ACTIVE — page jetable, à retirer après relevé",
          flush=True)
