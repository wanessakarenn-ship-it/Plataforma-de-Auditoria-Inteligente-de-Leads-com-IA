from logging.config import fileConfig

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

bootstrap_stamp = bool(config.attributes.get("bootstrap_stamp"))
bootstrap_connection = config.attributes.get("connection")
if bootstrap_stamp:
    if bootstrap_connection is None:
        raise RuntimeError("Bootstrap stamping requires its validated connection.")
    target_metadata = None
else:
    from backend.app.models import Base

    target_metadata = Base.metadata


def _legacy_settings():
    from backend.app.config import (
        CLOUD_SQL_MIGRATOR_IDENTITY,
        get_settings,
        require_cloud_sql_identity,
    )

    settings = get_settings()
    require_cloud_sql_identity(settings, CLOUD_SQL_MIGRATOR_IDENTITY)
    migration_url = (
        "postgresql+psycopg://" if settings.cloud_sql_iam_auth else settings.database_url
    )
    config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))
    return settings


def run_migrations_offline() -> None:
    _legacy_settings()
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if bootstrap_stamp:
        context.configure(
            connection=bootstrap_connection,
            target_metadata=None,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    from backend.app.config import CLOUD_SQL_MIGRATOR_IDENTITY
    from backend.app.db import build_engine, close_cloud_sql_connector

    settings = _legacy_settings()
    connectable = build_engine(
        settings.database_url,
        expected_identity=(
            CLOUD_SQL_MIGRATOR_IDENTITY if settings.cloud_sql_iam_auth else None
        ),
    )
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()
        close_cloud_sql_connector()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
