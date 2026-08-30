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
import depot_objet
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
    rendus: int = 0

    @property
    def consommes(self) -> int:
        # Jamais négatif : rendre plus de crédits qu'il n'y a eu de dépôts est
        # légitime, et ne doit pas offrir de dépôts supplémentaires.
        return max(0, self.deposes - self.echecs - self.rendus)

    @property
    def restants(self) -> int:
        return max(0, self.maximum - self.consommes)

    @property
    def epuise(self) -> bool:
        return self.restants <= 0


@dataclass
class BudgetTable:
    """EX-CDT-14 — trois compteurs indépendants, tous dérivés.

    Ils s'emboîtent : cinq affichées plus cinq suppressions font dix envois.
    Les trois se lient donc en même temps — arrivé à cinq, il faut supprimer
    pour ajouter ; après cinq suppressions, la table est figée. C'est voulu, et
    l'administrateur peut rendre des crédits.
    """
    affichees: int
    envois: int
    suppressions: int
    max_affichees: int
    max_envois: int
    max_suppressions: int

    @property
    def peut_deposer(self) -> bool:
        return (self.affichees < self.max_affichees
                and self.envois < self.max_envois)

    @property
    def peut_supprimer(self) -> bool:
        return self.suppressions < self.max_suppressions

    @property
    def restantes(self) -> int:
        """Combien il en manque pour atteindre les cinq."""
        return max(0, self.max_affichees - self.affichees)


def budget_table(table_uuid: str) -> BudgetTable:
    with bd.Seance() as seance:
        return _budget_table(seance, table_uuid)


def _budget_table(seance, table_uuid: str) -> BudgetTable:
    depuis = bd.borne_de_remise(seance, table_uuid,
                               Journal.ENLUMINURE_CREDITEE)
    def compte(action):
        requete = (select(func.count()).select_from(Journal)
                   .where(Journal.objet_uuid == table_uuid,
                          Journal.action == action))
        if depuis is not None:
            requete = requete.where(Journal.horodatage > depuis)
        return seance.scalar(requete) or 0

    affichees = seance.scalar(
        select(func.count()).select_from(Photo)
        .where(Photo.table_uuid == table_uuid, Photo.portee == "table",
               Photo.supprimee.is_(False))) or 0
    return BudgetTable(
        affichees=affichees,
        # Un échec de conversion est NOTRE défaut : il ne se décompte pas.
        envois=max(0, compte(Journal.ENLUMINURE_DEPOSEE)
                   - compte(Journal.ENLUMINURE_ECHOUEE)),
        suppressions=compte(Journal.ENLUMINURE_RETIREE),
        max_affichees=int(config.parametre("quotas.photos_de_table", 5)),
        max_envois=int(config.parametre("quotas.uploads_table", 10)),
        max_suppressions=int(config.parametre("quotas.suppressions_table", 5)),
    )


def enluminures(table_uuid: str) -> list[Photo]:
    """Les enluminures vivantes de cette table, la plus récente en tête."""
    with bd.Seance() as seance:
        return list(seance.scalars(
            select(Photo).where(Photo.table_uuid == table_uuid,
                                Photo.portee == "table",
                                Photo.supprimee.is_(False))
            .order_by(Photo.creee_le.desc())))


def maximum_depots() -> int:
    depots = config.parametre("quotas.photo_par_personne", DEPOTS_PAR_DEFAUT)
    modifs = config.parametre("quotas.modifications_photo",
                              MODIFICATIONS_PAR_DEFAUT)
    return int(depots) + int(modifs)


def _compter(seance, personne_uuid: str, action: str, depuis=None) -> int:
    requete = (select(func.count()).select_from(Journal)
               .where(Journal.acteur_personne_uuid == personne_uuid,
                      Journal.action == action))
    if depuis is not None:
        requete = requete.where(Journal.horodatage > depuis)
    return seance.scalar(requete) or 0


def budget(personne_uuid: str) -> Budget:
    with bd.Seance() as seance:
        return _budget(seance, personne_uuid)


def _budget(seance, personne_uuid: str) -> Budget:
    """Tout se recompte depuis la dernière remise à zéro.

    Trois termes, deux en soustraction : ce que l'invité a déposé, moins ce que
    NOUS avons raté (EX-PHO-33), moins ce que l'administrateur a rendu
    (EX-ADM-10). Aucun compteur en base — c'est la sixième grandeur du projet à
    suivre la règle.
    """
    depuis = bd.borne_de_remise(seance, personne_uuid,
                                Journal.PHOTO_CREDITS_REMIS,
                                colonne=Journal.acteur_personne_uuid)
    return Budget(
        deposes=_compter(seance, personne_uuid, Journal.PHOTO_DEPOSEE, depuis),
        echecs=_compter(seance, personne_uuid, Journal.PHOTO_ECHOUEE, depuis),
        rendus=_compter(seance, personne_uuid, Journal.PHOTO_CREDITEE, depuis),
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


def deposer(personne_uuid: str, octets: bytes, est_test: bool = False,
            sans_consommer: bool = False, table_uuid: str | None = None) -> Photo:
    """Écrit l'original, journalise, met la conversion en file. Rend la main.

    `EX-PHO-10` — l'application répond immédiatement. La conversion, le
    redimensionnement et la vignette s'exécutent en tâche de fond.
    `EX-PHO-11` — l'original est écrit **avant** tout, et n'est jamais retouché.
    """
    forme = verifier(octets)

    with bd.Seance() as seance:
        # EX-ADM-10 — l'administrateur agit sans limite. Il passe par la MÊME
        # fonction : un second chemin de dépôt divergerait du premier au
        # prochain changement de règle, et c'est celui qu'on relit le moins
        # qui garderait l'ancienne. Même raison pour la portée `table` :
        # l'enluminure suit le chemin de la photo personnelle, seuls le budget
        # et la ligne de journal diffèrent.
        if table_uuid is not None:
            etat_table = _budget_table(seance, table_uuid)
            if not etat_table.peut_deposer and not sans_consommer:
                raise RefusPhoto(
                    "Votre table a ses cinq enluminures."
                    if etat_table.affichees >= etat_table.max_affichees
                    else "Vous avez utilisé vos dix envois pour cette table.")
        else:
            etat_budget = _budget(seance, personne_uuid)
            if etat_budget.epuise and not sans_consommer:
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

        # EX-CDT-15 — une table porte CINQ enluminures ; une personne porte UNE
        # photo. Le remplacement automatique n'a donc de sens que pour la
        # seconde : côté table, on ajoute, et l'on supprime à la main.
        ancienne = None
        if table_uuid is None:
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
            table_uuid=table_uuid,
            portee="table" if table_uuid else "personnelle",
            est_test=est_test,
            chemin_original=relatif,
            etat="traitement",
        )
        seance.add(photo)
        # Le budget de table s'ancre sur la TABLE, celui de la personne sur la
        # personne : le rôle peut changer de main, le budget appartient à la
        # table. Compter sur l'acteur ferait repartir le compte à zéro le jour
        # où l'administrateur désigne un autre Gardien.
        if table_uuid:
            bd.journaliser(
                seance, Journal.ENLUMINURE_DEPOSEE, objet_uuid=table_uuid,
                objet_type="table", acteur=personne_uuid,
                details={"photo": identifiant, "forme": forme,
                         "octets": len(octets)})
        else:
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


# --------------------------------------------------------------------------- #
# La conversion (EX-PHO-10, EX-PHO-11, EX-PHO-33)
# --------------------------------------------------------------------------- #

# Mesuré au morceau A : de 1,6 à 24,5 Mpx, de 514 ko à 5,25 Mo. 1600 couvre un
# téléphone à trois fois la densité et un écran d'ordinateur ; le recueil
# imprimé tirera sur l'original, qui reste intact.
COTE_WEB = 1600
COTE_VIGNETTE = 400
QUALITE_WEB = 85
QUALITE_VIGNETTE = 80

# Garde-fou contre une image-bombe : 24,5 Mpx au pire des relevés réels, on
# laisse quatre fois la marge. Au-delà, refus définitif — décompresser une
# image de deux gigapixels tuerait le conteneur, et avec lui la soirée.
PIXELS_MAX = 100_000_000


def _preparer(image):
    """Oriente, aplatit la transparence, ramène en RVB.

    `exif_transpose` ne suppose **jamais** qu'un EXIF existe : mesuré au
    morceau A, la photo de galerie Android n'en portait aucun et arrivait déjà
    dans le bon sens. Sans EXIF, l'image ressort inchangée.
    """
    from PIL import ImageOps

    image = ImageOps.exif_transpose(image) or image
    if image.mode in ("RGBA", "LA", "P"):
        from PIL import Image as _Image

        image = image.convert("RGBA")
        fond = _Image.new("RGB", image.size, (255, 255, 255))
        fond.paste(image, mask=image.split()[-1])
        return fond
    return image.convert("RGB")


def convertir(photo_uuid: str) -> None:
    """Produit les versions web et vignette. Traitant de `conversion_image`.

    **L'original n'est jamais retouché** (`EX-PHO-11`) : on le lit, on n'y
    écrit pas. Les deux dérivés sont écrits AVANT la mise à jour de la ligne :
    une photo annoncée `prete` dont le fichier n'existerait pas encore
    donnerait un cadre vide sur le téléphone de l'invité.

    *Effet de bord voulu :* Pillow n'écrit pas l'EXIF si on ne le lui passe
    pas. Les versions web et vignette partent donc **sans coordonnées GPS ni
    modèle d'appareil**, alors que l'original les garde sur le volume, derrière
    le mot de passe d'administration. C'est la version web qui circulera dans
    le recueil.
    """
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = PIXELS_MAX

    with bd.Seance() as seance:
        photo = seance.get(Photo, photo_uuid)
        if photo is None:
            raise taches.EchecDefinitif(f"photo {photo_uuid} introuvable")
        relatif = photo.chemin_original
        est_supprimee = photo.supprimee

    if est_supprimee:
        # Remplacée pendant que la tâche attendait : convertir la précédente
        # écraserait la nouvelle dans l'affichage. Rien à faire, et ce n'est
        # pas un échec — l'invité n'a rien à se voir rendre.
        return

    source = _dossier("originaux") / relatif
    if not source.is_file():
        raise taches.EchecDefinitif(f"original absent : {relatif}")

    try:
        with Image.open(source) as image:
            image.load()            # force le décodage : un fichier tronqué
            prepare = _preparer(image)  # échoue ici, pas au moment d'écrire
            web = prepare.copy()
            web.thumbnail((COTE_WEB, COTE_WEB), Image.LANCZOS)
            vignette = prepare.copy()
            vignette.thumbnail((COTE_VIGNETTE, COTE_VIGNETTE), Image.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        # Un format que Pillow ne sait pas lire ne le saura pas davantage au
        # troisième essai : définitif, jamais différé.
        raise taches.EchecDefinitif(
            f"image illisible ({type(exc).__name__} — {exc})") from exc

    nom = f"{photo_uuid}.jpg"
    for image, dossier, qualite in ((web, "web", QUALITE_WEB),
                                    (vignette, "vignettes", QUALITE_VIGNETTE)):
        cible = _dossier(dossier) / nom
        cible.parent.mkdir(parents=True, exist_ok=True)
        image.save(cible, "JPEG", quality=qualite, optimize=True)

    with bd.Seance() as seance:
        photo = seance.get(Photo, photo_uuid)
        if photo is None or photo.supprimee:
            return
        photo.chemin_web = nom
        photo.chemin_vignette = nom
        photo.etat = "prete"
        seance.commit()

    # EX-SAU-01 — la copie part UNE fois la conversion faite : plus tôt, il n'y
    # aurait qu'un original à déposer, et il faudrait repasser sur les deux
    # fournisseurs pour les deux dérivés. Elle est en file séparée et de plus
    # basse priorité : une photo lente à sauvegarder ne doit pas retarder la
    # conversion de la suivante, que l'invité, lui, attend.
    taches.mettre_en_file("copie_stockage_objet", photo_uuid)


def marquer_echec(photo_uuid: str, erreur: str) -> None:
    """Crochet d'échec définitif de `conversion_image`.

    `EX-PHO-33` — l'état `echouee` signifie échec de **conversion**, pas
    d'envoi : l'original est intact sur le volume. Le crédit est donc rendu,
    par une ligne de journal comptée en soustraction — le budget reste dérivé,
    aucun compteur n'est touché.

    **Idempotent** : deux passages ne rendent qu'un crédit. Sans ce contrôle,
    une tâche rejouée offrirait des dépôts supplémentaires à chaque échec.
    """
    with bd.Seance() as seance:
        photo = seance.get(Photo, photo_uuid)
        if photo is None or photo.etat == "echouee":
            return
        photo.etat = "echouee"
        # **Le crédit doit revenir au budget qui a payé.** Une enluminure
        # créditée sur la personne offrirait un dépôt de photo personnelle au
        # Gardien et en retirerait un à sa table — faux dans les deux sens, et
        # silencieux. Le sujet d'un budget n'est pas toujours celui qui agit.
        if photo.portee == "table" and photo.table_uuid:
            bd.journaliser(
                seance, Journal.ENLUMINURE_ECHOUEE, objet_uuid=photo.table_uuid,
                objet_type="table", acteur=photo.personne_uuid,
                details={"photo": photo_uuid, "erreur": erreur[:300]})
        else:
            bd.journaliser(
                seance, Journal.PHOTO_ECHOUEE, objet_uuid=photo_uuid,
                objet_type="photo", acteur=photo.personne_uuid,
                details={"erreur": erreur[:300]})
        seance.commit()


def reprendre_conversions_perdues() -> int:
    """Remet en file les photos restées en traitement sans tâche vivante.

    Même raisonnement qu'`EX-ARC-11` pour les tâches interrompues : un état
    intermédiaire sans rien pour le faire avancer est un état définitif qui
    s'ignore. Couvre le redémarrage en plein travail — et les photos déposées
    avant que le traitant n'existe, qui seraient restées « en préparation »
    jusqu'au 5 septembre.

    Ne boucle pas : une conversion qui échoue définitivement fait passer la
    photo en `echouee`, donc hors de cette requête.
    """
    from modeles import Tache

    with bd.Seance() as seance:
        vivantes = set(seance.scalars(
            select(Tache.objet_uuid).where(
                Tache.type == "conversion_image",
                Tache.etat.in_(("en_attente", "en_cours")))))
        perdues = [p for p in seance.scalars(
            select(Photo).where(Photo.etat == "traitement",
                                Photo.supprimee.is_(False)))
            if p.uuid not in vivantes]
        identifiants = [p.uuid for p in perdues]

    for identifiant in identifiants:
        taches.mettre_en_file("conversion_image", identifiant)
    return len(identifiants)


# --------------------------------------------------------------------------- #
# Ce que l'administrateur peut faire (EX-ADM-10, EX-ADM-11)
# --------------------------------------------------------------------------- #

def crediter(personne_uuid: str, tout: bool = False,
             par: str = "admin") -> Budget:
    """Rend un crédit de photo, ou les rend tous.

    **Un crédit est une quantité, tout rendre est une date.** La borne est
    idempotente : deux appuis en posent deux, la dernière gagne, le résultat
    est identique. Des lignes de compensation, elles, s'additionneraient — et
    un double appui sur un réseau lent offrirait huit dépôts au lieu de quatre.
    """
    with bd.Seance() as seance:
        bd.journaliser(
            seance,
            Journal.PHOTO_CREDITS_REMIS if tout else Journal.PHOTO_CREDITEE,
            objet_uuid=personne_uuid, objet_type="personne",
            acteur=personne_uuid, pour_le_compte_de=par)
        seance.commit()
    return budget(personne_uuid)


def retirer(photo_uuid: str, par: str | None = None) -> bool:
    """Suppression douce (`EX-GEN-03`) : la ligne se marque, le fichier reste.

    **Ne débite rien.** `EX-PHO-37` compte les *modifications*, et une
    modification est « une suppression **suivie d'un nouvel envoi** » : c'est le
    dépôt suivant qui coûte, jamais le retrait. C'est aussi ce que veut
    `EX-PHO-33` pour une photo dont la conversion a échoué.
    """
    with bd.Seance() as seance:
        photo = seance.get(Photo, photo_uuid)
        if photo is None or photo.supprimee:
            return False
        photo.supprimee = True
        photo.supprimee_le = config.maintenant()
        bd.journaliser(seance, Journal.PHOTO_RETIREE, objet_uuid=photo_uuid,
                       objet_type="photo", acteur=photo.personne_uuid,
                       pour_le_compte_de=par,
                       details={"etat_au_retrait": photo.etat})
        seance.commit()
        return True


def deposer_pour(personne_uuid: str, octets: bytes, par: str = "admin",
                 est_test: bool = False) -> Photo:
    """Dépôt par l'administrateur, **sans consommer** (`EX-ADM-10`).

    Le budget épuisé ne s'oppose pas à lui : il agit sans limite. Le geste est
    identique à celui de l'invité — mêmes contrôles, même conversion —, seule
    la ligne de journal diffère, et elle dit au nom de qui.

    Rendre un crédit *puis* déposer donnerait le même résultat en deux gestes ;
    ce raccourci existe parce qu'à 21 h, deux gestes valent un oubli.
    """
    photo = deposer(personne_uuid, octets, est_test=est_test,
                    sans_consommer=True)
    with bd.Seance() as seance:
        bd.journaliser(seance, Journal.PHOTO_CREDITEE,
                       objet_uuid=personne_uuid, objet_type="personne",
                       acteur=personne_uuid, pour_le_compte_de=par,
                       details={"motif": "dépôt par l'administrateur",
                                "photo": photo.uuid})
        seance.commit()
    return photo


# --------------------------------------------------------------------------- #
# La copie hors du volume (EX-SAU-01)
# --------------------------------------------------------------------------- #

# Ce qu'on copie, et dans quel ordre d'importance. L'original d'abord : c'est
# le seul irremplaçable — le web et la vignette se reconstruisent à partir de
# lui, alors que lui ne se reconstruit de rien.
VARIANTES_COPIEES = ("originaux", "web", "vignettes")


def _a_copier(photo: Photo) -> list[tuple[str, str]]:
    chemins = {"originaux": photo.chemin_original, "web": photo.chemin_web,
               "vignettes": photo.chemin_vignette}
    return [(v, chemins[v]) for v in VARIANTES_COPIEES if chemins[v]]


def copier(photo_uuid: str) -> None:
    """Dépose les trois fichiers sur les deux stockages. Traitant de
    `copie_stockage_objet`.

    **La copie ne touche jamais l'état de la photo.** Un dépôt objet
    indisponible est un défaut de sauvegarde, pas un défaut de photo : l'invité
    n'a rien à savoir, et sa chronique s'affiche exactement pareil. C'est le
    tableau de bord qui doit le dire, à celui qui peut y remédier.

    Le préfixe vient de `depot_objet.prefixe_projet()`, donc de
    `projet-actif.txt` — jamais tapé à la main. C'est ce qui a manqué le jour
    où des sauvegardes sont parties dans un préfixe orphelin.
    """
    with bd.Seance() as seance:
        photo = seance.get(Photo, photo_uuid)
        if photo is None:
            raise taches.EchecDefinitif(f"photo {photo_uuid} introuvable")
        fichiers = _a_copier(photo)
        est_test = bool(photo.est_test)

    if not depot_objet.depots_actifs():
        # Aucune destination configurée : ce n'est pas un échec, c'est un
        # projet de développement. Échouer ici remplirait la file de rouge
        # sur un poste où il n'y a rien à sauvegarder.
        return
    if not fichiers:
        raise taches.EchecDefinitif("aucun fichier à copier")

    manques, deposes = [], 0
    for variante, relatif in fichiers:
        source = _dossier(variante) / relatif
        if not source.is_file():
            manques.append(f"{variante}/{relatif} absent du volume")
            continue
        resultats = depot_objet.deposer_partout(
            f"photos/{variante}/{relatif}", source.read_bytes())
        for r in resultats:
            if r.succes:
                deposes += 1
            else:
                manques.append(f"{variante} → {r.destination} : {r.erreur}")

    with bd.Seance() as seance:
        bd.journaliser(
            seance,
            Journal.PHOTO_COPIEE if not manques else Journal.PHOTO_COPIE_ECHOUEE,
            objet_uuid=photo_uuid, objet_type="photo",
            details={"fichiers": len(fichiers), "depots": deposes,
                     "test": est_test,
                     **({"manques": manques[:6]} if manques else {})})
        seance.commit()

    if manques:
        # Temporaire, jamais définitif : un fournisseur qui ne répond pas
        # maintenant répondra peut-être dans quatre secondes, et la photo est
        # toujours sur le volume en attendant.
        raise taches.EchecTemporaire(" · ".join(manques[:3]))


def copiees() -> set[str]:
    """Les photos dont la copie a réussi au moins une fois.

    Dérivé du journal (`EX-GEN-07`) : interroger les deux fournisseurs à chaque
    affichage serait lent, et faux dès que l'un des deux ne répond pas.
    """
    with bd.Seance() as seance:
        return set(seance.scalars(
            select(Journal.objet_uuid).where(
                Journal.action == Journal.PHOTO_COPIEE)))


def reprendre_copies_manquantes() -> int:
    """Met en file la copie des photos prêtes qui n'ont jamais été copiées.

    Même raisonnement que `reprendre_conversions_perdues` : couvre le
    redémarrage en plein travail, un dépôt objet indisponible toute la soirée,
    et les photos déposées avant que la copie n'existe. Ne boucle pas — une
    copie réussie sort la photo de la requête.
    """
    if not depot_objet.depots_actifs():
        return 0
    from modeles import Tache

    deja = copiees()
    with bd.Seance() as seance:
        vivantes = set(seance.scalars(
            select(Tache.objet_uuid).where(
                Tache.type == "copie_stockage_objet",
                Tache.etat.in_(("en_attente", "en_cours")))))
        manquantes = [p.uuid for p in seance.scalars(
            select(Photo).where(Photo.etat == "prete",
                                Photo.supprimee.is_(False)))
            if p.uuid not in deja and p.uuid not in vivantes]

    for identifiant in manquantes:
        taches.mettre_en_file("copie_stockage_objet", identifiant)
    return len(manquantes)
