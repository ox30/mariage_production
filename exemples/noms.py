"""Normalisation des noms saisis et calcul des initiales.

Un invité tape « jean-pierre GAGNEBIN » à 22 h, d'une main. Ce qui est stocké
et montré aux mariés doit être « Jean-Pierre Gagnebin », et le palier d'indice
« J.-P. G. ».
"""

import re

# Particules qui restent en minuscules et ne comptent pas dans les initiales :
# « Jean de Rham » donne « J. R. », pas « J. d. R. ».
# « Le » et « La » n'y figurent pas : l'usage français les capitalise dans les
# patronymes — Le Roy, La Fontaine.
PARTICULES = {
    "de", "du", "des", "d", "van", "von", "der", "den", "ten", "ter",
    "da", "di", "dal", "del", "della", "y",
}

# « d'alembert », « l'écuyer » : particule élidée collée au nom
ELISION = re.compile(r"^([dljmnstDLJMNST])['’](.+)$")


def _capitaliser_mot(mot: str) -> str:
    if not mot:
        return mot
    if mot.lower() in PARTICULES:
        return mot.lower()
    elide = ELISION.match(mot)
    if elide:
        return elide.group(1).lower() + "'" + _capitaliser_mot(elide.group(2))
    return "-".join(m[:1].upper() + m[1:].lower() for m in mot.split("-"))


def capitaliser(nom: str) -> str:
    """« jean-pierre GAGNEBIN » → « Jean-Pierre Gagnebin »."""
    nom = re.sub(r"\s+", " ", (nom or "").strip()).replace("’", "'")
    if not nom:
        return nom
    return " ".join(_capitaliser_mot(mot) for mot in nom.split(" "))


def _initiales_fragment(valeur: str) -> str:
    """« Jean-Pierre » → « J.-P. » ; « de Rham » → « R. » ; « d'Alembert » → « A. »."""
    sortie = []
    for mot in (valeur or "").split(" "):
        if not mot or mot.lower() in PARTICULES:
            continue
        elide = ELISION.match(mot)
        if elide:
            mot = elide.group(2)
        sortie.append("-".join(f"{m[0].upper()}." for m in mot.split("-") if m))
    return " ".join(sortie)


def initiales(prenom: str, nom: str) -> str:
    """« jean-pierre », « gagnebin » → « J.-P. G. »."""
    parts = (_initiales_fragment(capitaliser(prenom)),
             _initiales_fragment(capitaliser(nom)))
    return " ".join(p for p in parts if p)
