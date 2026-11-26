from collections.abc import Generator
from threading import Lock

from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import CloudSqlExecutionIdentity, get_settings

_connector: Connector | None = None
_connector_lock = Lock()


def build_engine(
    database_url: str | None = None,
    *,
    expected_identity: CloudSqlExecutionIdentity | None = None,
):
    settings = get_settings()
    options = {"pool_pre_ping": True}

    if settings.cloud_sql_iam_auth:
        identity = settings.cloud_sql_execution_identity
        if expected_identity is not None and identity != expected_identity:
            raise RuntimeError(
                f"Cloud SQL identity {expected_identity!r} is required for this operation."
            )
        options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
        connector = _get_cloud_sql_connector()

        def connect_with_iam():
            return connector.connect(
                settings.cloud_sql_connection_name,
                "psycopg",
                user=settings.selected_cloud_sql_db_user,
                db=settings.cloud_sql_db_name.strip(),
                ip_type=IPTypes.PUBLIC,
            )

        return create_engine(
            "postgresql+psycopg://",
            creator=connect_with_iam,
            **options,
        )

    url = database_url or settings.database_url
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
    return create_engine(url, **options)


def _get_cloud_sql_connector() -> Connector:
    global _connector
    with _connector_lock:
        if _connector is None:
            _connector = Connector(enable_iam_auth=True, refresh_strategy="lazy")
        return _connector


def close_cloud_sql_connector() -> None:
    global _connector
    with _connector_lock:
        connector = _connector
        _connector = None
    if connector is not None:
        connector.close()


def close_database_resources() -> None:
    engine.dispose()
    close_cloud_sql_connector()


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
