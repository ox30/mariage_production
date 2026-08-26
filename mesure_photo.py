"""Page de mesure JETABLE — morceau A de l'étape 3. À SUPPRIMER après relevé.

Elle ne fait pas partie de l'application : elle répond à quatre questions dont
dépendent les dépendances et le dessin du module Photo, et qu'on ne peut pas
deviner depuis un poste de développement.

1. **Quel format arrive vraiment** d'un iPhone et d'un Android ? Si le HEIC
   n'arrive jamais, `pillow-heif` n'entre pas dans l'image Docker.
2. **Quelle taille**, et quelles dimensions en pixels ? Fixe la cible de
   redimensionnement (EX-PHO-10).
3. **Combien de secondes en 4G** ? Décide si l'indicateur de progression
   d'EX-PHO-15 est visible ou terminé avant d'avoir été vu.
4. **L'aperçu `URL.createObjectURL` s'affiche-t-il** ? C'est la première moitié
   d'EX-PHO-26 — et un HEIC qui arriverait ne s'y afficherait pas.

Trois principes, tenus parce que cette page tourne sur le projet de répétition
déployé :

- **Éteinte par défaut.** La route n'existe pas sans `MESURE_PHOTO=1`. Un
  fichier qu'on oublierait de supprimer ne sert rien. Le défaut sûr est celui
  qui protège quand on oublie.
- **N'écrit rien.** Ni base, ni volume, ni stockage objet. Les relevés vivent
  en mémoire du processus — une seule instance (EX-ARC-05) — et disparaissent
  au redéploiement. Rien à nettoyer avant la bascule.
  *Réserve exacte : `python-multipart` déverse les corps volumineux dans un
  fichier temporaire du conteneur, jamais sur le volume monté.*
- **Aucune dépendance nouvelle.** Les formats sont reconnus à leurs octets de
  tête et les dimensions lues à la main. Ajouter Pillow ici fausserait la
  question à laquelle cette page doit répondre.

Elle est derrière la porte : `/mesure` n'est pas dans `CHEMINS_LIBRES`, donc le
middleware d'accès la protège comme le reste du parcours invité.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

routeur = APIRouter()

# Ce que le module Photo devra accepter, et ce qu'il devra refuser.
MARQUES_HEIF = {"heic", "heix", "hevc", "hevx", "heim", "heis", "hevm",
                "hevs", "mif1", "msf1"}
MARQUES_AVIF = {"avif", "avis"}
# EX-PHO-12 — aucune vidéo. Ces marques partagent le conteneur ISO-BMFF avec
# le HEIC : les distinguer se fait sur la marque, jamais sur l'extension.
MARQUES_VIDEO = {"isom", "iso2", "mp41", "mp42", "avc1", "qt  ", "M4V ",
                 "M4A ", "3gp4", "3gp5"}

# Dernier relevé en tête. Borné : la page se lit sur un téléphone.
RELEVES: list[dict] = []
MAX_RELEVES = 30


def actif() -> bool:
    """La route n'existe que si on l'a explicitement demandée.

    Lue à chaque appel et non figée en constante de module, pour que le test
    puisse éprouver les deux sens sans réimporter `main`.
    """
    return os.environ.get("MESURE_PHOTO", "") == "1"


def identifier(octets: bytes) -> str:
    """Le format réel, lu aux octets de tête — jamais au nom du fichier.

    Safari renomme les fichiers qu'il convertit (`tempImageXXXX.heic`), et
    l'extension d'un fichier venu d'un téléphone ne dit rien de son contenu.
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
    # Conteneur ISO-BMFF : HEIC, AVIF et MP4 partagent la même enveloppe, seule
    # la marque les distingue.
    if octets[4:8] == b"ftyp":
        marque = octets[8:12].decode("ascii", "replace")
        if marque in MARQUES_HEIF:
            return f"heif ({marque})"
        if marque in MARQUES_AVIF:
            return f"avif ({marque})"
        if marque in MARQUES_VIDEO:
            return f"VIDÉO ({marque})"
        return f"iso-bmff inconnu ({marque})"
    return "inconnu"


def _dimensions_jpeg(o: bytes) -> tuple[int, int] | None:
    """Parcourt les segments jusqu'au SOF. Défensif : rend None au moindre doute.

    Le SOF n'est pas à un décalage fixe — un EXIF portant une vignette le
    repousse de plusieurs kilo-octets. D'où le parcours, et non une lecture à
    une position devinée.
    """
    i, n = 2, len(o)
    while i + 9 < n:
        if o[i] != 0xFF:
            return None
        marqueur = o[i + 1]
        if marqueur == 0xFF:          # octet de bourrage
            i += 1
            continue
        if marqueur in (0xD8, 0x01) or 0xD0 <= marqueur <= 0xD7:
            i += 2                    # segments sans longueur
            continue
        if marqueur == 0xDA:          # début des données : le SOF est passé
            return None
        longueur = int.from_bytes(o[i + 2:i + 4], "big")
        if longueur < 2:
            return None
        # SOF0..SOF15, sauf DHT (C4), JPG (C8) et DAC (CC).
        if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):
            hauteur = int.from_bytes(o[i + 5:i + 7], "big")
            largeur = int.from_bytes(o[i + 7:i + 9], "big")
            return largeur, hauteur
        i += 2 + longueur
    return None


def dimensions(octets: bytes, forme: str) -> tuple[int, int] | None:
    """Largeur et hauteur, pour les seuls formats lisibles sans bibliothèque.

    Rend None pour le HEIF : si du HEIF arrive, la réponse est de toute façon
    « il faut un décodeur », et la mesure a rempli son office.
    """
    try:
        if forme == "png" and len(octets) >= 24:
            return (int.from_bytes(octets[16:20], "big"),
                    int.from_bytes(octets[20:24], "big"))
        if forme == "gif" and len(octets) >= 10:
            return (int.from_bytes(octets[6:8], "little"),
                    int.from_bytes(octets[8:10], "little"))
        if forme == "jpeg":
            return _dimensions_jpeg(octets)
    except Exception:
        return None
    return None


def porte_exif(octets: bytes) -> bool:
    """Un EXIF présent porte l'orientation ; absent, la date de prise aussi."""
    return b"Exif\x00\x00" in octets[:65536]


def _lisible(n: int) -> str:
    return f"{n / 1_048_576:.2f} Mo" if n >= 1_048_576 else f"{n / 1024:.0f} ko"


@routeur.get("/mesure", response_class=HTMLResponse)
def page(request: Request):
    from main import gabarits          # import tardif : ce module reste jetable
    reponse = gabarits.TemplateResponse(
        request, "mesure.html", {"releves": RELEVES})
    # `blob:` est INDISPENSABLE à l'aperçu d'EX-PHO-26 et absent de la CSP du
    # projet. Posé ici seulement : le middleware emploie `setdefault`, donc il
    # respecte cet en-tête. La CSP globale n'est pas touchée pour une page
    # jetable — la question de sa modification se pose au morceau B.
    reponse.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'")
    return reponse


@routeur.post("/mesure")
async def relever(fichier: UploadFile = File(...),
                  origine: str = Form(""),
                  appareil: str = Form("")):
    debut = time.monotonic()
    octets = await fichier.read()
    duree_lecture_ms = int((time.monotonic() - debut) * 1000)

    forme = identifier(octets)
    taille = dimensions(octets, forme)
    releve = {
        "horodatage": time.strftime("%H:%M:%S"),
        "origine": origine or "?",
        "appareil": (appareil or "?")[:120],
        "nom_annonce": (fichier.filename or "?")[:80],
        "type_annonce": fichier.content_type or "?",
        "forme_reelle": forme,
        "octets": len(octets),
        "octets_lisible": _lisible(len(octets)),
        "dimensions": f"{taille[0]}×{taille[1]}" if taille else "—",
        "megapixels": round(taille[0] * taille[1] / 1e6, 1) if taille else None,
        "exif": porte_exif(octets),
        "lecture_ms": duree_lecture_ms,
        "envoi_ms": None,
        "evenements_progression": None,
    }
    RELEVES.insert(0, releve)
    del RELEVES[MAX_RELEVES:]
    # Le journal Railway garde la trace quand l'écran du téléphone s'éteint.
    print(f"MESURE PHOTO | {releve['origine']} | annoncé "
          f"{releve['type_annonce']} « {releve['nom_annonce']} » | RÉEL "
          f"{forme} | {releve['octets_lisible']} | {releve['dimensions']} | "
          f"exif {'oui' if releve['exif'] else 'non'} | lecture "
          f"{duree_lecture_ms} ms", flush=True)
    return JSONResponse(releve)


@routeur.post("/mesure/duree")
async def duree_client(envoi_ms: int = Form(...), evenements: int = Form(0)):
    """La durée d'envoi ne se mesure que côté client.

    Le serveur ne voit pas quand le téléphone a commencé à émettre : il ne
    connaît que le temps de lecture d'un corps déjà arrivé. C'est pourtant la
    durée vécue qui décide de l'indicateur de progression (EX-PHO-15).
    """
    if RELEVES:
        RELEVES[0]["envoi_ms"] = envoi_ms
        RELEVES[0]["evenements_progression"] = evenements
        print(f"MESURE PHOTO | envoi vécu {envoi_ms} ms | "
              f"{evenements} événements de progression", flush=True)
    return JSONResponse({"ok": True})
