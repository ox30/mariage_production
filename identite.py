"""Le cookie d'appareil — un raccourci, jamais un droit (EX-AUTH-02).

**Ce qu'il est.** Une valeur aléatoire posée sur le téléphone, et une ligne en
base qui dit « ce téléphone, c'est cette personne ». Rien de plus.

**Ce qu'il n'est pas.** Une autorisation. Le perdre ne coûte aucun droit : on
ressaisit le mot de passe du carton, on retrouve son nom, sa chronique et ses
crédits restants. Les quotas sont rattachés à la **personne** (`EX-AUTH-03`),
jamais à l'appareil — sans quoi effacer ses cookies rendrait trois générations
neuves, et un téléphone prêté en volerait autant.

**Ce qu'il ne décide pas.** `EX-AUTH-06` — l'attribution est figée au moment de
la création. Deux personnes peuvent se succéder sur le même téléphone : le
rattachement suit la dernière, mais les chroniques déjà écrites gardent
l'appareil de leur naissance. Réécrire après coup ferait changer de main un
personnage déjà publié.

Distinct du cookie d'accès (`acces.py`), qui dit seulement « cette personne a
lu le carton ». L'un ouvre la porte, l'autre reconnaît qui entre.
"""

from __future__ import annotations

import uuid as _uuid

import acces

NOM_COOKIE = "appareil"
# Aussi long que le cookie d'accès : les deux se perdent ensemble quand on
# efface ses données de navigation, et il n'y a aucune raison que l'un survive
# à l'autre.
DUREE_COOKIE_S = acces.DUREE_COOKIE_S


def nouveau() -> str:
    return str(_uuid.uuid4())


def du_requete(request) -> str | None:
    return request.cookies.get(NOM_COOKIE)


def poser(reponse, entetes, valeur: str) -> None:
    """EX-SEC-07 — mêmes attributs que le cookie d'accès.

    `Secure` conditionné à HTTPS pour la même raison : posé en clair, il ne
    serait jamais renvoyé en local, et l'appareil ne serait jamais reconnu.
    """
    reponse.set_cookie(
        NOM_COOKIE, valeur,
        max_age=DUREE_COOKIE_S,
        httponly=True,
        samesite="lax",
        secure=acces.en_https(entetes),
        path="/",
    )
