"""Les dix entités de la section 5.1, en SQLAlchemy 2.0.

Conventions (EX-GEN-06) : les tables, colonnes et classes portent des noms
**français**, l'outillage reste en anglais. Aucun terme thématique n'apparaît
ici : peuples et lieux sont des données, jamais des identifiants (EX-GEN-01).

Trois choix méritent d'être lus avant le code.

**Aucune colonne de comptage.** `nb_generations` et `nb_tentatives` ont
disparu du schéma : les consommations se calculent depuis le journal
(EX-GEN-07, EX-IA-21). Un échec qui débiterait le quota redevient
structurellement impossible, au lieu d'être évité par une discipline
d'écriture — c'était le défaut relevé sur le banc d'essai.

**Le lieu est un code stable.** `chronique.lieu` contient `lieu_01`…`lieu_10`,
jamais un libellé (EX-IA-28, EX-IA-42). Renommer une région en pleine soirée
(EX-ADM-22) n'orpheline alors aucune chronique déjà produite.

**Les horodatages sont conscients du fuseau et en UTC.** SQLite ne stocke pas
de fuseau ; le type `HorodatageUTC` ci-dessous impose la conversion aux deux
bouts, ce qui rend impossible la confusion naïf/conscient (EX-GEN-04).
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, TypeDecorator, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def nouvel_uuid() -> str:
    """EX-GEN-02 — toutes les clés primaires sont des UUID."""
    return str(_uuid.uuid4())


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


class HorodatageUTC(TypeDecorator):
    """`DateTime` qui refuse de perdre le fuseau (EX-GEN-04).

    SQLite stocke une chaîne sans fuseau. Sans ce garde-fou, un `datetime`
    naïf entre en base et en ressort naïf : rien ne distingue plus une heure
    UTC d'une heure locale, et l'écart d'une ou deux heures ne se voit qu'au
    moment où il fausse une durée.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, valeur, dialect):
        if valeur is None:
            return None
        if valeur.tzinfo is None:
            raise ValueError(
                "horodatage naïf refusé : utiliser config.maintenant(), qui "
                "renvoie un datetime conscient en UTC (EX-GEN-04)"
            )
        return valeur.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, valeur, dialect):
        if valeur is None:
            return None
        return valeur.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class _CleUUID:
    """Clé primaire UUID, commune à neuf entités sur dix (EX-GEN-02)."""

    uuid: Mapped[str] = mapped_column(String(36), primary_key=True,
                                      default=nouvel_uuid)


# --------------------------------------------------------------------------- #
# Personnes et appareils
# --------------------------------------------------------------------------- #

class TableGroupe(_CleUUID, Base):
    """Le regroupement physique des invités.

    Depuis la v3.0 elle n'authentifie plus personne — il n'y a qu'un mot de
    passe global (EX-AUTH-18) — et n'entre dans aucun quota. Elle ne sert plus
    qu'au rôle de responsable et au regroupement de ses enluminures.

    `code_responsable` et `est_responsable` s'appelaient `code_chef` et
    `est_chef_de_train` : un titre ferroviaire en nom de colonne, ce
    qu'EX-GEN-01 interdit. Le nom neutre survivra au prochain thème.
    """

    __tablename__ = "table_groupe"

    # EX-ADM-22 — le CODE est ce que porte le fichier Excel (« 3 ») et ce sur
    # quoi l'import rapproche ; le NOM est ce que les invités lisent
    # (« Fondcombe »), modifiable jusqu'au dernier moment.
    #
    # Sans cette séparation, renommer une table puis réimporter le fichier
    # créait une SECONDE table portant l'ancien numéro et y déplaçait ses dix
    # invités, en silence. Même principe que `chronique.lieu` : un code stable,
    # un libellé qui n'est qu'un paramètre d'affichage.
    code: Mapped[str] = mapped_column(String(40))
    nom: Mapped[str] = mapped_column(String(80))
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    code_responsable: Mapped[str | None] = mapped_column(String(40))
    est_test: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ux_table_groupe_code", "code", unique=True),
    )


class Region(Base):
    """Les dix régions de la carte, telles qu'on les AFFICHE (EX-ADM-22).

    **Pourquoi en base et non dans `questions.yaml`.** `EX-ADM-22` veut que les
    libellés se modifient « y compris après ouverture de la soirée ».
    `questions.yaml` est chargé au démarrage : une modification n'y prendrait
    effet qu'au redéploiement suivant, ce qu'`EX-SAU-09` interdit le 5
    septembre. Et le réécrire depuis une page web détruirait ses commentaires,
    qui sont la référence éditoriale du projet.

    `questions.yaml` porte donc les valeurs **par défaut**, semées ici au
    premier démarrage ; cette table fait autorité ensuite. Une seule autorité à
    l'exécution, une valeur initiale documentée — comme le nom du dossier de
    projet.

    **La clé primaire est le code**, pas un UUID : écart assumé à `EX-GEN-02`,
    au même titre qu'`EtatSoiree`. `lieu_01` est déjà stable et unique par
    construction (`EX-IA-42`), et c'est lui que portent les chroniques ; lui
    superposer un UUID ajouterait une indirection sans rien garantir de plus.

    Renommer une région n'orpheline aucune chronique : `chronique.lieu` stocke
    le code, jamais le libellé (`EX-IA-28`, `EX-IA-42`).
    """

    __tablename__ = "region"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    libelle: Mapped[str] = mapped_column(String(80))
    # « en Comté », « à Fondcombe », « aux Havres Gris » — la préposition fait
    # partie du libellé, sinon les gabarits en choisissent une au hasard.
    locution: Mapped[str] = mapped_column(String(120))
    # Le pendant d'ombre : où se tient celui qui a choisi l'Ombre, à la marge
    # de la même région (EX-IA-11).
    ombre: Mapped[str] = mapped_column(String(160))
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    modifie_le: Mapped[datetime] = mapped_column(HorodatageUTC,
                                                 default=maintenant,
                                                 onupdate=maintenant)


class Personne(_CleUUID, Base):
    """L'invité. Tout quota lui est rattaché, jamais à son appareil.

    Perdre son cookie ne coûte donc aucun droit : on se reconnecte et on
    retrouve sa chronique et ses crédits restants (EX-AUTH-02, EX-AUTH-03).
    """

    __tablename__ = "personne"

    table_uuid: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("table_groupe.uuid"))
    prenom: Mapped[str] = mapped_column(String(80))
    nom: Mapped[str] = mapped_column(String(80))

    # EX-IA-36 — le genre vient de la colonne `Genre` de l'import, jamais du
    # questionnaire. Seul l'invité créé en saisie libre y répond, à l'écran
    # d'identité. NULL vaut « au choix du modèle » et non « sans genre » : un
    # portrait français non genré est illisible (EX-IA-37).
    genre: Mapped[str | None] = mapped_column(String(10))

    identifiant_import: Mapped[str | None] = mapped_column(String(80))
    est_responsable: Mapped[bool] = mapped_column(Boolean, default=False)
    est_marie: Mapped[bool] = mapped_column(Boolean, default=False)
    est_test: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="saisie_libre")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("genre IS NULL OR genre IN ('masculin', 'feminin')",
                        name="ck_personne_genre"),
        CheckConstraint("source IN ('import', 'saisie_libre', 'kiosque')",
                        name="ck_personne_source"),
        # EX-ADM-13 — clé de rapprochement de l'import quand elle est fournie.
        Index("ux_personne_identifiant_import", "identifiant_import",
              unique=True, sqlite_where=text("identifiant_import IS NOT NULL")),
        Index("ix_personne_nom", "nom", "prenom"),
    )


class Appareil(Base):
    """Le cookie d'appareil, simple raccourci (EX-AUTH-02).

    Sa clé primaire est la valeur du cookie elle-même, conformément à la
    section 5.1 — il n'y a donc pas de colonne `uuid` distincte.
    """

    __tablename__ = "appareil"

    uuid: Mapped[str] = mapped_column(String(36), primary_key=True)
    personne_uuid: Mapped[str] = mapped_column(
        String(36), ForeignKey("personne.uuid"), index=True)
    premiere_vue: Mapped[datetime] = mapped_column(HorodatageUTC,
                                                   default=maintenant)
    derniere_vue: Mapped[datetime] = mapped_column(HorodatageUTC,
                                                   default=maintenant)


# --------------------------------------------------------------------------- #
# Chroniques
# --------------------------------------------------------------------------- #

class Chronique(_CleUUID, Base):
    """Le personnage transposé.

    `reponses_json` est la seule vérité (EX-GEN-08) : `portrait`, `nom_fictif`,
    `peuple` et `indice` en sont des dérivés régénérables. Une chronique perdue
    se réécrit ; une réponse perdue est perdue pour toujours. C'est ce qui
    justifie l'instantané toutes les trois minutes (EX-SAU-13) et la relance
    différée sans limite de temps (EX-IA-23).
    """

    __tablename__ = "chronique"

    personne_uuid: Mapped[str] = mapped_column(
        String(36), ForeignKey("personne.uuid"), index=True)
    appareil_uuid: Mapped[str | None] = mapped_column(String(36))
    est_test: Mapped[bool] = mapped_column(Boolean, default=False)

    # EX-IA-28, EX-IA-42 — code stable `lieu_01`…`lieu_10`, jamais le libellé.
    # Le libellé est un paramètre d'affichage, éditable en pleine soirée.
    lieu: Mapped[str] = mapped_column(String(20), index=True)

    reponses_json: Mapped[str] = mapped_column(Text)
    etage: Mapped[int] = mapped_column(Integer, default=1)

    nom_fictif: Mapped[str | None] = mapped_column(String(120))
    peuple: Mapped[str | None] = mapped_column(String(40))
    portrait: Mapped[str | None] = mapped_column(Text)
    indice: Mapped[str | None] = mapped_column(Text)
    fuites_noms_json: Mapped[str | None] = mapped_column(Text)

    modele: Mapped[str | None] = mapped_column(String(60))
    duree_s: Mapped[float | None] = mapped_column(Float)
    jetons_entree: Mapped[int | None] = mapped_column(Integer)
    jetons_sortie: Mapped[int | None] = mapped_column(Integer)

    # Aucune colonne de comptage ici : `nb_generations` et `nb_tentatives` se
    # calculent depuis le journal (EX-GEN-07, EX-IA-21).

    etat: Mapped[str] = mapped_column(String(20), default="en_attente",
                                      index=True)
    derniere_erreur: Mapped[str | None] = mapped_column(Text)
    validee: Mapped[bool] = mapped_column(Boolean, default=False)
    supprimee: Mapped[bool] = mapped_column(Boolean, default=False)
    creee_le: Mapped[datetime] = mapped_column(HorodatageUTC,
                                               default=maintenant)
    modifiee_le: Mapped[datetime] = mapped_column(HorodatageUTC,
                                                  default=maintenant,
                                                  onupdate=maintenant)

    __table_args__ = (
        CheckConstraint(
            "etat IN ('brouillon','en_attente','en_cours','prete','echouee')",
            name="ck_chronique_etat"),
        CheckConstraint("etage IN (1, 2)", name="ck_chronique_etage"),
        # EX-IA-26 — une seule chronique par personne. Deux chroniques
        # produiraient deux marqueurs sur la carte, dont un que les mariés ne
        # pourraient jamais deviner. La condition sur `supprimee` laisse
        # l'administrateur repartir de zéro pour un invité (EX-GEN-03).
        Index("ux_chronique_personne", "personne_uuid",
              unique=True, sqlite_where=text("supprimee = 0")),
    )


# --------------------------------------------------------------------------- #
# Photos et réclamations
# --------------------------------------------------------------------------- #

class Photo(_CleUUID, Base):
    """Photo personnelle de l'invité, ou enluminure d'une table.

    `etat = 'echouee'` signifie **échec de conversion**, jamais échec d'envoi :
    l'original reste intact sur le volume (EX-PHO-33, EX-PHO-11).
    """

    __tablename__ = "photo"

    personne_uuid: Mapped[str] = mapped_column(
        String(36), ForeignKey("personne.uuid"), index=True)
    table_uuid: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("table_groupe.uuid"), index=True)
    portee: Mapped[str] = mapped_column(String(20))
    est_test: Mapped[bool] = mapped_column(Boolean, default=False)
    chemin_original: Mapped[str] = mapped_column(String(400))
    chemin_web: Mapped[str | None] = mapped_column(String(400))
    chemin_vignette: Mapped[str | None] = mapped_column(String(400))
    etat: Mapped[str] = mapped_column(String(20), default="traitement")
    # EX-GEN-03 — suppression douce ; le fichier n'est jamais détruit.
    supprimee: Mapped[bool] = mapped_column(Boolean, default=False)
    supprimee_le: Mapped[datetime | None] = mapped_column(HorodatageUTC)
    creee_le: Mapped[datetime] = mapped_column(HorodatageUTC,
                                               default=maintenant)

    __table_args__ = (
        CheckConstraint("portee IN ('personnelle', 'table')",
                        name="ck_photo_portee"),
        CheckConstraint("etat IN ('traitement', 'prete', 'echouee')",
                        name="ck_photo_etat"),
    )


class Reclamation(_CleUUID, Base):
    """Signalement d'un invité sur un objet le concernant."""

    __tablename__ = "reclamation"

    personne_uuid: Mapped[str] = mapped_column(
        String(36), ForeignKey("personne.uuid"), index=True)
    objet_type: Mapped[str] = mapped_column(String(30))
    objet_uuid: Mapped[str] = mapped_column(String(36), index=True)
    texte: Mapped[str] = mapped_column(Text)
    traitee: Mapped[bool] = mapped_column(Boolean, default=False)
    creee_le: Mapped[datetime] = mapped_column(HorodatageUTC,
                                               default=maintenant)


# --------------------------------------------------------------------------- #
# File de tâches
# --------------------------------------------------------------------------- #

class Tache(_CleUUID, Base):
    """La file d'attente persistée (EX-ARC-09).

    Elle est le **régulateur de débit** (EX-IA-24) : le nombre de fils du
    worker borne mécaniquement les appels simultanés. La file absorbe, elle ne
    rejette jamais — aucun invité ne doit lire « revenez plus tard »
    (EX-IA-25).

    `priorite` est croissante en urgence décroissante : la génération de
    chronique passe avant la conversion d'image, parce qu'un invité attend
    devant son écran alors qu'une photo se traite en silence (EX-ARC-12).

    L'instantané de la base **n'est pas** une tâche de cette file : mis en
    file, il attendrait derrière cent générations au moment précis où il
    compte le plus (EX-SAU-18).
    """

    __tablename__ = "tache"

    PRIORITE_GENERATION = 10
    PRIORITE_CONVERSION = 50
    PRIORITE_COPIE = 90

    type: Mapped[str] = mapped_column(String(30))
    objet_uuid: Mapped[str] = mapped_column(String(36), index=True)
    priorite: Mapped[int] = mapped_column(Integer, default=PRIORITE_GENERATION)
    etat: Mapped[str] = mapped_column(String(20), default="en_attente")
    tentatives: Mapped[int] = mapped_column(Integer, default=0)
    # Délai lu dans l'en-tête `retry-after` d'une erreur 429 (EX-ARC-13) : une
    # attente en puissances de deux l'ignorerait par construction.
    reprendre_apres: Mapped[datetime | None] = mapped_column(HorodatageUTC)
    derniere_erreur: Mapped[str | None] = mapped_column(Text)
    creee_le: Mapped[datetime] = mapped_column(HorodatageUTC,
                                               default=maintenant)
    demarree_le: Mapped[datetime | None] = mapped_column(HorodatageUTC)
    terminee_le: Mapped[datetime | None] = mapped_column(HorodatageUTC)

    __table_args__ = (
        CheckConstraint(
            "type IN ('generation_chronique','conversion_image',"
            "'copie_stockage_objet')", name="ck_tache_type"),
        CheckConstraint(
            "etat IN ('en_attente','en_cours','terminee','echouee')",
            name="ck_tache_etat"),
        # EX-IA-43 — une chronique ne peut avoir qu'une tâche de génération non
        # terminée à la fois. Les compteurs étant dérivés, deux demandes
        # simultanées liraient la même valeur et lanceraient deux générations ;
        # un double appui sur « Réécrivez-moi ça », sur une 4G lente, est le
        # cas nominal. L'index partiel rend la course impossible plutôt que de
        # la confier à une vérification suivie d'une écriture.
        Index("ux_tache_generation_en_cours", "objet_uuid", unique=True,
              sqlite_where=text(
                  "type = 'generation_chronique' "
                  "AND etat IN ('en_attente', 'en_cours')")),
        # Ordre de service du worker : priorité, puis ancienneté.
        Index("ix_tache_service", "etat", "priorite", "creee_le"),
    )


# --------------------------------------------------------------------------- #
# Journal, phase, sauvegardes
# --------------------------------------------------------------------------- #

class Journal(_CleUUID, Base):
    """Trace des actions sensibles (EX-GEN-05).

    C'est aussi la **source des consommations** : les quotas sont des
    allocations, et ce qui a été consommé se recompte ici (EX-GEN-07). D'où
    l'index sur le couple objet / action, interrogé à chaque affichage de
    portrait.
    """

    __tablename__ = "journal"

    # Deux entrées distinctes portent le décompte de génération (EX-IA-21) :
    # une tentative est un appel émis, une génération un portrait valide reçu.
    # Un échec technique ne débite donc jamais le quota de l'invité.
    CHRONIQUE_TENTEE = "chronique_tentee"
    CHRONIQUE_GENEREE = "chronique_generee"
    # Source du budget de photo (EX-GEN-07). `PHOTO_ECHOUEE` est journalisée
    # par la conversion et vient EN SOUSTRACTION : un échec de notre côté ne
    # se décompte pas à l'invité (EX-PHO-33).
    PHOTO_DEPOSEE = "photo_deposee"
    PHOTO_ECHOUEE = "photo_echouee"
    PHOTO_RETIREE = "photo_retiree"
    # EX-SAU-01 — la photo est copiée hors du volume. Journalisée pour que la
    # question « laquelle n'est pas sauvegardée ? » se DÉRIVE au lieu d'exiger
    # d'interroger deux fournisseurs, ce qui est lent et faux dès qu'un des
    # deux ne répond pas.
    PHOTO_COPIEE = "photo_copiee"
    PHOTO_COPIE_ECHOUEE = "photo_copie_echouee"
    # EX-ADM-10 — l'administrateur rend un crédit, ou les rend tous.
    # **Rendre UN crédit est une quantité ; tout rendre est une DATE.** Écrire
    # quatre lignes de compensation marcherait — mais un double appui sur un
    # réseau lent en écrirait huit, et le budget passerait au-dessus du
    # plafond. Une borne est idempotente : deux appuis posent deux bornes, la
    # dernière gagne, le résultat est le même. Le budget devient « ce qui s'est
    # passé depuis la dernière remise ».
    PHOTO_CREDITEE = "photo_creditee"
    PHOTO_CREDITS_REMIS = "photo_credits_remis"
    CHRONIQUE_CREDITEE = "chronique_creditee"
    CHRONIQUE_CREDITS_REMIS = "chronique_credits_remis"
    # Toute écriture de l'administrateur sur un objet, avec le détail de ce
    # qui a changé : c'est ce qu'on relira en octobre pour savoir si un
    # portrait a été retouché à la main.
    CHRONIQUE_MODIFIEE = "chronique_modifiee"
    # Distincte de la précédente, et ce n'est pas un détail : c'est la
    # comparaison de SA date avec celle de la dernière génération qui dit si
    # le portrait reflète encore les réponses. Noyée dans `CHRONIQUE_MODIFIEE`,
    # corriger une virgule du portrait lèverait le drapeau.
    REPONSES_MODIFIEES = "reponses_modifiees"

    # EX-CDT-14 — les trois budgets du Gardien. Ancrés sur la TABLE et non sur
    # la personne : le rôle peut changer de main en cours de soirée, et le
    # budget appartient à la table, pas à celui qui la garde à cet instant.
    ENLUMINURE_DEPOSEE = "enluminure_deposee"
    ENLUMINURE_RETIREE = "enluminure_retiree"
    ENLUMINURE_ECHOUEE = "enluminure_echouee"
    ENLUMINURE_CREDITEE = "enluminure_creditee"
    # Retirer une enluminure dont la CONVERSION a échoué est gratuit, comme
    # pour une photo personnelle (EX-PHO-33) : c'est notre défaut. Une action
    # distincte plutôt qu'un détail à relire — le budget se compte alors sans
    # jamais ouvrir un JSON. Cinq suppressions, c'est peu : en brûler deux à
    # nettoyer nos propres échecs serait payer notre panne.
    ENLUMINURE_ECARTEE = "enluminure_ecartee"
    # La charge change de main : c'est la seule écriture qui touche au rôle
    # ailleurs qu'à l'import, et on voudra savoir en octobre qui l'a déplacée.
    GARDIEN_DESIGNE = "gardien_designe"
    CHRONIQUE_SUPPRIMEE = "chronique_supprimee"
    CHRONIQUE_RESTAUREE = "chronique_restauree"
    # Actions écrites en chaîne libre depuis les étapes 1 et 2, promues en
    # constantes sans changer leur valeur : l'onglet Historique a besoin d'une
    # table `action -> libellé`, et une table dont les clés sont des chaînes
    # recopiées à la main diverge du jour où l'on renomme une action.
    REPONSES_REPRISES = "reponses_reprises"
    PERSONNE_CREEE = "personne_creee"
    NOM_COMPLETE = "nom_complete"
    IMPORT_INVITES = "import_invites"
    REGION_MODIFIEE = "region_modifiee"
    TABLE_RENOMMEE = "table_renommee"

    horodatage: Mapped[datetime] = mapped_column(HorodatageUTC,
                                                 default=maintenant)
    acteur_personne_uuid: Mapped[str | None] = mapped_column(String(36))
    # EX-ADM-11 — mode « incarner » : l'administrateur agit au nom d'un invité.
    agit_pour_le_compte_de: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    objet_type: Mapped[str | None] = mapped_column(String(30))
    objet_uuid: Mapped[str | None] = mapped_column(String(36))
    details_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_journal_objet_action", "objet_uuid", "action"),
        Index("ix_journal_horodatage", "horodatage"),
    )


class EtatSoiree(Base):
    """Phase de la soirée. Table à une seule ligne.

    **Écart assumé à EX-GEN-02** : la clé primaire est l'entier 1 et non un
    UUID. Une clé UUID sur une table singleton n'apporte rien et retire la
    seule garantie qui compte ici — qu'il n'y ait jamais deux phases
    simultanées. La contrainte le dit explicitement.
    """

    __tablename__ = "etat_soiree"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    phase: Mapped[str] = mapped_column(String(20), default="preparation")
    fermeture_prevue_le: Mapped[datetime | None] = mapped_column(HorodatageUTC)
    modifie_le: Mapped[datetime] = mapped_column(HorodatageUTC,
                                                 default=maintenant,
                                                 onupdate=maintenant)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_etat_soiree_unique"),
        CheckConstraint(
            "phase IN ('preparation','ouvert','dernier_appel',"
            "'lecture_seule','ferme')", name="ck_etat_soiree_phase"),
    )


class Sauvegarde(_CleUUID, Base):
    """Journal des copies : instantanés de la base, médias, copie du Pi.

    L'horodatage du dernier instantané réussi figure au tableau de bord
    (EX-SAU-15, EX-ADM-18) — c'est ce qui rend la sauvegarde vérifiable
    plutôt que supposée.
    """

    __tablename__ = "sauvegarde"

    horodatage: Mapped[datetime] = mapped_column(HorodatageUTC,
                                                 default=maintenant,
                                                 index=True)
    cible: Mapped[str] = mapped_column(String(40))
    nb_objets: Mapped[int] = mapped_column(Integer, default=0)
    octets: Mapped[int] = mapped_column(Integer, default=0)
    succes: Mapped[bool] = mapped_column(Boolean, default=True)
    erreur: Mapped[str | None] = mapped_column(Text)
