"""La porte — mot de passe unique d'accès (EX-AUTH-18, EX-AUTH-07, EX-SEC-09).

Un seul mot de passe pour tous les invités, imprimé sur les cartons de table.
Non haché : l'administrateur doit pouvoir le relire (EX-SEC-09).

**Où il vit, et pourquoi.** Dans `acces.mot_de_passe` du `config.yaml` du
dossier de projet, jamais dans l'environnement. Trois raisons, dans l'ordre de
leur poids :

1. Il **suit le projet**. Un seul service Railway sert la répétition puis le
   mariage, et la bascule se fait en changeant `projet-actif.txt`. Une variable
   d'environnement vit au-dessus du projet : le mot de passe qui aura circulé
   pendant les essais resterait valable le 5 septembre, et rien ne le
   signalerait. C'est le défaut du 25 août — deux endroits qui déclarent une
   chose apparentée sans obligation de s'accorder.
2. `EX-ADM-08` veut sa **génération et son export imprimable**. L'application
   ne peut pas écrire une variable Railway.
3. Le gain de protection n'existe pas : l'archive d'administration emporte
   déjà la base, et la base porte déjà le code du Gardien (`EX-AUTH-08`).

`MOT_DE_PASSE_ADMIN` et `ANTHROPIC_API_KEY` restent dans l'environnement. La
ligne de partage n'est pas *fichier contre environnement*, c'est **ce qui
s'imprime sur un carton contre ce qui ne s'imprime jamais**.

**Le cookie est l'empreinte du mot de passe en vigueur.** Sans état serveur, et
changer le mot de passe invalide tous les cookies d'un coup — ce qui est le
comportement voulu : si on le change, c'est qu'on veut refermer. Le connaître
ne donne rien de plus que connaître le mot de passe, qui est sur les tables.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
import unicodedata

import config

# Valeur portée par `exemples/config.yaml`. Un `config.yaml` recopié depuis
# l'exemple et jamais relu est le mode de fabrication normal d'un fichier de
# projet — c'est exactement ce qui a produit le défaut d'identité du 25 août.
# Refusée explicitement plutôt que laissée passer.
MOT_DE_PASSE_EXEMPLE = "a-definir"

# Repli de développement : aucun `config.yaml` n'existe alors, et bloquer
# l'exécution locale n'apprendrait rien à personne. Affiché au démarrage.
MOT_DE_PASSE_DEVELOPPEMENT = "conseil"

NOM_COOKIE = "acces"
# Le cookie n'est qu'un raccourci : le mot de passe reste lisible sur le carton
# toute la soirée. Large, donc, pour que revenir voir son portrait une semaine
# plus tard ne demande pas de le ressaisir.
DUREE_COOKIE_S = 60 * 24 * 3600

# EX-SEC-05 — voir `_freiner()` : un délai, jamais un blocage.
DELAI_APRES_ECHEC_S = 0.5


def normaliser(saisie: str) -> str:
    """EX-AUTH-07 — insensible à la casse et aux espaces superflus.

    Les accents sont dépouillés et les espaces intérieurs réduits : sur un
    clavier de téléphone, dans une lumière tamisée, la saisie exacte d'un mot
    accentué n'est pas acquise. Le correcteur automatique ajoute volontiers une
    majuscule initiale et une espace finale, l'un et l'autre invisibles.
    """
    depouille = unicodedata.normalize("NFKD", (saisie or "").strip().lower())
    depouille = "".join(c for c in depouille if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", depouille)


def mot_de_passe() -> str:
    """Le mot de passe en vigueur, relu à chaud (EX-ADM-02).

    Relu et non figé au démarrage : `config.parametre` rafraîchit toutes les
    dix secondes, ce qui rend le mot de passe modifiable avant ouverture sans
    redéployer — ce qu'`EX-SAU-09` interdirait le 5 septembre.
    """
    valeur = config.parametre("acces.mot_de_passe")
    if valeur is None and config.projet().chemin_configuration is None:
        return MOT_DE_PASSE_DEVELOPPEMENT
    return str(valeur or "")


def verifier_au_demarrage() -> None:
    """Refuse de démarrer sans mot de passe utilisable.

    Un projet sans mot de passe est soit ouvert à tous, soit fermé à tous : les
    deux sont pires que l'arrêt. La seule exception est le repli de
    développement, qui n'a pas de `config.yaml` du tout.
    """
    if config.projet().chemin_configuration is None:
        return
    brut = config.parametre("acces.mot_de_passe")
    if brut is None or not str(brut).strip():
        raise config.ErreurConfiguration(
            "`acces.mot_de_passe` est absent du config.yaml du projet "
            f"« {config.projet().identifiant} ». C'est le mot de passe unique "
            "imprimé sur les cartons (EX-AUTH-18, EX-SEC-09). L'ajouter dans "
            f"{config.projet().chemin_configuration} :\n"
            "    acces:\n      mot_de_passe: \"…\""
        )
    if normaliser(str(brut)) == normaliser(MOT_DE_PASSE_EXEMPLE):
        # L'empreinte est jointe parce qu'elle tranche la seule question qui
        # se pose alors : « ai-je modifié le bon fichier ? ». Le 25 août, une
        # valeur éditée sur le volume n'était pas celle que l'application
        # lisait, et rien ne permettait de distinguer les deux cas.
        raise config.ErreurConfiguration(
            f"[fichier lu : {config.projet().chemin_configuration}, empreinte "
            f"{config.empreinte(config.projet().chemin_configuration)}] "
            f"`acces.mot_de_passe` vaut encore « {MOT_DE_PASSE_EXEMPLE} », la "
            "valeur de exemples/config.yaml. Un fichier recopié depuis "
            "l'exemple et jamais relu a déjà envoyé les sauvegardes sous un "
            "préfixe orphelin le 25 août (EX-PRJ-13) ; ici il ouvrirait la "
            "soirée avec un mot de passe public. En poser un vrai dans "
            f"{config.projet().chemin_configuration}."
        )


def jeton() -> str:
    """La valeur que porte le cookie : l'empreinte du mot de passe en vigueur.

    Pas de sel ni de clé : le mot de passe est imprimé sur les tables, son
    empreinte ne protège rien qu'il ne protège déjà. Ce qu'elle apporte, c'est
    qu'aucun état serveur n'est nécessaire et qu'un changement de mot de passe
    referme la porte pour tout le monde, sans liste de sessions à purger.
    """
    return hashlib.sha256(
        ("acces:" + normaliser(mot_de_passe())).encode("utf-8")
    ).hexdigest()[:32]


def correspond(saisie: str) -> bool:
    """EX-AUTH-07 — comparaison normalisée, en temps constant."""
    attendu = normaliser(mot_de_passe())
    if not attendu:
        return False
    return secrets.compare_digest(normaliser(saisie), attendu)


def cookie_valide(valeur: str | None) -> bool:
    return bool(valeur) and secrets.compare_digest(valeur or "", jeton())


def freiner() -> None:
    """EX-SEC-05, partiellement — un délai après échec, jamais un blocage.

    **Pas de compteur par adresse IP.** Cent invités sur le wifi de la salle,
    ou derrière le NAT d'un même opérateur, partagent une seule adresse
    publique : un verrou par IP transformerait dix fautes de frappe en panne
    collective à 21 h. Le délai ralentit une énumération sans jamais fermer la
    porte à quelqu'un qui a le carton sous les yeux.
    """
    time.sleep(DELAI_APRES_ECHEC_S)


def en_https(entetes) -> bool:
    """Vrai derrière le proxy Railway, faux en local et sous TestClient.

    Lu dans `x-forwarded-proto` plutôt que dans le schéma de l'URL : uvicorn
    voit du HTTP en clair derrière le proxy, faute de `--proxy-headers` au
    `CMD`. Un cookie `Secure` posé en local ne serait jamais renvoyé par le
    navigateur, et la porte se refermerait en boucle sans rien afficher.
    """
    return (entetes.get("x-forwarded-proto", "").split(",")[0].strip().lower()
            == "https")


def poser_cookie(reponse, entetes) -> None:
    """EX-SEC-07 — `HttpOnly`, `SameSite=Lax`, `Secure` dès que HTTPS."""
    reponse.set_cookie(
        NOM_COOKIE, jeton(),
        max_age=DUREE_COOKIE_S,
        httponly=True,
        samesite="lax",
        secure=en_https(entetes),
        path="/",
    )


def resume() -> str:
    """Ligne de démarrage. Le mot de passe y figure **en clair**.

    Ce n'est pas un secret : il s'imprime sur une vingtaine de cartons posés
    sur les tables. Ce qu'il vaut, en revanche, c'est de rendre la bascule
    répétition → production vérifiable d'un coup d'œil, au lieu de se
    découvrir à 21 h que les cartons portent l'autre mot.
    """
    source = ("config.yaml du projet" if config.projet().chemin_configuration
              else "repli de développement — aucun config.yaml")
    return f"accès          : mot de passe « {mot_de_passe()} »  ({source})"
