"""Outils partagés par les tests de fumée. N'est pas un test lui-même.

Depuis l'étape 2, tout le parcours invité est derrière le mot de passe unique
(EX-AUTH-18). Un client de test qui ne le franchit pas reçoit une redirection
vers `/entrer` sur chaque requête — et l'assertion qui tombe ne dit alors rien
de ce qu'elle prétendait éprouver.

`client()` remplace `TestClient(main.app)` : il ouvre le cycle de vie de
l'application, franchit la porte, et **vérifie qu'elle était bien fermée avant**
de la franchir. Sans ce dernier contrôle, un jour où la porte ne fermerait plus
rien, tous les tests continueraient de passer sans que personne le voie.
"""

from fastapi.testclient import TestClient

import acces


def client(app, entrer: bool = True) -> TestClient:
    c = TestClient(app)
    c.__enter__()
    if entrer:
        avant = c.get("/", follow_redirects=False)
        assert avant.status_code == 303 and "/entrer" in avant.headers["location"], \
            ("la porte ne fermait déjà rien avant que le test l'ouvre : "
             f"« / » a répondu {avant.status_code} (EX-AUTH-18)")
        r = c.post("/entrer",
                   data={"mot_de_passe": acces.mot_de_passe(), "vers": "/"},
                   follow_redirects=False)
        assert r.status_code == 303, f"la porte a refusé le mot de passe : {r.status_code}"
    return c


def creer_chronique(prenom, nom, reponses, codes_lieux, etat="en_attente",
                    genre=None):
    """Raccourci de test : résout l'identité, puis crée la chronique.

    `bd.creer()` prend un `personne_uuid` depuis l'étape 2 — l'identité se
    résout à l'écran d'identité, et une résolution par le nom refaite dans la
    couche de persistance serait une seconde source de vérité, celle qui
    confondait deux homonymes. Ce helper enchaîne les deux appels pour que les
    tests restent lisibles, SANS rouvrir ce chemin dans l'application.
    """
    import base_donnees as bd

    trouvee = bd.resoudre(prenom, nom).unique
    if trouvee is None:
        trouvee = bd.personne(bd.creer_personne_libre(prenom, nom, genre=genre))
    elif genre:
        bd.definir_genre(trouvee.uuid, genre)
    return bd.creer(trouvee.uuid, reponses, codes_lieux, etat=etat)


def entrer_identite(client, prenom, nom, genre="", intention="creer"):
    """Parcourt l'écran d'identité comme le ferait un invité."""
    return client.post("/identite",
                       data={"intention": intention, "prenom": prenom,
                             "nom": nom, "genre": genre},
                       follow_redirects=False)


def valider(client, donnees, **extra):
    """Poste `/valider` comme le ferait un invité sortant de l'écran d'identité.

    Extrait (prénom, nom) du dictionnaire de réponses, franchit l'écran
    d'identité pour obtenir un `personne_uuid`, et poste le reste. Depuis
    l'étape 2, `/valider` n'accepte plus (prénom, nom) : deux homonymes ne se
    distinguent que par leur uuid.
    """
    import base_donnees as bd

    d = dict(donnees)
    d.update(extra)
    prenom = d.pop("prenom", "")
    nom = d.pop("nom", "")
    genre = d.pop("genre", "")
    entrer_identite(client, prenom, nom, genre)
    trouvee = bd.resoudre(prenom, nom).unique
    d["personne_uuid"] = trouvee.uuid if trouvee else ""
    return client.post("/valider", data=d, follow_redirects=False)
