"""Point d'entrée d'uvicorn. `serveur:app`, jamais `main:app`.

Une `ErreurConfiguration` peut sortir à **deux** moments, et il faut les
attraper tous les deux :

1. **À l'import de `main`** — `config.projet()` y est appelé au niveau module,
   et `base_donnees` en fait autant. Un `projet-actif.txt` absent, un dossier
   inexistant, un `questions.yaml` manquant échouent donc avant que la moindre
   application existe. C'est ce que ce fichier attrape.
2. **Au cycle de vie** — le contrôle du mot de passe, entre autres. C'est
   `main.cycle_de_vie` qui l'attrape, en posant `main.PANNE`.

Dans les deux cas le service **démarre et ne sert rien**, au lieu de mourir en
boucle. Le volume reste alors atteignable pour corriger le fichier fautif — ce
qui n'était pas le cas le 25 août, où le service refusait de démarrer à cause
d'un fichier que ce refus rendait inaccessible.

Ce module n'importe `main` qu'à l'intérieur du `try` : c'est tout l'intérêt.
"""

import config
import panne

try:
    from main import app
except config.ErreurConfiguration as exc:
    print(config.bloc_erreur(exc), flush=True)
    app = panne.application(exc)
