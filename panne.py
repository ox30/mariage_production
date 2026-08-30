"""L'application de secours : debout, mais ne servant rien.

**Pourquoi elle existe.** Le 25 août, le contrôle du mot de passe a refusé le
démarrage sur un `config.yaml` portant encore la valeur d'exemple. Le service
est entré en redémarrage perpétuel — et l'explorateur de fichiers de Railway
passe par le conteneur. Le fichier à corriger n'était plus atteignable *parce
que* le service refusait de démarrer à cause de ce fichier. Blocage circulaire.

Le défaut ne tenait pas au mot de passe : les sept refus de l'étape 1 portent
eux aussi sur des fichiers du volume — `projet-actif.txt`, le dossier de
projet, `projet.type`, `questions.yaml`. Chacun avait le même piège. Le
5 septembre, un redémarrage de conteneur sur une configuration momentanément
mal formée aurait coûté la soirée, sans recours.

**Ce que « échouer plutôt que se replier » voulait dire.** Ne pas faire
semblant de marcher — pas mourir. Un service qui démarre, ne sert *rien*, et
répond à chaque requête par ce qu'il faut corriger n'est replié en aucune
façon : il est visiblement en panne, il le dit, et il reste réparable.

Ce qui n'a **surtout pas** lieu dans cet état : aucune migration, aucun worker,
aucun instantané, aucune route du parcours. Une migration appliquée à une base
au mauvais endroit serait pire que l'arrêt.

Ce module ne dépend de rien — ni gabarit, ni feuille de style, ni
configuration. C'est la seule façon qu'il a de fonctionner quand justement la
configuration ne fonctionne pas.
"""

from __future__ import annotations

import html

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

CODE = 503


def page(message: str) -> str:
    """Du HTML en dur, sans gabarit ni feuille de style.

    Jinja2 lirait `templates/`, la feuille de style demanderait son empreinte,
    et l'empreinte demanderait `config.projet()` — celui-là même qui vient
    d'échouer. Une page de panne qui dépend de ce qui est en panne ne
    s'affiche jamais.
    """
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Configuration à corriger</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 0; padding: 2rem 1.2rem;
        background: #1a1714; color: #e8e0d4; line-height: 1.55; }}
 main {{ max-width: 34rem; margin: 0 auto; }}
 h1 {{ font-size: 1.3rem; font-weight: 600; margin: 0 0 1rem; }}
 pre {{ white-space: pre-wrap; word-break: break-word; background: #262019;
        border-left: 3px solid #b4884a; padding: 0.9rem 1rem; font-size: 0.95rem; }}
 p.discret {{ color: #9a9086; font-size: 0.9rem; }}
</style></head>
<body><main>
<h1>Le service est debout, mais il ne sert rien</h1>
<p>Sa configuration est incomplète. Rien n'a été touché : ni la base, ni les
   sauvegardes, ni les chroniques déjà écrites.</p>
<pre>{html.escape(message)}</pre>
<p class="discret">Corriger le fichier sur le volume, puis redémarrer le
   service. Le volume reste accessible : c'est précisément pour cela que ce
   service refuse de mourir.</p>
</main></body></html>"""


def application(exc: Exception) -> FastAPI:
    """Une application qui répond la même chose à tout, en 503.

    503 et non 500 : ce n'est pas un défaut du programme, c'est un service
    indisponible en attendant une manœuvre. Toutes les routes, sans exception —
    y compris `/entrer`, parce que dans cet état il n'y a rien derrière la
    porte à protéger, et parce qu'un écran de mot de passe qui n'ouvre sur rien
    ferait croire à un mot de passe erroné.
    """
    corps = page(str(exc))
    app = FastAPI(title="Le Livre des Convoqués — configuration à corriger")

    @app.api_route("/{chemin:path}",
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                   response_class=HTMLResponse)
    async def tout(request: Request, chemin: str = ""):
        return HTMLResponse(corps, status_code=CODE)

    return app
