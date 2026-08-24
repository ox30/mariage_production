"""Dépôts objets — instantanés de la base et médias (EX-SAU-19 à EX-SAU-22).

Le stockage est **doublé chez deux fournisseurs distincts**, un bucket Railway
et un bucket Cloudflare R2. Un instantané n'a de valeur que s'il survit à la
perte de ce qui tourne ; hébergé sur la seule plateforme qui héberge le
service, il partagerait sa panne.

Trois propriétés gouvernent ce module.

**Les écritures sont indépendantes** (EX-SAU-20). L'échec ou la lenteur d'un
dépôt ne retarde ni ne bloque l'autre : un parcours séquentiel avec un long
délai d'attente ferait passer l'instantané de trois minutes à six sans que
personne s'en aperçoive.

**Une destination muette se signale au démarrage** (EX-SAU-21), pas à minuit.
Doubler les destinations double le risque qu'une clé soit fausse sans que
personne le voie ; la sonde écrit puis relit un objet d'essai sur chacune.

**Les identifiants vivent dans l'environnement** (EX-SAU-22), jamais dans
`config.yaml` : le volume est tiré par le Pi toutes les cinq minutes et part
dans l'archive d'administration. Y ranger les clés du stockage reviendrait à
mettre les clés du coffre à l'intérieur du coffre. Seule la **liste des
destinations actives** est dans `config.yaml`, parce que retirer un dépôt
devenu lent doit être possible sans redéployer (EX-SAU-09).
"""

from __future__ import annotations

import os
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import config

# Ordre par défaut si `config.yaml` ne dit rien. Railway d'abord : c'est celui
# dont les identifiants sont les plus faciles à retrouver un soir de panne.
DESTINATIONS_DEFAUT = ["railway", "r2"]

DELAI_S = 20.0


@dataclass(frozen=True, slots=True)
class Resultat:
    """Ce qu'une écriture a produit, pour la table `sauvegarde` (EX-SAU-05)."""

    destination: str
    succes: bool
    octets: int = 0
    erreur: str | None = None


class DepotObjet:
    """Contrat commun. Deux implémentations : locale et S3."""

    nom = "abstrait"

    def deposer(self, cle: str, contenu: bytes) -> int:
        raise NotImplementedError

    def lire(self, cle: str) -> bytes:
        raise NotImplementedError

    def supprimer(self, cle: str) -> None:
        raise NotImplementedError


class DepotLocal(DepotObjet):
    """Écrit dans un dossier. Sert au développement et aux tests.

    Ce n'est pas une sauvegarde au sens d'EX-SAU-19 — le dossier vit sur le
    même volume que la base — mais il permet d'éprouver toute la chaîne sans
    compte tiers ni réseau.
    """

    def __init__(self, racine: pathlib.Path, nom: str = "local"):
        self.racine = pathlib.Path(racine)
        self.nom = nom
        self.racine.mkdir(parents=True, exist_ok=True)

    def _chemin(self, cle: str) -> pathlib.Path:
        return self.racine / cle

    def deposer(self, cle: str, contenu: bytes) -> int:
        chemin = self._chemin(cle)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(contenu)
        return len(contenu)

    def lire(self, cle: str) -> bytes:
        return self._chemin(cle).read_bytes()

    def supprimer(self, cle: str) -> None:
        self._chemin(cle).unlink(missing_ok=True)


class DepotS3(DepotObjet):
    """Tout fournisseur compatible S3 : buckets Railway, Cloudflare R2, B2.

    Le client est créé paresseusement : construire un `DepotS3` ne doit pas
    ouvrir de connexion, sans quoi la simple lecture de la configuration
    ferait tomber le démarrage si un fournisseur est injoignable.
    """

    def __init__(self, nom: str, endpoint: str, cle_acces: str, secret: str,
                 bucket: str, region: str = "auto"):
        self.nom = nom
        self._endpoint = endpoint
        self._cle_acces = cle_acces
        self._secret = secret
        self._bucket = bucket
        # R2 exige `region_name="auto"` ; une région AWS ordinaire y produit
        # une erreur de signature difficile à lire.
        self._region = region or "auto"
        self._client = None
        self._verrou = threading.Lock()

    def _obtenir_client(self):
        if self._client is None:
            with self._verrou:
                if self._client is None:
                    import boto3
                    from botocore.config import Config as ConfigBoto
                    self._client = boto3.client(
                        "s3",
                        endpoint_url=self._endpoint,
                        aws_access_key_id=self._cle_acces,
                        aws_secret_access_key=self._secret,
                        region_name=self._region,
                        config=ConfigBoto(
                            signature_version="s3v4",
                            connect_timeout=int(DELAI_S),
                            read_timeout=int(DELAI_S),
                            # Le réessai appartient à la boucle appelante, qui
                            # repassera dans trois minutes. Insister ici
                            # allongerait le cycle sans rien gagner.
                            retries={"max_attempts": 1, "mode": "standard"},
                        ),
                    )
        return self._client

    def deposer(self, cle: str, contenu: bytes) -> int:
        self._obtenir_client().put_object(Bucket=self._bucket, Key=cle,
                                          Body=contenu)
        return len(contenu)

    def lire(self, cle: str) -> bytes:
        reponse = self._obtenir_client().get_object(Bucket=self._bucket, Key=cle)
        return reponse["Body"].read()

    def supprimer(self, cle: str) -> None:
        self._obtenir_client().delete_object(Bucket=self._bucket, Key=cle)


# --------------------------------------------------------------------------- #
# Construction depuis l'environnement
# --------------------------------------------------------------------------- #

def _depuis_environnement(nom: str) -> DepotS3 | None:
    """Construit un dépôt S3 si ses quatre variables sont posées.

    Nommage propre au projet plutôt que les variables AWS standard : deux
    fournisseurs coexistent, et `AWS_ACCESS_KEY_ID` ne peut pas désigner les
    deux à la fois.
    """
    prefixe = f"STOCKAGE_{nom.upper()}_"
    endpoint = os.environ.get(prefixe + "ENDPOINT", "").strip()
    cle = os.environ.get(prefixe + "CLE", "").strip()
    secret = os.environ.get(prefixe + "SECRET", "").strip()
    bucket = os.environ.get(prefixe + "BUCKET", "").strip()
    if not (endpoint and cle and secret and bucket):
        return None
    return DepotS3(nom, endpoint, cle, secret, bucket,
                   os.environ.get(prefixe + "REGION", "auto").strip() or "auto")


def destinations_demandees() -> list[str]:
    """Liste lue dans `config.yaml`, relue à chaud (EX-SAU-22).

    Retirer un dépôt devenu lent ne doit pas demander de redéploiement :
    `EX-SAU-09` l'interdit pendant toute la soirée.
    """
    valeur = config.parametre("sauvegarde.destinations", DESTINATIONS_DEFAUT)
    if isinstance(valeur, str):
        valeur = [valeur]
    return [str(v).strip().lower() for v in (valeur or []) if str(v).strip()]


def depots_actifs() -> list[DepotObjet]:
    """Les dépôts réellement utilisables, dans l'ordre demandé.

    Un nom demandé sans identifiants n'est pas une erreur fatale — le service
    doit démarrer — mais la sonde le signalera bruyamment (EX-SAU-21).
    """
    actifs: list[DepotObjet] = []
    for nom in destinations_demandees():
        if nom == "local":
            actifs.append(DepotLocal(config.projet().dossier_instantanes, "local"))
            continue
        depot = _depuis_environnement(nom)
        if depot is not None:
            actifs.append(depot)
    return actifs


def prefixe_projet() -> str:
    """`EX-SAU-19` — un seul bucket par fournisseur, préfixé par le projet.

    Le préfixe ne se tape jamais à la main : il vient de `projet-actif.txt`,
    donc d'un seul endroit. C'est ce qui rend l'isolation logique acceptable
    ici, alors qu'`EX-PRJ-03` l'interdit dans la base — une colonne
    `projet_id` devrait être filtrée dans chaque requête.
    """
    return f"mariage/{config.projet().identifiant}"


def cle(*morceaux: str) -> str:
    return "/".join([prefixe_projet(), *[m.strip("/") for m in morceaux]])


# --------------------------------------------------------------------------- #
# Écriture et sonde
# --------------------------------------------------------------------------- #

def deposer_partout(chemin_relatif: str, contenu: bytes,
                    depots: list[DepotObjet] | None = None) -> list[Resultat]:
    """Écrit sur toutes les destinations, **en parallèle** (EX-SAU-20).

    Séquentiellement, un dépôt qui met vingt secondes à répondre ferait passer
    la boucle d'instantané de trois minutes à six sans que rien ne le dise.
    """
    depots = depots_actifs() if depots is None else depots
    if not depots:
        return []
    identifiant = cle(chemin_relatif)
    resultats: list[Resultat] = []
    with ThreadPoolExecutor(max_workers=len(depots),
                            thread_name_prefix="depot") as pool:
        travaux = {pool.submit(d.deposer, identifiant, contenu): d for d in depots}
        for travail in as_completed(travaux):
            depot = travaux[travail]
            try:
                octets = travail.result()
                resultats.append(Resultat(depot.nom, True, octets))
            except Exception as exc:
                resultats.append(
                    Resultat(depot.nom, False, 0, f"{type(exc).__name__} — {exc}"))
    return sorted(resultats, key=lambda r: r.destination)


def sonder(depots: list[DepotObjet] | None = None) -> list[Resultat]:
    """EX-SAU-21 — écrit puis **relit** un objet d'essai sur chaque dépôt.

    Écrire ne suffit pas : une clé en écriture seule, un bucket mal nommé ou
    une région erronée peuvent laisser un `put` réussir en apparence. La
    relecture est le seul contrôle qui prouve que l'objet est vraiment là.
    """
    depots = depots_actifs() if depots is None else depots
    temoin = f"sonde-{config.maintenant():%Y%m%dT%H%M%S}.txt"
    attendu = b"sonde de demarrage"
    resultats: list[Resultat] = []
    for depot in depots:
        identifiant = cle("sondes", temoin)
        try:
            depot.deposer(identifiant, attendu)
            relu = depot.lire(identifiant)
            if relu != attendu:
                raise ValueError("le contenu relu diffère de celui écrit")
            resultats.append(Resultat(depot.nom, True, len(attendu)))
            try:
                depot.supprimer(identifiant)
            except Exception:
                # Une sonde qui traîne ne gêne personne ; échouer ici
                # masquerait un succès d'écriture et de relecture.
                pass
        except Exception as exc:
            resultats.append(
                Resultat(depot.nom, False, 0, f"{type(exc).__name__} — {exc}"))
    return resultats


def resume_sonde() -> str:
    """Ligne à joindre au résumé de démarrage, à côté de l'empreinte."""
    demandees = destinations_demandees()
    actifs = depots_actifs()
    manquantes = [n for n in demandees
                  if n not in {d.nom for d in actifs}]
    if not actifs and not manquantes:
        return "stockage objet  : aucune destination configurée"

    morceaux = []
    for resultat in sonder(actifs):
        morceaux.append(f"{resultat.destination} "
                        + ("OK" if resultat.succes else f"ÉCHEC ({resultat.erreur})"))
    for nom in manquantes:
        morceaux.append(f"{nom} SANS IDENTIFIANTS "
                        f"(STOCKAGE_{nom.upper()}_ENDPOINT/CLE/SECRET/BUCKET)")
    return f"stockage objet  : {' · '.join(morceaux)}  [{prefixe_projet()}/]"
