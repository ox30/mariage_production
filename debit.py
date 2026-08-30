"""Ce que l'API dit de notre palier, à chaque réponse.

**Pourquoi ce module existe.** Le point 8 de l'annexe C demandait de lire le
palier de débit sur la console Anthropic. C'est une lecture ponctuelle, hors de
l'application : périmée le lendemain, et invisible le 5 septembre au moment où
elle compterait.

Or l'API le dit d'elle-même. Chaque réponse porte, pour chacun des trois axes —
requêtes, jetons d'entrée, jetons de sortie — la limite, ce qu'il en reste et
l'instant de réinitialisation. Le palier est donc dans nos mains à chaque
génération, sans rien aller chercher.

**Ce module ne régule rien.** Il relève et il affiche. `taches.py` réessaie
déjà sur `ErreurDebit` en respectant le `retry-after` ; ajouter une régulation
proactive à onze jours de l'événement coûterait plus de risque qu'elle n'en
retire, d'autant que les mesures donnent 59 % du plafond de sortie à huit fils.

**Le relevé n'est pas persisté.** Un plafond restant d'il y a trois heures ne
dit rien — les compteurs se réinitialisent à la minute. Le garder en base
donnerait un chiffre qu'on croirait actuel. Il vit en mémoire, et il porte son
âge : sans âge, un relevé est un piège.
"""

from __future__ import annotations

import threading
import time

# Les trois axes, dans l'ordre où ils saturent en pratique : la sortie d'abord.
# Mesuré sur ce projet — huit fils consomment 59 % du plafond de sortie, 24 %
# de celui d'entrée et 3 % de celui des requêtes.
AXES = (
    ("sortie", "anthropic-ratelimit-output-tokens"),
    ("entree", "anthropic-ratelimit-input-tokens"),
    ("requetes", "anthropic-ratelimit-requests"),
)

_verrou = threading.Lock()
_dernier: dict | None = None


def _entier(valeur) -> int | None:
    try:
        return int(str(valeur).strip())
    except (TypeError, ValueError):
        return None


def lire_entetes(entetes) -> dict:
    """Extrait les axes présents. Un en-tête absent n'est jamais inventé.

    L'API peut ne pas tous les envoyer — derrière un espace de travail, les
    en-têtes portent la limite la plus contraignante et non les trois. Un axe
    manquant est donc omis, pas mis à zéro : zéro voudrait dire « plus de
    budget », ce qui est le contraire de « on ne sait pas ».
    """
    releve = {}
    for axe, prefixe in AXES:
        limite = _entier(entetes.get(f"{prefixe}-limit"))
        reste = _entier(entetes.get(f"{prefixe}-remaining"))
        if limite is None and reste is None:
            continue
        releve[axe] = {"limite": limite, "reste": reste,
                       "reinitialise_le": entetes.get(f"{prefixe}-reset")}
    return releve


def noter(entetes) -> dict:
    """Retient le dernier relevé. Appelé par `ia.py` après chaque réponse."""
    releve = lire_entetes(entetes)
    if not releve:
        return {}
    global _dernier
    with _verrou:
        _dernier = {"axes": releve, "mesure_a": time.monotonic()}
    return releve


def dernier() -> dict | None:
    """Le dernier relevé avec son ÂGE, ou `None` si aucun n'a eu lieu.

    L'âge est calculé à la lecture et non stocké : un relevé de trois heures
    doit se voir comme tel. Sans lui, on lirait « reste 74 200 » en croyant
    que c'est maintenant.
    """
    with _verrou:
        if _dernier is None:
            return None
        instantane = dict(_dernier)
    instantane["age_s"] = int(time.monotonic() - instantane.pop("mesure_a"))
    for axe in instantane["axes"].values():
        limite, reste = axe["limite"], axe["reste"]
        axe["part_utilisee"] = (
            round(100 * (limite - reste) / limite) if limite and reste is not None
            and limite > 0 else None)
    return instantane


def oublier() -> None:
    """Remet à zéro. Sert aux tests, et au redémarrage implicitement."""
    global _dernier
    with _verrou:
        _dernier = None
