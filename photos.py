"""La photo personnelle — dépôt et budget (EX-PHO-36 à EX-PHO-38).

**Une photo appartient à une personne**, jamais à un appareil ni à une
chronique : `EX-AUTH-03` rattache les quotas à la personne, et effacer ses
cookies ne doit pas rendre un budget neuf. La chronique sert d'adresse dans
l'URL — c'est le même modèle de capacité que `/portrait/{uuid}` —, mais c'est
`personne_uuid` qui porte le droit.

**Le budget se dérive, il ne se déclare pas.** Sixième grandeur du projet à
suivre la règle (`EX-GEN-07`) : aucun compteur en base, tout se recompte depuis
le journal. Un dépôt dont la conversion a échoué **ne se décompte pas** — c'est
notre défaut, pas celui de l'invité, et `EX-PHO-33` dit déjà que son retrait est
gratuit. Sans cette soustraction, trois échecs de notre côté épuiseraient un
budget sans qu'une seule photo ait jamais été vue.

**Le format se lit aux octets de tête, jamais au nom du fichier.** Mesuré le
26 août : l'iPhone annonce `image.jpg`, l'Android un nombre à vingt chiffres, et
Safari renomme en `.heic` ce qu'il vient de convertir en JPEG. Une vidéo `.mov`
renommée `.jpg` partage le conteneur ISO-BMFF du HEIC : seule la marque les
sépare, et `EX-PHO-12` n'accepte aucune vidéo.

**Aucun décodeur HEIF.** Les quatre relevés du 26 août (iPhone 18.7 et Android,
capture et galerie) ont tous livré du JPEG réel. `pillow-heif` exigerait
`libheif` en natif dans l'image `slim`, donc une compilation, à quatre jours de
l'événement. Ce qui arriverait quand même dans un format inconnu suit le chemin
d'échec : l'original reste intact, l'état passe à `echouee`, le retrait est
gratuit et la photo est de toute façon facultative (`EX-PHO-38`).
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

import base_donnees as bd
import config
import taches
from modeles import Journal, Photo

# EX-PHO-37 lu à la lettre : « la photo admet trois MODIFICATIONS », et une
# modification est un remplacement. Le premier dépôt n'en est pas un. D'où
# 1 + 3, ce que la configuration dit déjà en deux clés distinctes —
# `photo_par_personne` et `modifications_photo`.
DEPOTS_PAR_DEFAUT = 1
MODIFICATIONS_PAR_DEFAUT = 3

# Mesuré : 5,25 Mo au pire des quatre relevés. 25 Mo laisse cinq fois la marge
# sans ouvrir la porte à un envoi qui durerait une minute.
TAILLE_MAX_OCTETS = 25 * 1024 * 1024

FORMATS_ACCEPTES = {"jpeg", "png", "webp", "gif"}
EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}

MARQUES_HEIF = {"heic", "heix", "hevc", "hevx", "heim", "heis", "hevm",
                "hevs", "mif1", "msf1"}
MARQUES_AVIF = {"avif", "avis"}
MARQUES_VIDEO = {"isom", "iso2", "mp41", "mp42", "avc1", "qt  ", "M4V ",
                 "M4A ", "3gp4", "3gp5"}


class RefusPhoto(Exception):
    """Refus lisible par l'invité. Ne consomme rien (EX-PHO-15)."""


def identifier(octets: bytes) -> str:
    """Le format réel, lu aux octets de tête.

    Éprouvée au morceau A contre quatre envois réels, et contre un `.mov`
    renommé `.jpg` qu'elle a démasqué.
    """
    if octets[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if octets[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if octets[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "webp"
    if octets[:2] in (b"II", b"MM") and octets[2:4] in (b"*\x00", b"\x00*"):
        return "tiff"
    if octets[4:8] == b"ftyp":
        marque = octets[8:12].decode("ascii", "replace")
        if marque in MARQUES_HEIF:
            return f"heif ({marque})"
        if marque in MARQUES_AVIF:
            return f"avif ({marque})"
        if marque in MARQUES_VIDEO:
            return f"video ({marque})"
        return f"iso-bmff ({marque})"
    return "inconnu"


@dataclass
class Budget:
    """Tout est recompté ; rien n'est lu dans une colonne."""
    deposes: int
    echecs: int
    maximum: int

    @property
    def consommes(self) -> int:
        return self.deposes - self.echecs

    @property
    def restants(self) -> int:
        return max(0, self.maximum - self.consommes)

    @property
    def epuise(self) -> bool:
        return self.restants <= 0


def maximum_depots() -> int:
    depots = config.parametre("quotas.photo_par_personne", DEPOTS_PAR_DEFAUT)
    modifs = config.parametre("quotas.modifications_photo",
                              MODIFICATIONS_PAR_DEFAUT)
    return int(depots) + int(modifs)


def _compter(seance, personne_uuid: str, action: str) -> int:
    return seance.scalar(
        select(func.count()).select_from(Journal)
        .where(Journal.acteur_personne_uuid == personne_uuid,
               Journal.action == action)
    ) or 0


def budget(personne_uuid: str) -> Budget:
    with bd.Seance() as seance:
        return _budget(seance, personne_uuid)


def _budget(seance, personne_uuid: str) -> Budget:
    return Budget(
        deposes=_compter(seance, personne_uuid, Journal.PHOTO_DEPOSEE),
        echecs=_compter(seance, personne_uuid, Journal.PHOTO_ECHOUEE),
        maximum=maximum_depots(),
    )


def courante(personne_uuid: str) -> Photo | None:
    """La photo vivante de cette personne, ou rien.

    `EX-PHO-36` — une seule photo. Un remplacement marque la précédente
    supprimée ; la suppression est douce (`EX-GEN-03`), le fichier reste.
    """
    with bd.Seance() as seance:
        return seance.scalar(
            select(Photo)
            .where(Photo.personne_uuid == personne_uuid,
                   Photo.portee == "personnelle",
                   Photo.supprimee.is_(False))
            .order_by(Photo.creee_le.desc()))


def _dossier(variante: str) -> Path:
    return config.projet().dossier_medias / "photos_invites" / variante


def verifier(octets: bytes) -> str:
    """Contrôle d'admission. Lève `RefusPhoto` avec un message pour l'invité.

    Le contrôle de taille existe aussi côté navigateur, mais c'est celui-ci qui
    fait foi : le premier épargne quarante secondes d'attente avant un refus,
    le second est le seul qu'on ne puisse pas contourner.
    """
    if not octets:
        raise RefusPhoto("Le fichier est arrivé vide. Réessayez.")
    if len(octets) > TAILLE_MAX_OCTETS:
        raise RefusPhoto(
            f"Cette image fait {len(octets) / 1048576:.0f} Mo, et la limite "
            f"est de {TAILLE_MAX_OCTETS // 1048576} Mo. "
            "Choisissez-en une autre.")
    forme = identifier(octets)
    if forme.startswith("video"):
        # EX-PHO-12. Le nom du fichier ne dit rien : c'est la marque du
        # conteneur qui trahit la vidéo.
        raise RefusPhoto("C'est une vidéo. Le Livre n'accueille que des images.")
    if forme not in FORMATS_ACCEPTES:
        raise RefusPhoto(
            "Ce format d'image n'est pas reconnu. Reprenez la photo avec "
            "l'appareil du téléphone plutôt que de choisir un fichier.")
    return forme


def deposer(personne_uuid: str, octets: bytes, est_test: bool = False) -> Photo:
    """Écrit l'original, journalise, met la conversion en file. Rend la main.

    `EX-PHO-10` — l'application répond immédiatement. La conversion, le
    redimensionnement et la vignette s'exécutent en tâche de fond.
    `EX-PHO-11` — l'original est écrit **avant** tout, et n'est jamais retouché.
    """
    forme = verifier(octets)

    with bd.Seance() as seance:
        etat_budget = _budget(seance, personne_uuid)
        if etat_budget.epuise:
            raise RefusPhoto(
                "Vous avez utilisé tous vos changements de photo. "
                "Celle-ci est la vôtre.")

        identifiant = str(_uuid.uuid4())
        # Le nom du fichier se dérive de l'UUID. Mesuré au morceau A : les noms
        # reçus sont « image.jpg » ou vingt chiffres — inutilisables, et un nom
        # venu d'un formulaire est une donnée non fiable (EX-SEC-16).
        relatif = f"{identifiant}{EXTENSIONS[forme]}"
        chemin = _dossier("originaux") / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(octets)

        ancienne = seance.scalar(
            select(Photo).where(Photo.personne_uuid == personne_uuid,
                                Photo.portee == "personnelle",
                                Photo.supprimee.is_(False)))
        if ancienne is not None:
            ancienne.supprimee = True
            ancienne.supprimee_le = config.maintenant()

        photo = Photo(
            uuid=identifiant,
            personne_uuid=personne_uuid,
            portee="personnelle",
            est_test=est_test,
            chemin_original=relatif,
            etat="traitement",
        )
        seance.add(photo)
        bd.journaliser(
            seance, Journal.PHOTO_DEPOSEE, objet_uuid=identifiant,
            objet_type="photo", acteur=personne_uuid,
            details={"forme": forme, "octets": len(octets),
                     "remplace": ancienne.uuid if ancienne else None})
        seance.commit()
        seance.refresh(photo)

    taches.mettre_en_file("conversion_image", identifiant)
    return photo


# --------------------------------------------------------------------------- #
# Lecture et retrait
# --------------------------------------------------------------------------- #

# Le segment d'URL ne devient JAMAIS un morceau de chemin. Il est traduit par
# ce dictionnaire, et le nom du fichier vient de la ligne en base : c'est la
# seule façon qu'un `../` dans l'URL ne veuille rien dire du tout.
VARIANTES = {"original": ("originaux", "chemin_original"),
             "web": ("web", "chemin_web"),
             "vignette": ("vignettes", "chemin_vignette")}


def chemin_fichier(photo: Photo, variante: str) -> Path | None:
    """Le chemin sur le volume, ou `None` si cette variante n'existe pas encore.

    Les photos vivent sur le volume et ne sont **jamais** servies par
    `/static`, qui est monté publiquement : quatre-vingt-treize photos
    d'invités derrière un chemin devinable serait le seul vrai incident
    possible de cette soirée.
    """
    if variante not in VARIANTES:
        return None
    dossier, colonne = VARIANTES[variante]
    nom = getattr(photo, colonne, None)
    if not nom:
        return None
    racine = (config.projet().dossier_medias / "photos_invites" / dossier).resolve()
    chemin = (racine / nom).resolve()
    # Ceinture et bretelles : le nom vient de la base, donc il est sain — mais
    # une base réparée à la main ne l'est plus forcément.
    if racine not in chemin.parents:
        return None
    return chemin if chemin.exists() else None


def retirer(photo_uuid: str, par: str | None = None,
            pour_le_compte_de: str | None = None) -> bool:
    """Suppression douce (EX-GEN-03) : la ligne se marque, le fichier reste.

    Ne débite rien. `EX-PHO-37` compte les **modifications**, et une
    modification est « une suppression **suivie d'un nouvel envoi** » : c'est
    le dépôt suivant qui coûte, jamais le retrait. Retirer sans renvoyer ne
    coûte donc rien, et c'est ce que veut `EX-PHO-33` pour une photo en échec.
    """
    with bd.Seance() as seance:
        photo = seance.get(Photo, photo_uuid)
        if photo is None or photo.supprimee:
            return False
        photo.supprimee = True
        photo.supprimee_le = config.maintenant()
        bd.journaliser(seance, Journal.PHOTO_RETIREE, objet_uuid=photo_uuid,
                       objet_type="photo",
                       acteur=par or photo.personne_uuid,
                       pour_le_compte_de=pour_le_compte_de,
                       details={"etat_au_retrait": photo.etat})
        seance.commit()
        return True


def par_personne(avec_test: bool = False) -> dict[str, Photo]:
    """La photo vivante de chaque personne, indexée par `personne_uuid`.

    EX-TST-04 — le test est exclu par défaut, comme `lister()` et `tables()`.
    """
    with bd.Seance() as seance:
        requete = (select(Photo)
                   .where(Photo.portee == "personnelle",
                          Photo.supprimee.is_(False))
                   .order_by(Photo.creee_le))
        if not avec_test:
            requete = requete.where(Photo.est_test.is_(False))
        return {p.personne_uuid: p for p in seance.scalars(requete)}


def etats(avec_test: bool = False) -> dict[str, int]:
    """Le décompte par état, pour le tableau de bord (EX-ADM-18).

    Dérivé, comme tout le reste : aucune colonne ne le porte.
    """
    compte = {"traitement": 0, "prete": 0, "echouee": 0}
    for photo in par_personne(avec_test).values():
        compte[photo.etat] = compte.get(photo.etat, 0) + 1
    compte["total"] = sum(compte[c] for c in ("traitement", "prete", "echouee"))
    return compte
