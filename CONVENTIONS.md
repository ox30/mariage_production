# Conventions du dépôt

Consigné en application d'`EX-GEN-06`.

## Langue

**Français pour le modèle de domaine, anglais pour l'infrastructure technique.**

| Ce qui est en français | Ce qui est en anglais |
|---|---|
| noms de tables et de colonnes (`chronique`, `reponses_json`, `creee_le`) | bibliothèques, décorateurs, API des outils |
| noms de classes et de fonctions du domaine (`Projet`, `assigner_lieu`) | noms de variables d'environnement imposés par un service |
| routes du parcours invité (`/portrait`, `/deviner`) | noms de fichiers imposés par un outil |
| commentaires, messages d'erreur, journaux | |

Exception assumée : les fichiers dont le nom est imposé gardent ce nom —
`README.md`, `Dockerfile`, `requirements.txt`, `alembic.ini`.

## Nommage

**Aucun terme thématique en base, en classe ou en route** (`EX-GEN-01`). Les
noms de peuples et de lieux sont des **données**, pas des identifiants de code.
Le lieu est stocké par code stable — `lieu_01` … `lieu_10` — et non par son
libellé (`EX-IA-28`, `EX-IA-42`) : renommer une région en pleine soirée ne doit
orpheliner aucune chronique.

Corollaire éprouvé : `code_chef` et `est_chef_de_train` ont dû être renommés en
v3.1 parce qu'un titre ferroviaire avait fini en nom de colonne. Le nom neutre
survivra au prochain changement de thème.

## Horodatages

Stockés en **UTC**, affichés en **Europe/Zurich** (`EX-GEN-04`). Une seule
source : `config.maintenant()` pour écrire, `config.en_heure_locale()` pour
afficher. `datetime.utcnow()` est proscrit — il renvoie un objet naïf que rien
ne distingue d'une heure locale.

Le fuseau est **vérifié au démarrage** et non supposé : Windows n'a pas de base
de fuseaux système, et les images Debian « slim » n'en embarquent pas. D'où
`tzdata` dans `requirements.txt`.

## Chemins

L'application ne connaît **qu'un seul chemin**, celui désigné par
`projet-actif.txt` (`EX-PRJ-01`). Tout ce qui touche au système de fichiers
passe par `config.py`. Aucun module ne construit un chemin à partir de `/data`.

## Configuration

| Ce qui vit où | Pourquoi |
|---|---|
| **Variables d'environnement** — secrets, prénoms des mariés | ne doivent apparaître dans aucun fichier versionné (`EX-SEC-06`, `EX-SEC-18`) |
| **`config.yaml`** du dossier de projet — type, quotas, mots de passe, modèle | modifiable sans redéployer ; le type est immuable (`EX-PRJ-04`) |
| **`questions.yaml`** du dossier de projet — libellés, options, lieux, peuples, contrat de style | un libellé incompréhensible découvert à 21 h se corrige sans redéployer (`EX-PRJ-12`, `EX-QUE-12`) |
| **Dépôt** — `questions.yaml` de référence, `exemples/config.yaml` | jamais lus en production ; `questions.yaml` sert en revanche de source réelle au projet de développement local |

Deux variables n'ont pas leur place dans `.env.example` parce qu'elles ne sont
pas des paramètres de production mais des échappatoires d'essai :
`RACINE_DONNEES` déplace la racine du volume, `ZONE_AFFICHAGE` change le fuseau.
`test_config.py` s'en sert pour éprouver les chemins d'échec sans toucher au
vrai volume.

**Rien n'est recopié automatiquement du dépôt vers le volume.** Une copie faite
une fois puis jamais rafraîchie a fait tourner l'application des heures sur une
configuration périmée, sans aucun message d'erreur (`EX-ARC-19`). Un fichier
manquant provoque une erreur qui nomme la commande à taper.

Le dépôt est alimenté par un **client Git**, jamais par le dépôt de fichiers de
l'interface web de GitHub : les fichiers cachés y passent à la trappe, et
`.gitignore`, `.env.example` et `.dockerignore` en ont fait les frais.

## Échouer plutôt que se replier

Un repli silencieux se paie plus tard et plus cher. Le démarrage échoue
explicitement, avec un message qui nomme l'exigence et la manœuvre :

- volume absent alors que `EXIGER_VOLUME=1` (`EX-ARC-17`) ;
- volume monté en lecture seule, que tout test d'existence laisse passer ;
- `projet-actif.txt` absent, ou désignant un dossier inexistant ;
- `projet.type` absent ou hors des deux valeurs admises ;
- `questions.yaml` absent du dossier de projet ;
- fuseau d'affichage introuvable.

Deux exceptions, qui **avertissent sans bloquer** : un nom de dossier non
conforme à `EX-PRJ-02`, et le repli de développement quand aucun volume n'est
monté et qu'`EXIGER_VOLUME` ne l'interdit pas. Bloquer le démarrage sur une
convention de nommage le 4 septembre à 21 h serait la pire façon de faire
respecter une règle cosmétique.

Chaque démarrage écrit un résumé au journal, **empreinte de `questions.yaml`
comprise**. Une ligne contre plusieurs heures de recherche.

## Tests

Scripts autonomes, `assert` nus, lancés par `python test_xxx.py`. Étiquettes de
bloc **descriptives et uniques** : un numéro se décale au prochain bloc inséré,
un nom non.

| Fichier | Ce qu'il éprouve |
|---|---|
| `test_hygiene.py` | `.gitignore` par `git check-ignore`, `.dockerignore` par simulation des règles Docker, absence des prénoms réels |
| `test_config.py` | résolution du projet actif et les sept chemins d'échec |
| `test_parcours.py` | parcours invité, cloisonnement, quotas, contrat de style |
| `test_modeles.py` | schéma, compteurs dérivés, contraintes d'unicité |
| `test_affichage.py` | rendu, échappement, appariement des lieux |

Le chemin d'échec est testé, pas seulement le chemin heureux.

## Repli

Le dépôt `mariage_histoire` — le banc d'essai des 16 et 17 août — reste déployé
et figé, comme plan de repli en cas de bogue majeur du code de production.
Conséquence sur les conventions : **une `cle` de `questions.yaml` ne se renomme
jamais.** Les libellés se reformulent librement jusqu'au 4 septembre
(`EX-PLA-06`) ; renommer une clé rendrait les réponses collectées par le banc
inexploitables avec celles de production.

## Schéma et migrations

`modeles.py` porte les dix entités de la section 5.1, `alembic/versions/` leur
histoire. Les migrations s'appliquent **au démarrage** : le service tourne en
une seule instance (`EX-ARC-05`), il n'y a donc aucune course, et une migration
qu'on peut oublier de lancer est une migration qu'on oubliera.

Trois règles :

- **Une révision est un instantané historique.** Elle n'importe jamais
  `modeles` : au niveau de la base, `HorodatageUTC` n'est qu'un `DATETIME`, et
  `env.py` le rend ainsi. Une révision qui dépendrait du modèle courant
  changerait de sens à chaque évolution.
- **`render_as_batch=True`** dès la première révision. SQLite ne sait pas
  modifier une colonne en place ; sans cela, toute modification ultérieure
  échouerait.
- **Les tables absentes du modèle sont ignorées**, jamais proposées à la
  suppression (`include_object`). La table `participation` du banc d'essai
  survit dans les bases déjà déployées ; toute suppression est douce
  (`EX-GEN-03`) et se décide à la main.

## Écarts assumés

| Écart | Raison | Échéance |
|---|---|---|
| `ia.py` lit le modèle dans `MODELE_IA`, alors que la section 4.6 le place dans `config.yaml` | `EX-ADM-02` veut le modèle réglable avant ouverture, donc dans `config.yaml`. À déplacer quand `config.yaml` sera lu en entier | étape 2 |
| `config.py` ne valide que le bloc `projet:` ; `acces`, `quotas`, `ia`, `tables` sont exposés bruts | valider une forme avant d'avoir écrit le code qui la consomme, c'est la deviner | étape 2 |
| Le contrôle `EX-SEC-18` se met en veille si `PRENOM_MARIEE` et `PRENOM_MARIE` sont absents de l'environnement | c'est le seul dessin qui n'exige pas d'écrire les prénoms dans un fichier versionné. Le garde-fou est l'exécution locale avec le `.env` chargé ; il n'y a pas d'intégration continue dans ce projet | accepté tel quel |
| `etat_soiree` a une clé primaire entière et non un UUID (`EX-GEN-02`) | table à une seule ligne : une clé UUID n'y apporte rien et retire la garantie qui compte, qu'il n'y ait jamais deux phases simultanées. La contrainte `id = 1` le dit | accepté tel quel |
| Le rapprochement des personnes se fait sur (prénom, nom) normalisé, sans confirmation | `EX-AUTH-05` (doublon approximatif) et `EX-AUTH-19` (sélection dans la liste importée) arrivent à l'étape 2. D'ici là, deux homonymes réels seraient confondus — mais la reconduction ne détruit rien, donc le pire cas est un invité qui voit le personnage d'un autre, pas un personnage effacé | étape 2 |
| Ressaisir son nom reconduit vers la chronique existante sans écran d'explication | l'écran à deux entrées d'`EX-AUTH-09` — *créer* ou *revoir* son personnage — arrive à l'étape 2. D'ici là la reconduction est muette, mais non destructrice | étape 2 |
| `EX-IA-43` est portée par un index unique partiel, mais la mise en file n'existe pas encore : `main.py` se contente de refuser si l'état est `en_cours` | vérification suivie d'écriture, donc théoriquement joueuse. La file rendra la course impossible | étape suivante |
| `.dockerignore` est une liste d'exclusion, non d'inclusion | conforme à la lettre d'`EX-SEC-17`. Une liste d'inclusion couvrirait un nouveau type de fichier sensible, mais tout module oublié ferait échouer le démarrage — et `EX-SAU-09` gèle les déploiements le 5 septembre | accepté tel quel |
