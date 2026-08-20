# Le Livre des Convoqués

Application événementielle du **mariage du 5 septembre 2026**, à Court (Jura
bernois). Thématique Terre du Milieu.

Le soir de la fête, une centaine d'invités répondent depuis leur téléphone à un
questionnaire sur eux-mêmes. Une IA transpose chacun en personnage de la Terre
du Milieu — nom fictif, peuple, portrait, indice — et le serveur lui assigne
l'une des dix régions. Chacun dépose aussi une photo. Après l'événement,
l'administrateur monte une carte interactive où les mariés doivent deviner qui
se cache derrière chaque chronique.

**Le soir, on collecte ; la curation se fait au calme.** Rien n'est assemblé,
monté ni écrit définitivement pendant l'événement. Tout ce qui est produit le
5 septembre est un ingrédient.

---

## Ce dépôt, et l'autre

| Dépôt | Rôle |
|---|---|
| **`mariage_production`** — celui-ci | l'application. C'est lui qui tournera le 5 septembre |
| `mariage_histoire` — figé | le banc d'essai des 16 et 17 août. **Conservé en ligne comme repli**, plus jamais modifié |

Le banc a répondu à deux questions avant l'écriture du cahier des charges v3.0 :
les invités savent-ils répondre seuls, et les portraits sont-ils devinables ?
Oui aux deux, sur une douzaine de chroniques réelles. Son parcours, son
questionnaire, son prompt et son assignation des lieux sont repris ici tels
quels — ce sont des **références normatives**, éprouvées contre l'API réelle et
corrigées une quinzaine de fois sur la base de portraits réellement produits.

> **Le banc est le plan de repli en cas de bogue majeur du code de production.**
> Il ne collecte que les chroniques : ni photo personnelle, ni enluminures, ni
> formulaire des mariés. C'est acceptable — `EX-PHO-38` prévoit qu'une
> chronique sans photo reste jouable.
>
> Deux conséquences à ne pas perdre de vue :
>
> - **Ne jamais renommer une clé de `questions.yaml`.** Reformuler un libellé
>   est libre et prévu jusqu'au 4 septembre (`EX-PLA-06`) ; renommer une `cle`
>   rendrait les réponses du banc inexploitables avec celles de production.
> - **L'adresse du banc doit figurer sur le carton du major de table**, pas sur
>   ceux des invités. Un repli qu'on ne retrouve pas à 22 h 30 n'existe pas.
>
> Le banc ne remplace pas le **plan de repli papier** (annexe B.4) : il appelle
> la même API par la même 4G. Si le réseau ou l'API lâche, seul le papier reste.

---

## Où en est le code

| Fichier | Rôle | État |
|---|---|---|
| `config.py` | projet actif, chemins du volume, fuseau, garde-fous de démarrage | **fait** |
| `.gitignore`, `.dockerignore`, `.env.example` | hygiène du dépôt et de l'image | **fait** |
| `questions.yaml` | 7 questions + 2 conditionnelles + 5 complémentaires, 18 peuples, 10 régions, 4 motifs de reprise, contrat de style | référence normative |
| `ia.py` | appel au modèle, contrôle de sortie, contrôle des noms réels | repris, éprouvé |
| `noms.py` | capitalisation des noms saisis, initiales | repris, éprouvé |
| `templates/`, `static/` | 9 gabarits Jinja2, une question par écran, palette nocturne | repris, éprouvé |
| `main.py` | routes FastAPI, parcours invité | repris, à compléter |
| `base_donnees.py` | SQLite via `sqlite3` standard | **à migrer** vers SQLAlchemy 2.0 + Alembic |

**Manquent encore :** mot de passe unique, import Excel, photo personnelle,
Gardien des chroniques perdues, formulaire des mariés, aide contextuelle,
phases de soirée, administration, réclamations, poste kiosque, sauvegardes,
file de tâches persistée. La génération part toujours dans un
`threading.Thread` nu, sans table `tache` ni reprise après incident.

L'ordre des travaux et les raisons de cet ordre sont dans le **briefing de
démarrage**. Les 239 exigences numérotées sont dans le **cahier des charges
v3.14**. Les deux documents gagneraient à être versionnés ici, dans `docs/` :
le code et sa spécification voyageraient ensemble, et un identifiant `EX-` se
retrouverait par une simple recherche.

---

## Architecture

| Couche | Choix |
|---|---|
| Langage | Python 3.12 |
| Web | FastAPI + Jinja2 + HTMX |
| Base | SQLite (WAL) sur volume persistant |
| ORM | SQLAlchemy 2.0 + Alembic *(à venir)* |
| Images | Pillow + pillow-heif *(à venir)* |
| IA | API Anthropic, `claude-sonnet-5` |
| Conteneur | Docker, une seule instance |

Une seule réplique, sans exception : SQLite n'accepte pas deux conteneurs
écrivant sur le même fichier. C'est ce que garantit le `--workers 1` du
`Dockerfile`, et c'est une des raisons pour lesquelles ce `Dockerfile` doit être
effectivement utilisé par la plateforme (`EX-ARC-18`).

---

## Un service Railway, deux projets

L'application ne connaît **qu'un seul chemin**, celui désigné par
`projet-actif.txt` (`EX-PRJ-01`). Basculer de la répétition au mariage consiste
à changer une ligne et à redémarrer — pas à déployer ailleurs.

```
/data/                                     ← volume persistant, 5 Go (EX-ARC-15)
  projet-actif.txt                         ← une ligne : le nom du dossier actif
  projets/
    2026-08-repetition/                    ← type: preparation
      config.yaml
      questions.yaml
      app.db
      medias/{photos_invites,photos_tables}/{originaux,web,vignettes}/
      exports/  logs/  instantanes/
    2026-09-05-court-mariage/              ← type: production
      ...
```

L'isolation entre projets est **physique**, pas logique : il n'existe aucune
colonne `projet_id` (`EX-PRJ-03`). Le type de projet est **immuable** et
commande le refus de toute opération destructive (`EX-PRJ-04` à `EX-PRJ-06`) :
une remise à zéro est impossible sur un projet de production, quelle que soit
l'interface. Le projet de préparation se crée **avant** celui de production
(`EX-PLA-03`), qui en reprend tables, invités, mots de passe et configuration,
sans aucune donnée de soirée (`EX-PRJ-08`).

La table de test reste **active dans le projet de production**, pour le test de
fumée du jour J (`EX-PRJ-10`).

### Déploiement

1. Railway → *New Project* → *Deploy from GitHub repo*. Le `Dockerfile` est
   détecté.
2. Onglet **Volumes** → *New Volume*, point de montage `/data`, **5 Go**.
   Sans volume, la base vit dans le conteneur et le prochain redéploiement —
   un simple ajout de variable suffit — l'efface. C'est arrivé le 17 août.
3. Onglet **Variables** :

   | Variable | Valeur |
   |---|---|
   | `ANTHROPIC_API_KEY` | la clé de la console Anthropic |
   | `MOT_DE_PASSE_ADMIN` | un mot de passe long |
   | `MODELE_IA` | `claude-sonnet-5` |
   | `PRENOM_MARIEE` | le prénom de la mariée |
   | `PRENOM_MARIE` | le prénom du marié |
   | `EXIGER_VOLUME` | `1` |

   `EXIGER_VOLUME=1` fait **échouer le démarrage** si `/data` est absent ou en
   lecture seule, au lieu de perdre les données en silence (`EX-ARC-17`).

4. Créer sur le volume :

   ```
   /data/projet-actif.txt                       →  2026-08-repetition
   /data/projets/2026-08-repetition/config.yaml →  voir exemples/config.yaml
   /data/projets/2026-08-repetition/questions.yaml
   ```

   **Rien n'est recopié automatiquement du dépôt vers le volume.** Une copie
   faite une fois puis jamais rafraîchie a fait tourner l'application des
   heures sur une configuration périmée, sans aucun message d'erreur
   (`EX-ARC-19`). Un fichier manquant provoque une erreur de démarrage qui
   nomme la manœuvre exacte — le premier déploiement échouera donc, et son
   journal dira quoi déposer.

5. Onglet **Settings** → *Generate Domain*, ou nom de domaine propre.
   À trancher avant l'impression des cartons.

6. Vérifier que le **`Dockerfile` est bien le constructeur** : *Settings →
   Build → Builder*. Le badge de version affiché à côté du domaine relève
   d'une détection de langage indépendante de l'image et **n'est pas fiable** :
   il annonçait 3.13 pour une image en 3.12.

### Ce que le démarrage écrit au journal

```
projet actif    : 2026-09-05-court-mariage (Mariage Court 2026)
type            : production  — opérations destructives refusées (EX-PRJ-06)
dossier         : /data/projets/2026-09-05-court-mariage
base            : /data/projets/2026-09-05-court-mariage/app.db
questions.yaml  : /data/projets/2026-09-05-court-mariage/questions.yaml  [43c8eb703d7a]
fuseau affiché  : Europe/Zurich  (2026-09-05 22:00)
```

L'**empreinte de `questions.yaml`** figure dans ce résumé parce qu'elle est la
seule chose qui aurait révélé, le 17 août, que l'application tournait sur une
configuration périmée. Une ligne au démarrage contre plusieurs heures de
recherche. **Comparer cette empreinte est le premier geste du jour J.**

---

## En local

```powershell
Copy-Item .env.example .env      # puis y mettre les vraies valeurs
pip install -r requirements.txt
uvicorn main:app --reload
```

Sans `/data` et sans `EXIGER_VOLUME`, l'application se replie sur un projet de
développement dans `donnees-locales/` — hors du dépôt, et **annoncé à chaque
démarrage**. Ce projet est synthétique : aucun `config.yaml` sur le disque, son
type est forcé à `preparation`, et `questions.yaml` est lu **directement dans le
dépôt**, sans copie. Éditer `questions.yaml` prend donc effet immédiatement, et
aucune copie locale ne peut se figer.

Les prénoms des mariés ne figurent dans **aucun fichier versionné**
(`EX-SEC-18`) : ni dans le `README`, ni dans `.env.example`, ni dans les jeux de
test, où ils s'écrivent en valeurs fictives. Ils se posent dans Railway et dans
le `.env` local, tous deux non versionnés.

Le dépôt est alimenté par un **client Git**, jamais par le dépôt de fichiers de
l'interface web de GitHub : les fichiers cachés y passent à la trappe, et
`.gitignore`, `.env.example` et `.dockerignore` en ont déjà fait les frais.

---

## Tests

Scripts autonomes, une commande chacun. Le chemin d'échec est testé, pas
seulement le chemin heureux.

```powershell
python test_hygiene.py     # .gitignore, .dockerignore, prénoms réels
python test_config.py      # projet actif et ses sept chemins d'échec
python test_parcours.py    # parcours invité, cloisonnement, quotas, contrat
python test_affichage.py   # rendu, échappement, appariement des lieux
```

Ils doivent passer **sur un dossier vierge**, décompressé depuis l'archive.
`test_hygiene.py` gagne à être lancé avec les vrais prénoms dans
l'environnement : c'est la seule condition dans laquelle il peut vérifier
qu'ils n'ont pas fui dans un fichier versionné.

Les conventions de code, le registre des écarts assumés et la liste des
garde-fous de démarrage sont dans **`CONVENTIONS.md`**.

---

## Les pages, aujourd'hui

| Adresse | À qui |
|---|---|
| `/` | l'invité — questionnaire, portrait, questions complémentaires |
| `/deviner` | provisoire — relecture avec quelqu'un qui connaît les participants |
| `/tableau` | provisoire — latences, jetons, échecs, fuites de noms, répartition |
| `/tableau/export.json` | provisoire — export brut |

Les trois dernières sont reprises du banc et protégées par authentification
HTTP. Elles seront remplacées à l'étape 4 par le tableau de bord complet
(`EX-ADM-18`) et l'écran de relecture (`EX-ADM-19`).

---

## Ce que ce projet n'est pas

- Pas un service en ligne multi-utilisateurs. Un seul événement tourne à la fois.
- Pas une plateforme de diffusion en direct. Aucun personnage n'est montré
  publiquement le soir même : la découverte appartient aux mariés.
- Pas un module de partage de photos. La photo est un accessoire du personnage.
- Pas un système à haute sécurité — mais **la simplicité d'usage n'excuse
  aucune faiblesse technique**.

Hors périmètre, à faire après l'événement, sans contrainte de temps : le dessin
de la carte, la logique du jeu et ses paliers d'aide, l'écriture des dix
chapitres, l'épilogue, le montage des enluminures, la relecture des cent
chroniques.
