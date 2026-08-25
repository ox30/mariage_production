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
