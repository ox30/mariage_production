"""Code stable des tables, et les régions rendues modifiables.

**`table_groupe.code`.** L'import rapprochait les tables par leur `nom`.
Renommer la table « 3 » en « Fondcombe » puis réimporter le fichier — qui porte
toujours `Table = 3` — créait une SECONDE table « 3 » et y déplaçait ses dix
invités, en silence. Le code est ce que porte le fichier, le nom est ce que les
invités lisent. Même principe que `chronique.lieu` : un code stable, un libellé
qui n'est qu'un paramètre d'affichage (EX-IA-42).

Les tables existantes reçoivent leur nom actuel comme code — c'est exactement
ce que l'import y avait écrit.

**`region`.** EX-ADM-22 veut que libellés, locutions et pendants d'ombre se
modifient depuis l'administration, « y compris après ouverture de la soirée ».
`questions.yaml` est chargé au démarrage : une modification n'y prendrait effet
qu'au redéploiement suivant, ce qu'EX-SAU-09 interdit le 5 septembre. Le
fichier garde les valeurs par défaut, semées ici au premier démarrage ; la
table fait autorité ensuite.

Aucune chronique n'est orpheline : `chronique.lieu` porte le code, jamais le
libellé (EX-IA-28).

Révision : 0002_tables_regions
Précédente : 0001_socle
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_tables_regions"
down_revision: Union[str, None] = "0001_socle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite ne sait pas ajouter une colonne NOT NULL sans défaut à une table
    # peuplée : on l'ajoute nullable, on la remplit, puis on la contraint par
    # l'index unique. `batch_alter_table` recopie la table, ce qui est le seul
    # moyen d'y poser une contrainte après coup sous SQLite.
    op.add_column("table_groupe", sa.Column("code", sa.String(length=40),
                                            nullable=True))
    # Les tables existantes portent « 1 »… « 10 » comme nom : c'est ce que
    # l'import y a écrit, et c'est donc exactement leur code.
    op.execute("UPDATE table_groupe SET code = nom WHERE code IS NULL")
    with op.batch_alter_table("table_groupe") as lot:
        lot.alter_column("code", existing_type=sa.String(length=40),
                         nullable=False)
        lot.create_index("ux_table_groupe_code", ["code"], unique=True)

    op.create_table(
        "region",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("libelle", sa.String(length=80), nullable=False),
        sa.Column("locution", sa.String(length=120), nullable=False),
        sa.Column("ombre", sa.String(length=160), nullable=False),
        sa.Column("ordre", sa.Integer(), nullable=False),
        sa.Column("modifie_le", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    # Pas de semis ici : les valeurs par défaut vivent dans le `questions.yaml`
    # du dossier de projet, que la migration ne doit pas connaître. Le semis se
    # fait au démarrage, où le fichier est déjà chargé et validé.


def downgrade() -> None:
    op.drop_table("region")
    with op.batch_alter_table("table_groupe") as lot:
        lot.drop_index("ux_table_groupe_code")
        lot.drop_column("code")
