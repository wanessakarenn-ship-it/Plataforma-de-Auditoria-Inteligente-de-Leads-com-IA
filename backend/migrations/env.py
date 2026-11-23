from logging.config import fileConfig

from alembic import context

from backend.app.config import CLOUD_SQL_MIGRATOR_IDENTITY, get_settings, require_cloud_sql_identity
from backend.app.db import build_engine, close_cloud_sql_connector
from backend.app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
require_cloud_sql_identity(settings, CLOUD_SQL_MIGRATOR_IDENTITY)
migration_url = (
    "postgresql+psycopg://"
    if settings.cloud_sql_iam_auth
    else settings.database_url
)
config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
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
