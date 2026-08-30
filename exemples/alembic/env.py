"""Contexte de migration Alembic.

L'URL de la base vient de `config.py` et jamais d'`alembic.ini` : un seul
endroit sait où l'application écrit (EX-PRJ-01). Une URL en dur pourrait viser
un autre projet que celui désigné par `projet-actif.txt` — et une migration
appliquée au mauvais dossier ne se voit pas.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import config
import modeles

configuration = context.config

if configuration.config_file_name is not None:
    fileConfig(configuration.config_file_name)

configuration.set_main_option(
    "sqlalchemy.url", f"sqlite+pysqlite:///{config.projet().chemin_base}")

metadonnees_cibles = modeles.Base.metadata


def inclure_objet(objet, nom, type_, reflechi, comparaison):
    """Ignore les tables absentes du modèle plutôt que de proposer leur retrait.

    La table `participation` du banc d'essai survit dans les bases déjà
    déployées. Elle n'est plus utilisée, mais `--autogenerate` proposerait de
    la supprimer — et toute suppression est douce dans ce projet (EX-GEN-03).
    Elle se retire à la main, une fois, en connaissance de cause.
    """
    if type_ == "table" and reflechi and nom not in metadonnees_cibles.tables:
        return False
    return True


def rendre_type(type_, obj, autogen_context):
    """Rend `HorodatageUTC` comme un `DateTime` ordinaire.

    Une révision est un instantané historique : elle ne doit dépendre
    d'aucun module de l'application, sous peine de changer de sens quand le
    modèle évolue. Au niveau de la base, `HorodatageUTC` n'est qu'un
    `DATETIME` — la conscience du fuseau est un comportement Python
    (EX-GEN-04), pas une caractéristique de colonne.
    """
    if type_ == "type" and isinstance(obj, modeles.HorodatageUTC):
        autogen_context.imports.add("import sqlalchemy as sa")
        return "sa.DateTime()"
    return False


def hors_ligne() -> None:
    context.configure(
        url=configuration.get_main_option("sqlalchemy.url"),
        target_metadata=metadonnees_cibles,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=inclure_objet,
        render_item=rendre_type,
        # SQLite ne sait pas modifier une colonne en place : Alembic recrée la
        # table et recopie. Indispensable dès la première révision, sans quoi
        # toute modification ultérieure de colonne échouerait.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def en_ligne() -> None:
    moteur = engine_from_config(
        configuration.get_section(configuration.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with moteur.connect() as connexion:
        context.configure(
            connection=connexion,
            target_metadata=metadonnees_cibles,
            include_object=inclure_objet,
            render_item=rendre_type,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    hors_ligne()
else:
    en_ligne()
