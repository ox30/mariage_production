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
except Exception as exc:                                       # noqa: BLE001
    # **Tout le reste aussi**, et c'est le point : un `SyntaxError`, un
    # `AssertionError` ou un `ImportError` produisent exactement le même
    # symptôme qu'un refus de configuration — le service meurt en boucle, donc
    # l'explorateur de fichiers de Railway, qui passe par le conteneur, devient
    # inatteignable, donc le volume avec lui. Photos, `config.yaml`,
    # `questions.yaml` : tout hors de portée tant que rien ne démarre.
    #
    # Deux fois le 30 août : des marqueurs de conflit Git non résolus, puis un
    # `assert` sur un fichier du volume. La promesse d'EX-ARC-23 — « échouer ne
    # veut pas dire mourir » — ne valait que pour les refus de configuration.
    # Elle vaut désormais pour tout.
    #
    # Ce n'est pas masquer : la trace part au journal, et une page 503 qui
    # nomme le défaut se voit mieux qu'une boucle de redémarrage dont les
    # lignes défilent.
    import traceback

    traceback.print_exc()
    app = panne.application(
        RuntimeError(f"Défaut de code à l'import : {type(exc).__name__} — "
                     f"{exc}"))
