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
| `test_admin.py` | tables et régions modifiables, onglets, semis non destructif |

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

Une valeur dérivée ne peut pas se désynchroniser. Le tableau ci-dessous est
volontairement sans compte : il a commencé à trois, et chaque fois qu'on a
voulu stocker un chiffre, c'est qu'il fallait le recalculer.

| Grandeur | Dérivée de | Exigence |
|---|---|---|
| l'identité d'un projet | le nom de son dossier | `EX-PRJ-01` |
| les doublons de noms fictifs | les noms fictifs normalisés | `EX-IA-44` |
| `nb_generations`, `nb_tentatives` | le journal | `EX-GEN-07`, `EX-IA-21` |
| `chronique.etage` | les clés de réponses présentes | `EX-QUE-11` |
| le libellé d'une région | son code stable | `EX-IA-28`, `EX-IA-42` |
| le budget de photo d'une personne | dépôts − échecs de conversion − crédits, depuis la dernière borne | `EX-PHO-37`, `EX-GEN-07` |
| les trois budgets d'une table | les enluminures vivantes, et le journal pour les envois et suppressions | `EX-CDT-14` |
| le rôle de Gardien | `personne.est_responsable`, moins les mariés, moins les sans-table | `EX-CDT-12` |
| la divergence réponses / portrait | trois dates du journal comparées | `EX-QUE-11`, `EX-ADM-19` |
| « ce Gardien s'est-il manifesté » | l'existence de sa chronique | `EX-CDT-12` |
| les photos hors du stockage objet | le journal des copies | `EX-SAU-01` |
| la phase de la soirée | l'absence de `lecture_seule` vaut « ouvert » | `EX-CYC-16` |

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

**La sélection dans la liste, et trois règles de rapprochement.** L'annuaire
part **entier** dans la page — 93 noms font deux kilo-octets — et le filtre se
fait en JavaScript, sans requête : il fonctionne encore si la 4G de la salle
flanche, là où une recherche serveur ferait un aller-retour par frappe.

`EX-AUTH-05` — **jamais flou sur les deux composantes à la fois.** Trois règles,
chacune exigeant une composante exacte : nom identique et prénom proche, prénom
identique et nom proche, prénom identique et nom **absent en base**. Un flou
double rapprocherait « Martin Durant » de « Martine Durand » — 0,923 et 0,833 —
qui sont deux personnes, souvent un couple, et noierait chaque famille
nombreuse sous des confirmations.

*Le seuil se choisit sur les deux bords.* Mesuré sur la liste réelle, aucun
seuil entre 0,75 et 0,90 ne produit le moindre faux positif : 0,85 semblait
donc gratuit — et rejetait « Meier » contre « Meyer », l'exemple même du
briefing, qui vaut 0,800. Un seuil mesuré sur les seuls faux positifs n'est pas
mesuré. `test_identite.py` éprouve les deux bords, cas visés et cas à rejeter.

*La troisième règle fait tout le travail.* Sur la liste réelle, la distance
d'édition ne se déclenche jamais — les homonymes de nom de famille y portent
des prénoms trop éloignés. Les seuls rapprochements viennent des 48 invités
importés sans nom de famille : sans cette règle, chacun créerait un doublon en
tapant son vrai nom.

**Deux cookies, deux rôles.** `acces` dit « cette personne a lu le carton » ;
`appareil` dit « ce téléphone, c'est cette personne ». L'un ouvre la porte,
l'autre reconnaît qui entre. Perdre le second ne coûte **aucun droit** : les
quotas sont rattachés à la personne (`EX-AUTH-03`), sans quoi effacer ses
cookies rendrait trois générations neuves.

**L'attribution est figée à la création** (`EX-AUTH-06`). Deux personnes
peuvent se succéder sur le même téléphone : le rattachement suit la dernière,
mais les chroniques déjà écrites gardent l'appareil de leur naissance.

## Ce qui s'affiche se modifie, ce qui identifie ne bouge jamais

Deux couples, même principe, tous deux posés par la migration `0002` :

| Identifie | S'affiche |
|---|---|
| `chronique.lieu` = `lieu_02` | `region.libelle` = « Fondcombe », `region.locution` = « à Fondcombe » |
| `table_groupe.code` = « 3 » | `table_groupe.nom` = « Andúril » |

*Le défaut payé :* l'import rapprochait les tables par leur **nom**. Renommer
la table « 3 » en « Fondcombe » puis réimporter le fichier — qui porte toujours
`Table = 3` — créait une **seconde** table « 3 » et y déplaçait ses dix
invités, en silence. Le code est ce que porte le fichier, le nom est ce que
lisent les invités.

**Les régions vivent en base, pas dans `questions.yaml`.** `EX-ADM-22` veut la
modification « y compris après ouverture de la soirée » ; le fichier est chargé
au démarrage, donc un renommage à 21 h n'y prendrait effet qu'au redéploiement
suivant, que `EX-SAU-09` interdit ce soir-là. Et le réécrire depuis une page
web détruirait ses commentaires, qui sont la référence éditoriale du projet.
Le fichier porte les **valeurs par défaut**, semées au démarrage ; la base fait
autorité ensuite. **Le semis n'écrase jamais** : sans cela, chaque redémarrage
effacerait le travail de la soirée.

**La coïncidence entre noms de tables et noms de régions est voulue** —
`EX-ADM-22` : *« ils sont destinés à reprendre les noms de tables choisis par
les mariés, en clin d'œil »*. Là où l'on est assis et là où l'on est convoqué
n'ont aucune raison de coïncider, et l'écran d'attente le dit : « Le Conseil
vous convoquera à Fondcombe. **Pas ce soir** : ce soir vous êtes assis parmi
nous. » Aucun contrôle n'interdit donc de nommer une table du nom d'une région.

**La locution porte sa préposition** — « en Comté », « aux Havres Gris » — parce
qu'elle s'écrit dans une phrase. Les gabarits écrivaient « en » en dur, ce qui
donnait « convoqué en Les Havres Gris » sur l'écran que tous les invités
voient. Le futur (« convoquera ») évite au passage l'accord que le passé
composé imposait.

**Aucune couleur ne s'écrit dans un gabarit.** Elles vivent toutes dans
`style.css`, où elles se corrigent une fois pour tous les écrans — et où la
palette du projet est la seule source. Le 25 août, trois gabarits portaient
des codes hexadécimaux inventés sur place, qui n'appartenaient à aucune
palette. `test_affichage.py` refuse désormais tout `style="…color…"` dans un
gabarit.

**Un lien qui est un bouton n'est pas un lien.** `a:link` pèse plus lourd que
`.action` — un élément plus une pseudo-classe contre une simple classe — donc
la règle générale des liens écrasait la couleur du bouton : texte laiton sur
fond laiton. Seul `a:hover` le rattrapait, ce qui ne se voit qu'à la souris ;
au doigt, sur téléphone, le bouton était vide. Toute classe portée par un `<a>`
et qui pose un fond doit avoir ses règles `a.classe:link` **et**
`a.classe:visited`, et `test_affichage.py` le déduit des gabarits : un futur
`<a class="bouton-neuf">` sera signalé sans qu'on y pense.

**Le survol ne répare jamais rien.** Sur téléphone il n'existe pas, et un état
qui n'existe pas ne peut pas rendre lisible ce qui ne l'est pas. Il ne change
que la teinte.

**Les liens sont stylés explicitement, `:visited` compris.** Sans règle `a
{ color }`, tout lien hors bouton prend le bleu du navigateur, et le violet dès
qu'il a été suivi une fois — illisibles sur fond nocturne. Le laiton est la
seule couleur d'accent du projet, celle des boutons, donc celle que l'œil a
déjà appris à suivre. Un lien dans un paragraphe `.discret` reste en brume : il
n'a pas à crier plus fort que la phrase qui le porte.

**Les onglets d'administration sont des liens**, pas du JavaScript : chaque
écran a son adresse, donc se recharge et se rouvre après une coupure. Un onglet
qui vit en mémoire est un onglet perdu dès que l'écran du téléphone se
verrouille.

## Les questions fermées, et le champ libre

`EX-QUE-17` — **deux remèdes pour deux problèmes distincts.** À six options et
cent invités, dix-sept personnes partagent le même défaut : plus d'options agit
sur **tout le monde**, le champ libre agit sur celui à qui rien ne convient.
Les deux se cumulent ; ce ne sont pas deux façons de faire la même chose.

| Question | Options | Champ libre | Pourquoi |
|---|---|---|---|
| `defaut`, `colere` | 8 | oui | traits de caractère, transposés librement |
| `role_groupe` | 7 | oui | idem — elle n'en avait que 5 |
| `lien` | 5 | oui | « Autrement » était un cul-de-sac : celui qui la choisissait livrait **zéro** indice. Pas d'option de plus : c'est un palier d'indice, il doit rester précis |
| `attachement` | 6 | **non** | détermine le peuple, croisé avec l'allégeance (`EX-IA-09`). Une réponse libre laisserait le modèle choisir seul et la répartition sur les dix-huit peuples cesserait d'être maîtrisée |
| `allegeance`, `monstre`, `destin` | 2 | **non** | binaires et structurantes |

**Le bouton reste le chemin par défaut.** À 22 h, un verre à la main, taper
coûte dix fois plus que toucher : « Autre » se place en dernier, discret, et
c'est le **seul bouton du questionnaire qui n'enchaîne pas** — il déplie un
champ. D'où son aspect distinct : identique aux autres, il serait vécu comme un
bouton en panne.

**Le texte libre part sous la clé de la question**, pas sous une clé à part :
`ia.py` ne change pas, `reponses_json` reste homogène, et aucune clé n'est
renommée — le banc d'essai figé reste relisible. `EX-SEC-16` traite déjà les
réponses comme des données non fiables.

## La table de test

`EX-PRJ-10` — elle reste **active en production**. Le test de fumée du jour J
se fait sur la vraie base, avec la vraie clé et le vrai modèle : une répétition
ailleurs n'éprouverait pas ce qui va servir.

D'où l'étanchéité qui va avec. `est_test` est **hérité** par tout ce qu'un
testeur crée, et `lister()` comme `tables()` l'excluent **par défaut** —
l'inverse ferait apparaître dix personnages fictifs sur la carte le jour où
l'on oublierait le drapeau quelque part. Le défaut sûr est celui qui protège
quand on oublie.

Le semis **réaffirme** le drapeau à chaque démarrage : une personne de test qui
l'aurait perdu reparaîtrait dans les listes, et c'est le genre de chose qu'on
ne remarque qu'après coup.

Le bandeau `MODE TEST` se **dérive** d'une chronique réellement en base — cinquième
grandeur du projet à suivre cette règle. Un interrupteur dirait ce qu'on a
réglé ; ceci dit ce qui est.

## Le palier de débit

Relevé sur **chaque réponse** de l'API, dans `debit.py`, et affiché au tableau
de bord. Le point 8 de l'annexe C demandait de le lire sur la console
Anthropic : une lecture ponctuelle, hors de l'application, périmée le lendemain
et invisible le soir où elle compterait.

Relevé **avant** l'aiguillage sur le code HTTP : les en-têtes sont présents sur
un `429` comme sur un succès, et c'est justement quand ça sature qu'on veut le
chiffre. La trace l'emporte, donc le journal garde le palier au moment exact où
il a lâché — ce qu'aucune console ne dira après coup.

**Il ne régule rien.** `taches.py` réessaie déjà sur `ErreurDebit` en
respectant le `retry-after`. Les mesures donnent 59 % du plafond de sortie à
huit fils : une régulation proactive coûterait plus de risque qu'elle n'en
retire.

**Il n'est pas persisté, et il porte son âge.** Les compteurs se
réinitialisent à la minute : un plafond restant d'il y a trois heures ne dit
rien, et le garder en base donnerait un chiffre qu'on croirait actuel. Un axe
absent est **omis**, jamais mis à zéro — zéro voudrait dire « plus de budget »,
le contraire de « on ne sait pas ».

*Paliers relevés le 26 août pour Claude Sonnet 5* : 1 000 requêtes/min,
500 000 jetons d'entrée/min, **80 000 jetons de sortie/min**. Le débit de
sortie est le seul axe contraignant — huit fils en consomment 59 %, contre 24 %
de l'entrée et 3 % des requêtes. Treize fils le satureraient. La limite vaut
pour toute l'**organisation** : un autre outil appelant l'API pendant la soirée
puiserait au même budget.

## L'administration, et ce qui sort d'elle

Quatre onglets — **Invités · Tables · Régions · Tableau** — tous derrière
`MOT_DE_PASSE_ADMIN`. `/deviner` reste **hors** de ces onglets : c'est l'écran
des mariés, et `EX-AUTH-20` leur donne leur propre mot de passe.

Le tableau sépare **production** et **test**, chacun à son adresse. Il était
devenu aveugle au test depuis que `lister()` l'exclut — c'était pourtant
l'endroit même où l'on vérifie le test de fumée du jour J.

**Un export dit ce qu'il est, dans son enveloppe ET dans son nom de fichier.**
Deux tableaux JSON nus ne se distinguent pas une fois sur le disque : l'un
productif, l'autre de test, seraient interchangeables au moment où l'on s'en
sert. Les deux marques sont posées parce que l'une des deux se perd toujours —
le nom en renommant le fichier, l'enveloppe en l'ouvrant au milieu.

`EX-TST-08` — l'export de production exclut le test, toujours ; l'export de
test ne contient que lui. Les anciennes adresses `/tableau` et
`/tableau/export.json` répondent en `308` : elles sont en signet et sur des
notes.

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

**`grep -c` compte des lignes, il ne dit pas si le test a réussi.** Le 25 août,
un fichier affichait seize blocs verts et échouait au dix-septième : le compte
était juste, le test était rouge. Une suite se lance sur son **code de
retour**, jamais sur ce qu'elle a écrit.

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

**`commande | head || repli` n'exécute jamais le repli.** Le `||` porte sur le
dernier maillon du tube, et `head` réussit toujours. Le 25 août, le bloc qui
devait ajouter les styles d'administration n'a donc jamais tourné — et le
défaut ne s'est vu qu'à l'écran, deux échanges plus tard. Une commande dont la
sortie compte se vérifie sur sa sortie, pas sur son code de retour.

**Une mutation doit rester syntaxiquement valide.** Le 26 août, une mutation
mal formée a fait tomber la suite sur une `IndentationError` : le test n'avait
rien accusé, il avait mesuré le parseur. Le harnais contrôle désormais la
syntaxe par `ast` **avant** de lancer.

**Le motif d'une mutation doit être UNIQUE.** Vérifier qu'il existe ne suffit
pas. Le 27 août, `if photo is None or photo.supprimee:` apparaissait deux fois :
la mutation frappait la mauvaise, le test rendait vert, et l'on a failli en
conclure « redondance voulue » sans avoir rien muté. Le harnais exige une
occurrence et une seule.

**Une mutation morte doit se dénoncer.** Un motif absent laisse le test passer
et compte pour une réussite. Le harnais dit `MOTIF NON UNIQUE (0)` plutôt que
de continuer.

**Une chaîne cherchée telle quelle éprouve la mise en forme du gabarit.** Jinja
coupe les lignes là où l'auteur les a coupées : « il vous reste 3\n
changements » ne contient pas « 3 changements ». Replier les blancs et
déséchapper avant de comparer, comme le fait `test_identite.texte()`. Et
replier la casse : le titre « Quatre de plus » est capitalisé côté serveur.

**Un test de route n'éprouve pas le formulaire.** Le 27 août, le champ de dépôt
de photo de l'administrateur n'avait pas de `name` : le navigateur n'envoyait
rien, mais les tests postaient `files={"fichier": …}` en direct et passaient.
Trois sondes structurelles couvrent maintenant cette classe — tout champ dans
un formulaire porte un `name`, tout `<input type="file">` sans exception, et
toute case à cocher qui reflète un état stocké est précédée d'un champ caché de
même nom.

**Une case décochée n'est pas envoyée.** Sans champ caché avant elle, « absent »
se lit « pas de changement » et l'on ne peut jamais décocher, seulement cocher.

**Cibler la structure, pas le document.** Un découpage sur un nom échoue quand
ce nom paraît deux fois dans la même rangée — « Ludivine » y figure comme
prénom *et* dans « Ludivine du Val ». Viser la ligne, la balise, la classe.

**La file n'est pas à soi seul.** Compter les appels à `traiter_une()` suppose
qu'elle ne contient que ses propres tâches : faux dès qu'un bloc précédent en a
laissé une, et le test éprouve alors le travail de quelqu'un d'autre. Vider la
file jusqu'à ce qu'elle ne rende plus rien.

**Faire écouler un délai plutôt que l'attendre.** Une temporisation réelle rend
un test lent et intermittent — et un test intermittent finit par être ignoré.
On avance `reprendre_apres` à la main.

**Une sonde doit pouvoir accuser.** Vérifier qu'elle a bien examiné quelque
chose : « aucun fichier fautif » sur zéro fichier examiné est vert pour rien.

**Un test de traversée de chemin doit viser une cible qui existe.** « Le fichier
`../../config.yaml` est-il refusé ? » passait grâce à l'absence de la cible, pas
grâce au filtre. Poser un vrai classeur atteignable, et vérifier d'abord qu'il
l'est.

**Une chaîne cherchée dans toute une page vient souvent d'ailleurs.** Quatre
fois : `« empreinte »` trouvé dans un commentaire, `« serveur:app »` dans le
commentaire du Dockerfile, `value="…"` dans le champ caché plutôt que dans le
champ visible, `href="/admin/tableau"` dans le basculement de la page plutôt
que dans sa navigation. Cibler la **structure** — la ligne, la balise, l'autre
écran — et non le document.

**Une assertion qui cherche une chaîne dans un fichier entier peut être
satisfaite par un commentaire.** Deux fois le 25 août : `« empreinte » not in
panne.py` échouait sur le mot écrit dans une explication, et `« serveur:app »
in Dockerfile` passait encore après retour à `main:app`, parce que le
commentaire qui justifiait le choix contenait la chaîne. Contrôler la
**structure** — les imports par `ast`, la ligne `CMD` isolée — et non le texte.

**Un cas de test trop frais n'exerce pas une assertion sur le temps.** L'âge
d'un relevé vaut zéro dans la seconde qui suit, qu'il soit calculé ou figé : le
contrôle ne pouvait pas distinguer les deux. Faire **vieillir** l'objet plutôt
que d'attendre.

**Un cas de test trop petit n'exerce pas l'assertion qu'il porte.** Le message
d'essai du bloc d'erreur était trop court pour produire assez de lignes : le
repliage n'était jamais atteint, et l'assertion qui le surveillait ne pouvait
pas échouer. Les cas de test reprennent depuis les **messages réels** des
incidents.

**Jinja échappe le contenu des variables, pas le texte des gabarits.** Une
assertion cherchant « n'a » dans une réponse échoue sur `n&#39;a` — et la faute
ne se voit que sur les messages *dynamiques*, ce qui la rend d'autant plus
déroutante. `test_identite.texte()` déséchappe avant de comparer.

**Deux règles de même spécificité se départagent par leur ordre dans le
fichier.** `a.action` et `a:visited` pèsent pareil : une classe et une
pseudo-classe comptent dans la même colonne. Le bouton était donc correct par
l'endroit où la règle avait été collée, pas par sa spécificité — et la mutation
qui retirait `a.action:visited` ne cassait rien. Dépendre de l'ordre, c'est
dépendre de l'endroit où quelqu'un posera la prochaine règle.

**Une clé de configuration décorative est pire qu'une clé absente.** Le
30 août, `quotas.generations_par_personne` figurait dans `config.yaml` et
n'était lue nulle part : `MAX_GENERATIONS` valait 3 en dur. La changer sur le
volume n'aurait rien fait, et **on aurait cru avoir réglé quelque chose**. Une
sonde vérifie désormais que chaque clé du modèle est lue par le code, ou porte
la mention `NON LUE PAR LE CODE` à l'endroit même où elle est écrite. Deux
clés l'ont été de ce fait : `ia.plafond_appels` et `tables.nombre`.

**Un test qui interdit une chaîne la contient forcément.** Le 30 août,
`test_maries.py` vérifiait qu'aucun fichier ne cite `mot_de_passe_maries` — et
s'accusait lui-même. S'exclure du balayage est nécessaire, mais il faut alors
vérifier qu'il reste quelque chose à balayer, sinon la sonde passe au vert pour
rien.

**Replier la casse avant de comparer.** Le 30 août, une assertion cherchait
« quatre » dans une page qui affiche « Quatre de plus » : le titre est
capitalisé côté serveur. Comparer sans replier éprouvait la mise en forme.

**Choisir un sujet que la règle n'a pas déjà exclu.** Trois fois le 30 août :
la soupape éprouvée sur quelqu'un qui avait déjà ses trois messages — le
formulaire manquait à cause du quota, pas de la clôture ; le bouton de retrait
éprouvé sur une table aux cinq suppressions épuisées ; la place de la soupape
éprouvée sur le même invité saturé. Chaque fois on constatait une absence en
croyant constater une règle. **Avant d'affirmer qu'une chose manque parce que
la règle l'a retirée, vérifier qu'aucune autre règle ne l'avait déjà retirée.**

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
| La CSP autorise `blob:` sur `img-src` | `EX-PHO-26` exige la préparation côté navigateur par `URL.createObjectURL`, qui produit une URL `blob:`. Sans elle l'aperçu est bloqué, et **silencieusement** : une image vide, aucun message. L'écart autorise l'AFFICHAGE d'un fichier déjà choisi par l'invité, aucune exécution. Posé sur les seules routes qui en ont besoin, et dérivé de la constante `CSP` pour que les deux ne divergent pas | accepté tel quel |
| `table_groupe.code_responsable` est une colonne que rien n'écrit | `EX-AUTH-08` a été réécrite : le rôle se dérive de `est_responsable`, semé par l'import. Supprimer la colonne demanderait une migration à cinq jours de l'événement, pour retirer une donnée que personne ne lit | après l'événement |
| `EX-PHO-11` — « l'original est conservé intact » se borne à l'original **tel que livré par l'appareil** | mesuré le 26 août : Safari convertit le HEIC en JPEG à l'entrée de fichier, et l'Android de galerie n'envoie aucun EXIF. Ce qu'on reçoit est déjà un réencodage. Aucune page web ne peut atteindre le fichier de la pellicule | accepté tel quel |
| `EX-CDT-15` — « il remplace » se lit *retirer puis déposer*, sans bouton combiné | un geste unique laisserait le Gardien sans enluminure ET sans suppression si l'envoi échouait au milieu. Deux gestes coûtent la même chose et n'ont aucun état intermédiaire où l'on a perdu quelque chose | accepté tel quel |
| `EX-MAR-06` — le lieu des mariés est assigné comme les autres, puis corrigé à la main | l'exigence veut que l'administrateur décide ; il le peut depuis la fiche, avec l'effectif de chaque région sous les yeux. Un cas particulier dans `assigner_lieu` serait une seconde règle pour deux chroniques sur quatre-vingt-treize | accepté tel quel |
| `EX-ADM-08` — l'export imprimable se réduit au mot de passe d'accès | les dix codes de Gardien et celui des mariés n'existent plus. Le mot de passe vit dans `config.yaml` et s'écrit en clair au journal de démarrage : c'est lui qui rend la bascule vérifiable d'un coup d'œil | accepté tel quel |
| `EX-KSK-01` à `EX-KSK-11` — le poste kiosque n'est pas installé sur place | les invités sans téléphone ne seront pas présents. Le Raspberry Pi reste à domicile et ne fait plus que tirer une archive de l'application à intervalle régulier : il devient une **troisième copie**, hors Railway et hors Cloudflare, que ni l'une ni l'autre ne fournissait | à préciser hors étape 3 |
| Le défaut de la phase de soirée est **ouvert** | inversion assumée de la règle du défaut sûr : oublier de fermer laisse écrire des gens bornés par leurs quotas, oublier d'ouvrir laisse quatre-vingt-treize personnes devant une porte close le soir même. Le second est catastrophique, le premier bénin | accepté tel quel |
| `EX-IA-18` — le coupe-circuit de coût n'est pas implémenté | `ia.plafond_appels` figure dans `config.yaml` et n'est lu par aucun code, constaté le 30 août. Ce qui borne réellement les appels : un appui humain par régénération, l'index unique partiel d'`EX-IA-43` qui interdit deux générations en file pour une même chronique, et `MAX_TENTATIVES` côté invité. Poser un plafond dur à six jours de l'événement risquerait davantage d'arrêter une soirée qui fonctionne que d'attraper une boucle que la file rend déjà impossible | après l'événement |
| `tables.nombre` n'est lu par aucun code | le nombre de tables se dérive de celles qui existent en base, semées par l'import du tableur. La clé est **signalée comme telle dans le modèle**, et une sonde refuse désormais toute clé de configuration non lue et non signalée | accepté tel quel |
