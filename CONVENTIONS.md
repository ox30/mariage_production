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

**Le nom du dossier fait autorité pour l'identité du projet**, jamais un champ
déclaratif. Le 25 août, un `config.yaml` recopié depuis `exemples/` portait un
autre identifiant : les sauvegardes sont parties sous un préfixe qui ne
correspondait à aucun dossier, et rien ne l'a signalé pendant des heures. Deux
endroits déclaraient la même chose sans obligation de s'accorder. Un
`projet.identifiant` divergent est désormais annoncé au démarrage, et l'exemple
livré n'en porte plus.

## Configuration

| Ce qui vit où | Pourquoi |
|---|---|
| **Variables d'environnement** — secrets, prénoms des mariés | ne doivent apparaître dans aucun fichier versionné (`EX-SEC-06`, `EX-SEC-18`) |
| **`config.yaml`** du dossier de projet — type, quotas, mots de passe, modèle | modifiable sans redéployer ; le type est immuable (`EX-PRJ-04`) |
| **`questions.yaml`** du dossier de projet — libellés, options, lieux, peuples, contrat de style | un libellé incompréhensible découvert à 21 h se corrige sans redéployer (`EX-PRJ-12`, `EX-QUE-12`) |
| **Dépôt** — `questions.yaml` de référence, `exemples/config.yaml`, `exemples/invites-gabarit.xlsx` | jamais lus en production ; `questions.yaml` sert en revanche de source réelle au projet de développement local |

Le **gabarit d'import** est versionné en deux morceaux : `gabarit_invites.py`
qui le produit, et le `.xlsx` qu'il produit. Le script est la pièce normative —
un `.xlsx` est un binaire, et aucun diff ne montrerait qu'une colonne a changé
de nom. `test_hygiene.py` contrôle sa liste de colonnes contre `EX-ADM-05`,
parce qu'un gabarit qui dérive de l'import casse l'import en silence. Le
classeur est versionné à côté pour n'avoir pas à installer `openpyxl` juste
pour remplir une liste d'invités.

Deux variables n'ont pas leur place dans `.env.example` parce qu'elles ne sont
pas des paramètres de production mais des échappatoires d'essai :
`RACINE_DONNEES` déplace la racine du volume, `ZONE_AFFICHAGE` change le fuseau.
`test_config.py` s'en sert pour éprouver les chemins d'échec sans toucher au
vrai volume.

### Deux fichiers, le même nom

`exemples/config.yaml` **n'est jamais lu par l'application.** C'est un modèle,
versionné, à recopier sur le volume *puis à modifier*. Le fichier lu est celui
du dossier de projet, sur le volume. La confusion entre les deux a coûté un
échange entier le 25 août.

Le modèle porte volontairement `a-definir` partout où une valeur est à
choisir, et le démarrage **refuse** cette valeur : le filet et l'appât vont
ensemble. Y écrire une valeur réelle désarmerait le filet *et* propagerait
cette valeur au projet de production par recopie — le mot de passe de la
répétition, qui aura circulé pendant tous les essais, deviendrait celui du
mariage. `test_hygiene.py` le contrôle, parce qu'un commentaire ne se fait pas
respecter tout seul.

**Rien n'est recopié automatiquement du dépôt vers le volume.** Une copie faite
une fois puis jamais rafraîchie a fait tourner l'application des heures sur une
configuration périmée, sans aucun message d'erreur (`EX-ARC-19`). Un fichier
manquant provoque une erreur qui nomme la commande à taper.

Le dépôt est alimenté par un **client Git**, jamais par le dépôt de fichiers de
l'interface web de GitHub : les fichiers cachés y passent à la trappe, et
`.gitignore`, `.env.example` et `.dockerignore` en ont fait les frais.

## Les trois classes de secret

La ligne de partage n'est pas *fichier contre environnement*, c'est **ce qui
s'imprime sur un carton contre ce qui ne s'imprime jamais**.

| Secret | Où | Pourquoi |
|---|---|---|
| `ANTHROPIC_API_KEY`, `MOT_DE_PASSE_ADMIN`, identifiants du stockage objet | environnement | jamais imprimés, ne suivent pas le projet (`EX-SEC-09`, `EX-SAU-22`) |
| mot de passe d'accès, mot de passe des mariés | `acces:` du `config.yaml` du projet | s'impriment sur les cartons, suivent le projet, réglables avant ouverture (`EX-SEC-09`, `EX-ADM-02`) |
| code du Gardien | base | généré par l'application, un par projet (`EX-AUTH-08`) |

Le mot de passe d'accès **ne va pas dans l'environnement**, et c'est délibéré.
Un seul service Railway sert la répétition puis le mariage, et la bascule se
fait par `projet-actif.txt` : une variable d'environnement vit au-dessus du
projet, donc le mot de passe des essais resterait valable le 5 septembre sans
que rien ne le signale. C'est le défaut du 25 août — deux endroits qui
déclarent une chose apparentée sans obligation de s'accorder. S'y ajoutent
`EX-ADM-08`, qui veut sa génération et son export imprimable, ce qu'aucune
variable Railway ne permet, et le fait que l'archive d'administration emporte
déjà la base, donc déjà le code du Gardien : le gain de protection n'existait
pas.

**Le cookie d'accès est l'empreinte du mot de passe en vigueur.** Aucun état
serveur, et changer le mot de passe referme toutes les sessions d'un coup — ce
qui est le comportement voulu, mais qu'il faut savoir : le modifier à 21 h 30
oblige toute la salle à ressaisir. Le mot de passe est écrit au journal de
démarrage **en clair** : il est sur vingt cartons, ce n'est pas un secret, et
c'est ce qui rend la bascule vérifiable d'un coup d'œil.

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

### Échouer ne veut pas dire mourir

**Aucun de ces refus ne tue le processus.** Le service démarre, ne sert
**rien**, et répond `503` sur toutes les routes avec le texte de ce qu'il faut
corriger — `panne.py`, branché par `serveur.py` et par le drapeau `main.PANNE`.

*Payé le 25 août.* Le contrôle du mot de passe a refusé un `config.yaml`
portant la valeur d'exemple ; le service est entré en redémarrage perpétuel, et
l'explorateur de fichiers de Railway passe par le conteneur. **Le fichier à
corriger n'était plus atteignable parce que le service refusait de démarrer à
cause de ce fichier.** Blocage circulaire, sortie uniquement par retour au
déploiement précédent.

Le défaut ne tenait pas au mot de passe : les sept refus ci-dessus portent tous
sur des fichiers du volume et avaient chacun le même piège. Le 5 septembre, un
redémarrage de conteneur — resize de volume, mise à jour d'infrastructure — sur
une configuration momentanément mal formée aurait coûté la soirée sans recours.

« Échouer plutôt que se replier » voulait dire **ne pas faire semblant de
marcher**, pas mourir. Un service qui dit ce qu'il faut corriger et n'exécute
ni migration, ni worker, ni instantané n'est replié en rien : il est visiblement
en panne, et il reste réparable.

Deux points de capture, parce qu'une `ErreurConfiguration` sort à deux moments :
à l'**import de `main`** — `config.projet()` y est appelé au niveau module —
attrapé par `serveur.py`, et au **cycle de vie**, attrapé par `cycle_de_vie`.
D'où `CMD ["…", "uvicorn serveur:app …"]` et non `main:app`.

`panne.py` n'importe **aucun module du projet** et n'emploie ni gabarit ni
feuille de style : une page de panne qui dépend de ce qui est en panne ne
s'affiche jamais. Le contrôle se fait sur les imports réels, par `ast`.

Chaque démarrage écrit un résumé au journal, **empreintes de `questions.yaml`
et de `config.yaml` comprises**. Une ligne contre plusieurs heures de
recherche. *L'empreinte de `config.yaml` manquait jusqu'au 25 août : une valeur
qu'on croyait modifiée sur le volume ne l'était pas, et rien ne permettait de
distinguer « mon édition n'a pas pris » de « ce n'est pas ce fichier-là ».*

**Le `config.yaml` est chargé strictement : deux fois la même clé au même
niveau est refusé.** PyYAML garde silencieusement la **dernière** occurrence.
Ajouter un bloc `acces:` en tête d'un fichier qui en portait déjà un plus bas
produit alors exactement l'inverse de ce qu'on croit avoir écrit — sans un
mot. Le message nomme les deux numéros de ligne.

**Un message d'erreur multiligne se fait réordonner par Railway.** Chaque ligne
reçoit son propre horodatage et le tri les mélange : le 25 août, le cadre est
arrivé en morceaux, son corps affiché avant son en-tête. `bloc_erreur()` émet
donc d'abord le message **sur une seule ligne**, atomique et toujours lisible ;
le cadre suit, pour le confort de lecture en local.

**Une configuration refusée s'écrit comme une consigne, pas comme un bug.**
`config.bloc_erreur()` encadre le message et le rend lisible sans dérouler de
trace. Constaté sur Railway le 25 août : le message qui disait quoi corriger
sortait sous douze lignes de trace Python, répétées onze fois par le
redémarrage en boucle. La trace n'apprend rien — ce n'est pas le programme qui
est en défaut, c'est un fichier à corriger — et elle enterre la seule ligne
utile, au moment précis où le service est à terre et où l'on cherche vite.
Capturé aux deux endroits d'où une `ErreurConfiguration` peut sortir : à
l'import de `main`, et au cycle de vie.

## Tests

Scripts autonomes, `assert` nus, lancés par `python test_xxx.py`. Étiquettes de
bloc **descriptives et uniques** : un numéro se décale au prochain bloc inséré,
un nom non.

| Fichier | Ce qu'il éprouve |
|---|---|
| `test_hygiene.py` | `.gitignore` par `git check-ignore`, `.dockerignore` par simulation des règles Docker, absence des prénoms réels |
| `test_config.py` | résolution du projet actif et les sept chemins d'échec |
| `test_parcours.py` | parcours invité, cloisonnement, quotas, contrat de style |
| `test_ia.py` | une tentative, exceptions typées, traçabilité, doublons |
| `test_taches.py` | file, priorité, réclamation atomique, réessai, barrière |
| `test_instantane.py` | VACUUM INTO, dépôts doublés, sonde, aucune purge |
| `test_modeles.py` | schéma, compteurs dérivés, contraintes d'unicité |
| `test_affichage.py` | rendu, échappement, appariement des lieux |
| `test_acces.py` | porte fermée par défaut, cookie, en-têtes, refus au démarrage |
| `test_identite.py` | deux portes, cookie d'appareil, homonymes, reconduction |
| `test_import.py` | simulation, idempotence, rejet sur conflit, inactivation |

`test_outils.py` n'est pas un test : il porte `client()`, qui ouvre le cycle de vie et franchit la porte — **après avoir vérifié qu'elle était fermée**. Sans ce contrôle, le jour où la porte ne fermerait plus rien, toute la suite continuerait de passer.

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

## Valeurs dérivées

Trois grandeurs ne sont jamais déclarées, toujours recalculées depuis ce
qu'elles décrivent. Une valeur dérivée ne peut pas se désynchroniser :

| Grandeur | Dérivée de | Exigence |
|---|---|---|
| l'identité d'un projet | le nom de son dossier | `EX-PRJ-01` |
| les doublons de noms fictifs | les noms fictifs normalisés | `EX-IA-44` |
| `nb_generations`, `nb_tentatives` | le journal | `EX-GEN-07`, `EX-IA-21` |
| `chronique.etage` | les clés de réponses présentes | `EX-QUE-11` |
| le libellé d'une région | son code stable | `EX-IA-28`, `EX-IA-42` |

Corollaire pour l'étage : comme les réponses ne sont jamais que **fusionnées**,
jamais retirées, l'étage ne peut mécaniquement pas redescendre. Il dit ce que
l'invité a donné, et ce qui a été donné l'a été.

## L'identité

**Une chronique appartient à une `personne`, désignée par son UUID.** Ni un
nom, ni un cookie. `bd.creer()` prend un `personne_uuid` déjà résolu : refaire
une résolution par le nom dans la couche de persistance serait une seconde
source de vérité.

*Le défaut qu'on a fermé :* `personne_par_nom` faisait un `scalar()` et
renvoyait silencieusement la **première** de deux personnes du même nom. Or
`EX-ADM-13` autorise deux homonymes distingués par leur colonne `Identifiant`
— c'est même la seule raison d'être de cette colonne. La seconde Marie Meyer à
se présenter aurait été reconduite vers la chronique de la première.
`personnes_par_nom` renvoie donc une **liste**, et `resoudre()` un objet à
trois issues : aucune, une, plusieurs. Rendre une liste force l'appelant à
trancher, ce qui est précisément `EX-AUTH-05`.

**Deux cookies, deux rôles.** `acces` dit « cette personne a lu le carton » ;
`appareil` dit « ce téléphone, c'est cette personne ». L'un ouvre la porte,
l'autre reconnaît qui entre. Perdre le second ne coûte **aucun droit** : les
quotas sont rattachés à la personne (`EX-AUTH-03`), sans quoi effacer ses
cookies rendrait trois générations neuves.

**L'attribution est figée à la création** (`EX-AUTH-06`). Deux personnes
peuvent se succéder sur le même téléphone : le rattachement suit la dernière,
mais les chroniques déjà écrites gardent l'appareil de leur naissance.

## L'import des invités

**Rien ne s'écrit sans simulation préalable** (`EX-ADM-16`). `preparer()` calcule
un plan, `appliquer()` l'exécute — et **relit le classeur** au lieu de rejouer le
plan mémorisé : un plan calculé dix minutes plus tôt décrit une base qui a pu
changer entre-temps, quelqu'un ayant pu créer son personnage pendant la lecture
du rapport.

**Deux écarts assumés, tous deux protecteurs :**

*L'inactivation demande une case à cocher.* `EX-ADM-07` dit qu'une personne
retirée du fichier devient inactive. Pris à la lettre, un fichier ne contenant
qu'une table — pour corriger deux noms — désactiverait les quatre-vingt-dix
autres invités, en silence. L'exigence dit ce qui arrive aux personnes
*retirées* ; elle ne dit pas que tout fichier vaut liste complète. Sans la case,
l'import n'est jamais soustractif.

*Une personne ayant une chronique n'est jamais inactivée.* Elle sortirait de
`personnes_par_nom` (filtre `active` posé au morceau B) et ne pourrait plus
revoir son propre personnage. Le fichier ne fait pas autorité contre un fait
accompli. Le rapport les liste à part.

**Le classeur est conservé sur le volume**, dans `imports/`, horodaté : la
confirmation le relit, il part dans les instantanés, et l'on sait exactement ce
qui a été importé et quand. Le nom de fichier venant d'un champ de formulaire
est réduit à son dernier segment, sans quoi `../piege.xlsx` serait lu comme un
classeur.

**Le nom de famille est facultatif, le prénom ne l'est pas.** Sur la vraie
liste, 48 invités sur 93 n'avaient pas de nom : le conjoint d'un cousin, l'ami
dont on n'a jamais su le nom. Les exiger rejetait la moitié du fichier et
forçait à inventer. La clé devient `(prénom, "")`, et deux « Sophie » sans nom
déclenchent le conflit d'`EX-ADM-15` comme deux homonymes ordinaires — rien
n'est relâché, c'est la règle qui devient juste. `noms.initiales` tenait déjà :
« Coralie » donne `C.`, « Anne-Marie » donne `A.-M.`.

**Les erreurs de lecture se groupent par nature.** Le premier rapport alignait
quarante-huit fois « prénom ou nom manquant » : ça ne se lit pas, et ça cache
les autres erreurs sous la répétition.

**Les lignes d'exemple du gabarit sont signalées.** Oubliées dans un fichier
rempli, elles fabriqueraient des invités fictifs au milieu des vrais. La
détection porte sur la **ligne entière** — table, genre et rôle compris — et
non sur le seul couple (prénom, nom) : la vraie liste contenait un
« Jean-Pierre Gagnebin », mes noms d'exemple venant des tests du projet, et le
rapport accusait un vrai invité d'être fictif. Un garde-fou qui crie au loup
use la confiance qu'on lui porte, et c'est le jour où il aura raison qu'on ne
le lira plus.

## Interface

**Réutiliser les composants existants.** `.choix` sert au questionnaire comme
au sommaire de reprise : même fond, même bordure, même hauteur de frappe.
Inventer une apparence pour un écran le fait détonner, et rien n'indique plus
ce qui se touche.

**Une cible se touche à une main, à 22 h, écran baissé.** Le marqueur natif de
`<details>` fait huit pixels : le résumé porte donc `.action.sobre` et occupe
toute la largeur, avec le coût en dessous, dans la zone de frappe.

**La feuille de style porte son empreinte** — `style.css?v=…`, calculée au
démarrage. Sans elle, les gabarits se mettent à jour et le style reste figé
dans le cache du navigateur : une correction d'affichage faite le soir de
l'événement serait invisible pour tous ceux qui ont ouvert la page plus tôt,
c'est-à-dire pour tout le monde. *Défaut constaté le 20 août.*

## Tests : ce qu'une assertion doit mesurer

Deux règles, payées cher le 20 août.

**Comparer un écart, pas une valeur absolue.** `nb_tentatives == 2` passait
quoi qu'il arrive, parce que `enregistrer_portrait` journalise une tentative
*et* une génération : le compteur valait déjà 2 avant l'action mesurée.

**Prendre la référence avant l'action, pas après.** Un état capturé après une
première visite de l'écran photographie les dégâts et les appelle la normale :
l'assertion ne peut alors plus rien détecter. *Constaté trois fois le 20 août,
toujours sous cette forme.*

**Attendre le fil avant de mesurer.** Les générations partent en arrière-plan.
Une mesure prise juste après la requête constate l'état d'avant le travail
qu'elle prétend vérifier. Le helper `_attendre(condition)` sert à ça.

**Un numéro écrit en dur dans une assertion est presque toujours faux.** Trois
fois le 25 août : lignes 6 et 8 attendues pour un YAML qui les portait en 3 et
7, lignes 1 et 3 pour un classeur dont l'en-tête occupe la ligne 1. Le numéro
se **dérive** du contenu qu'on vient d'écrire.

**Un test de traversée de chemin doit viser une cible qui existe.** « Le fichier
`../../config.yaml` est-il refusé ? » passait grâce à l'absence de la cible, pas
grâce au filtre. Poser un vrai classeur atteignable, et vérifier d'abord qu'il
l'est.

**Une assertion qui cherche une chaîne dans un fichier entier peut être
satisfaite par un commentaire.** Deux fois le 25 août : `« empreinte » not in
panne.py` échouait sur le mot écrit dans une explication, et `« serveur:app »
in Dockerfile` passait encore après retour à `main:app`, parce que le
commentaire qui justifiait le choix contenait la chaîne. Contrôler la
**structure** — les imports par `ast`, la ligne `CMD` isolée — et non le texte.

**Un cas de test trop petit n'exerce pas l'assertion qu'il porte.** Le message
d'essai du bloc d'erreur était trop court pour produire assez de lignes : le
repliage n'était jamais atteint, et l'assertion qui le surveillait ne pouvait
pas échouer. Les cas de test reprennent depuis les **messages réels** des
incidents.

**Jinja échappe le contenu des variables, pas le texte des gabarits.** Une
assertion cherchant « n'a » dans une réponse échoue sur `n&#39;a` — et la faute
ne se voit que sur les messages *dynamiques*, ce qui la rend d'autant plus
déroutante. `test_identite.texte()` déséchappe avant de comparer.

**Une mutation qui ne fait rien tomber n'accuse pas toujours le test.** Retirer
le contrôle de chronique existante dans `main.py` n'a rien cassé : `bd.creer()`
porte le même garde-fou. Deux barrages pour une même règle, et c'est voulu —
la mutation devait donc retirer les deux. Mais retirer `definir_genre`, lui, ne
cassait rien parce que le test ne couvrait que la création, où le genre arrive
par un autre chemin ; là, c'était bien un trou de couverture. Distinguer les
deux cas avant de conclure.

Et toute assertion nouvelle se vérifie **dans les deux sens** : on réintroduit
le défaut et on regarde le test tomber. Un test qui ne peut pas échouer ne
prouve rien.

## La file

Le worker démarre au `lifespan` et s'arrête à l'extinction. `WORKER_ACTIF=0`
l'inhibe : les tests entrent dans le cycle de vie et ne doivent pas se mettre
à consommer des appels d'API. Ils pilotent la file par `taches.traiter_une()`,
qui exécute une tâche ici et maintenant — une attente arbitraire produit des
tests qui passent une fois sur deux, et un test intermittent finit toujours
par être ignoré.

Trois règles apprises en écrivant ce module :

- **La réclamation est atomique.** `UPDATE … RETURNING` en une instruction ;
  un `SELECT` suivi d'un `UPDATE` laisserait une fenêtre où deux fils traitent
  la même tâche. Éprouvé à huit fils sur soixante tâches.
- **La tentative se décompte à la prise, non à l'échec.** Une tâche réclamée
  puis perdue dans un redémarrage a bien coûté un essai — sans quoi une tâche
  empoisonnée relancerait le service à chaque démarrage.
- **N'absorber qu'une erreur d'intégrité connue.** `mettre_en_file` ne tait que
  le doublon d'`EX-IA-43` ; un type inconnu remonte. SQLite ne nomme pas
  l'index partiel dans son message — il dit « UNIQUE constraint failed:
  tache.objet_uuid » —, c'est donc sur ce texte qu'on discrimine.

## Sauvegardes

**Aucun interrupteur.** Une sauvegarde qu'on peut éteindre est une sauvegarde
qui sera éteinte le jour où elle compte. La boucle tourne toutes les trois
minutes sans condition ; c'est le **dépôt** qui est conditionnel.

**Rien ne part si rien ne change.** Deux instantanés d'une base inchangée sont
identiques au bit près — vérifié. Dix jours d'attente avant l'événement
déposeraient sinon 4 800 fois le même fichier, soit 788 Mo pour zéro
information.

**Le piège, et pourquoi l'empreinte porte sur le contenu métier.** Écrire la
ligne `sauvegarde` d'un dépôt modifie la base : l'instantané suivant diffère,
donc il se redépose, et la boucle se nourrit d'elle-même. `sauvegarde` et
`tache` sont donc exclues de l'empreinte. Elle porte sur **toutes les lignes de
toutes les autres tables**, jamais sur une sélection de compteurs et de dates —
une colonne oubliée dans une telle liste produirait un changement invisible,
donc une sauvegarde qui n'a pas lieu.

**Un plancher de six heures.** Sans lui, dix jours de calme seraient
indiscernables d'une panne silencieuse des deux dépôts.

**L'empreinte n'est mémorisée qu'après un dépôt réussi quelque part**, et dans
un fichier du volume — sinon chaque redéploiement reverserait un instantané
identique, et un échec des deux destinations serait pris pour un succès.

## Écarts assumés

| Écart | Raison | Échéance |
|---|---|---|
| `EX-I18N-01` — aucun texte affiché n'est externalisé | `EX-I18N-02` est retirée, la langue est `fr`, aucune seconde langue n'est prévue, et l'événement est dans onze jours. Le bénéfice invoqué — corriger un libellé sans redéployer — ne s'obtiendrait pas avec un fichier de textes dans le dépôt : il faudrait le porter sur le volume avec toute la mécanique d'empreinte de `questions.yaml` | aucune |
| `EX-SEC-05` — la porte ne compte pas les échecs par adresse IP | cent invités sur le wifi de la salle, ou derrière le NAT d'un même opérateur, partagent une adresse publique : un verrou par IP transformerait dix fautes de frappe en panne collective à 21 h. Remplacé par un délai d'une demi-seconde après échec, qui ralentit une énumération sans jamais fermer la porte à quelqu'un qui a le carton sous les yeux | accepté tel quel |
| La CSP autorise `'unsafe-inline'` sur `script-src` | l'accueil, le questionnaire et le fragment de portrait portent leur comportement en `<script>` inline. Les extraire à onze jours de l'événement coûterait plus de risque qu'il n'en retire, et le rempart contre l'injection reste l'échappement Jinja2 (`EX-SEC-02`), qui est actif. Les nonces sont la bonne réponse, après l'événement | après l'événement |
| La détection de doublon est **exacte**, pas encore approximative | `EX-AUTH-05` demande « un Jean-Pierre Meier existe déjà, c'est vous ? ». L'écran de choix existe depuis l'étape 2 et se déclenche sur un nom identique ; élargir son déclenchement à une distance d'édition ne touchera plus que la requête | étape 2, morceau D |
| `config.py` ne valide que le bloc `projet:` ; `acces`, `quotas`, `ia`, `tables` sont exposés bruts | valider une forme avant d'avoir écrit le code qui la consomme, c'est la deviner | étape 2 |
| Le contrôle `EX-SEC-18` se met en veille si `PRENOM_MARIEE` et `PRENOM_MARIE` sont absents de l'environnement | c'est le seul dessin qui n'exige pas d'écrire les prénoms dans un fichier versionné. Le garde-fou est l'exécution locale avec le `.env` chargé ; il n'y a pas d'intégration continue dans ce projet | accepté tel quel |
| `etat_soiree` a une clé primaire entière et non un UUID (`EX-GEN-02`) | table à une seule ligne : une clé UUID n'y apporte rien et retire la garantie qui compte, qu'il n'y ait jamais deux phases simultanées. La contrainte `id = 1` le dit | accepté tel quel |
| `EX-IA-43` est portée par un index unique partiel, mais la mise en file n'existe pas encore : `main.py` se contente de refuser si l'état est `en_cours` | vérification suivie d'écriture, donc théoriquement joueuse. La file rendra la course impossible | étape suivante |
| `.dockerignore` est une liste d'exclusion, non d'inclusion | conforme à la lettre d'`EX-SEC-17`. Une liste d'inclusion couvrirait un nouveau type de fichier sensible, mais tout module oublié ferait échouer le démarrage — et `EX-SAU-09` gèle les déploiements le 5 septembre | accepté tel quel |
