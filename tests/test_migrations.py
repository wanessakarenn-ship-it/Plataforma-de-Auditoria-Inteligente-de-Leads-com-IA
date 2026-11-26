from pathlib import Path
import os
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

import backend.migrations.bootstrap as bootstrap
from backend.migrations.bootstrap_schema import (
    BASELINE_METADATA,
    BASELINE_REVISION,
    expected_table_names,
    validate_schema,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG_PATH = REPOSITORY_ROOT / "alembic.ini"


@pytest.fixture(autouse=True)
def isolated_bootstrap_directory(tmp_path, monkeypatch):
    if os.name != "nt":
        os.chmod(tmp_path, 0o700)
    monkeypatch.setenv(
        bootstrap.DISPOSABLE_DIR_ENV,
        str(tmp_path.resolve()),
    )


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _set_safe_legacy_environment(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CLOUD_SQL_IAM_AUTH", "false")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("VERTEX_AI_ENABLED", "false")
    monkeypatch.setenv("VERTEX_AI_APPROVED", "false")
    from backend.app.config import get_settings

    get_settings.cache_clear()


def _legacy_upgrade(database_url: str, revision: str) -> None:
    from backend.app.config import get_settings

    get_settings.cache_clear()
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, revision)


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def test_frozen_bootstrap_is_independent_of_current_orm_metadata(
    tmp_path, monkeypatch
):
    from backend.app.models import Base
    from backend.app import db

    orm_only_table = Table(
        "orm_only_after_0010",
        Base.metadata,
        Column("id", Integer, primary_key=True),
    )
    database_url = _sqlite_url(tmp_path / "baseline.sqlite")
    monkeypatch.setenv("CLOUD_SQL_IAM_AUTH", "true")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://must-not-connect:must-not-connect@invalid/remote",
    )

    def unexpected_connector(*_args, **_kwargs):
        raise AssertionError("The explicit bootstrap must not use Cloud SQL Connector.")

    monkeypatch.setattr(db, "Connector", unexpected_connector)

    try:
        result = bootstrap.bootstrap_database(
            database_url,
            target_environment="disposable-test",
            confirm_disposable=True,
        )
    finally:
        Base.metadata.remove(orm_only_table)

    assert result.revision == BASELINE_REVISION
    assert result.dialect == "sqlite"
    assert result.table_count == len(expected_table_names())
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == (
                set(expected_table_names()) | {"alembic_version"}
            )
            assert _revision(engine) == BASELINE_REVISION
            validate_schema(connection, allow_alembic_version=True)
    finally:
        engine.dispose()


def test_bootstrap_requires_explicit_disposable_confirmation():
    with pytest.raises(bootstrap.BootstrapError, match="disposable-test"):
        bootstrap.bootstrap_database(
            "not-a-url",
            target_environment="development",
            confirm_disposable=False,
        )

    with pytest.raises(bootstrap.BootstrapError, match="disposable-test"):
        bootstrap.bootstrap_database(
            "not-a-url",
            target_environment="disposable-test",
            confirm_disposable=False,
        )


def test_bootstrap_rejects_non_file_unsupported_and_postgresql_urls(monkeypatch):
    def unexpected_engine(*_args, **_kwargs):
        raise AssertionError("PostgreSQL must be rejected before create_engine.")

    monkeypatch.setattr(bootstrap, "create_engine", unexpected_engine)
    with pytest.raises(bootstrap.BootstrapError, match="file path"):
        bootstrap.bootstrap_database(
            "sqlite:///:memory:",
            target_environment="disposable-test",
            confirm_disposable=True,
        )

    with pytest.raises(bootstrap.BootstrapError, match="PostgreSQL"):
        bootstrap.bootstrap_database(
            "postgresql+psycopg://user:password@localhost/test",
            target_environment="disposable-test",
            confirm_disposable=True,
        )

    with pytest.raises(bootstrap.BootstrapError, match="PostgreSQL"):
        bootstrap.bootstrap_database(
            "postgresql+psycopg://user:password@/"
            "test-project:test-region:test-instance",
            target_environment="disposable-test",
            confirm_disposable=True,
        )


def test_bootstrap_rejects_relative_absolute_and_persistent_paths(tmp_path):
    with pytest.raises(bootstrap.BootstrapError, match="Relative"):
        bootstrap.bootstrap_database(
            "sqlite:///relative/bootstrap.sqlite",
            target_environment="disposable-test",
            confirm_disposable=True,
        )

    outside = tmp_path.parent / "outside.sqlite"
    with pytest.raises(bootstrap.BootstrapError, match="outside"):
        bootstrap.bootstrap_database(
            _sqlite_url(outside),
            target_environment="disposable-test",
            confirm_disposable=True,
        )

    persistent = tmp_path / "bc_lead_intelligence.db"
    with pytest.raises(bootstrap.BootstrapError, match="persistent"):
        bootstrap.bootstrap_database(
            _sqlite_url(persistent),
            target_environment="disposable-test",
            confirm_disposable=True,
        )


def test_bootstrap_rejects_symlinks(tmp_path):
    outside = tmp_path.parent / "outside-target.sqlite"
    symlink = tmp_path / "linked-target.sqlite"
    if not hasattr(os, "symlink"):
        pytest.skip("Symlinks are unavailable.")
    try:
        outside.touch()
        symlink.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable.")

    with pytest.raises(bootstrap.BootstrapError, match="symlink|outside"):
        bootstrap.bootstrap_database(
            _sqlite_url(symlink),
            target_environment="disposable-test",
            confirm_disposable=True,
        )


def test_bootstrap_rejects_symlink_directory_root(tmp_path):
    outside = tmp_path.parent / "outside-bootstrap-root"
    outside.mkdir(exist_ok=True)
    linked_root = tmp_path / "linked-root"
    if not hasattr(os, "symlink"):
        pytest.skip("Symlinks are unavailable.")
    try:
        linked_root.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable.")

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(bootstrap.DISPOSABLE_DIR_ENV, str(linked_root))
        with pytest.raises(bootstrap.BootstrapError, match="symlink|reparse"):
            bootstrap.bootstrap_database(
                _sqlite_url(linked_root / "target.sqlite"),
                target_environment="disposable-test",
                confirm_disposable=True,
            )


def test_bootstrap_rejects_symlink_intermediate_directory(tmp_path):
    outside = tmp_path.parent / "outside-intermediate"
    outside.mkdir(exist_ok=True)
    linked_directory = tmp_path / "linked-intermediate"
    if not hasattr(os, "symlink"):
        pytest.skip("Symlinks are unavailable.")
    try:
        linked_directory.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable.")

    with pytest.raises(bootstrap.BootstrapError, match="symlink|reparse"):
        bootstrap.bootstrap_database(
            _sqlite_url(linked_directory / "target.sqlite"),
            target_environment="disposable-test",
            confirm_disposable=True,
        )


def test_bootstrap_rejects_directory_controlled_by_another_user(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX ownership semantics are unavailable.")
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(bootstrap.BootstrapError, match="owned by another"):
        bootstrap.bootstrap_database(
            _sqlite_url(tmp_path / "ownership.sqlite"),
            target_environment="disposable-test",
            confirm_disposable=True,
        )


def test_bootstrap_rejects_world_writable_directory(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX mode semantics are unavailable.")
    tmp_path.chmod(0o777)
    with pytest.raises(bootstrap.BootstrapError, match="writable by other users"):
        bootstrap.bootstrap_database(
            _sqlite_url(tmp_path / "world-writable.sqlite"),
            target_environment="disposable-test",
            confirm_disposable=True,
        )


def test_bootstrap_rejects_a_concurrently_locked_target(tmp_path):
    target = (tmp_path / "concurrent.sqlite").resolve()
    with bootstrap._exclusive_target_lock(target):
        with pytest.raises(bootstrap.BootstrapError, match="already being bootstrapped"):
            bootstrap.bootstrap_database(
                _sqlite_url(target),
                target_environment="disposable-test",
                confirm_disposable=True,
            )


def test_bootstrap_rejects_file_replacement_after_preflight(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows locks the SQLite file while open; replacement is tested on POSIX.")
    target = (tmp_path / "replacement.sqlite").resolve()
    replacement = (tmp_path / "replacement-new.sqlite").resolve()
    replacement_engine = create_engine(_sqlite_url(replacement))
    with replacement_engine.begin() as connection:
        connection.execute(text("CREATE TABLE replacement_marker (id INTEGER)"))
    replacement_engine.dispose()
    original_inspect_target = bootstrap.inspect_target

    def replace_then_inspect(connection):
        os.replace(replacement, target)
        return original_inspect_target(connection)

    with monkeypatch.context() as patch:
        patch.setattr(bootstrap, "inspect_target", replace_then_inspect)
        with pytest.raises(bootstrap.BootstrapError, match="removed or replaced"):
            bootstrap.bootstrap_database(
                _sqlite_url(target),
                target_environment="disposable-test",
                confirm_disposable=True,
            )

    assert not target.is_symlink()


def test_bootstrap_rejects_file_replacement_after_lock(tmp_path, monkeypatch):
    target = (tmp_path / "swap-after-lock.sqlite").resolve()
    replacement = (tmp_path / "swap-after-lock-new.sqlite").resolve()
    replacement_engine = create_engine(_sqlite_url(replacement))
    with replacement_engine.begin() as connection:
        connection.execute(text("CREATE TABLE replacement_marker (id INTEGER)"))
    replacement_engine.dispose()
    original_lock = bootstrap._exclusive_target_lock

    @contextmanager
    def replace_inside_lock(selected_target):
        with original_lock(selected_target):
            os.replace(replacement, selected_target)
            yield

    with monkeypatch.context() as patch:
        patch.setattr(bootstrap, "_exclusive_target_lock", replace_inside_lock)
        with pytest.raises(bootstrap.BootstrapError, match="removed or replaced"):
            bootstrap.bootstrap_database(
                _sqlite_url(target),
                target_environment="disposable-test",
                confirm_disposable=True,
            )


def test_bootstrap_rejects_file_removal_during_execution(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows keeps SQLite files locked, so unlink-at-runtime is unavailable.")
    target = (tmp_path / "removed.sqlite").resolve()
    original_inspect_target = bootstrap.inspect_target

    def remove_then_inspect(connection):
        if target.exists():
            target.unlink()
        return original_inspect_target(connection)

    with monkeypatch.context() as patch:
        patch.setattr(bootstrap, "inspect_target", remove_then_inspect)
        with pytest.raises(bootstrap.BootstrapError, match="removed or replaced"):
            bootstrap.bootstrap_database(
                _sqlite_url(target),
                target_environment="disposable-test",
                confirm_disposable=True,
            )


@pytest.mark.parametrize(
    ("object_sql", "setup_sql", "expected_detail"),
    [
        (
            "CREATE TABLE existing_data (id INTEGER PRIMARY KEY, label VARCHAR(40) UNIQUE)",
            "INSERT INTO existing_data (id, label) VALUES (1, 'synthetic')",
            "has_data': True",
        ),
        (
            "CREATE TABLE partial_schema (id INTEGER PRIMARY KEY)",
            None,
            "has_data': False",
        ),
        (
            "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)",
            "INSERT INTO alembic_version (version_num) VALUES ('0005_tenant_access_and_admin_actions')",
            "alembic_versions=('0005_tenant_access_and_admin_actions',)",
        ),
    ],
)
def test_bootstrap_refuses_existing_tables_and_preserves_them(
    tmp_path, object_sql, setup_sql, expected_detail
):
    database_url = _sqlite_url(tmp_path / "existing.sqlite")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text(object_sql))
        if "existing_data" in object_sql:
            connection.execute(
                text("CREATE INDEX ix_existing_data_label ON existing_data (label)")
            )
        if setup_sql:
            connection.execute(text(setup_sql))

    with pytest.raises(bootstrap.BootstrapError) as captured:
        bootstrap.bootstrap_database(
            database_url,
            target_environment="disposable-test",
            confirm_disposable=True,
        )

    assert expected_detail in str(captured.value)
    if "existing_data" in str(captured.value):
        assert "has_data': True" in str(captured.value)
        assert "ix_existing_data_label" in str(captured.value)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        if "existing_data" in tables:
            assert connection.execute(
                text("SELECT label FROM existing_data WHERE id = 1")
            ).scalar_one() == "synthetic"
        if "alembic_version" in tables:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "0005_tenant_access_and_admin_actions"
        assert not expected_table_names().intersection(tables)
    engine.dispose()


def test_bootstrap_refuses_existing_views(tmp_path):
    database_url = _sqlite_url(tmp_path / "view.sqlite")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIEW existing_view AS SELECT 1 AS value"))

    with pytest.raises(bootstrap.BootstrapError, match="views="):
        bootstrap.bootstrap_database(
            database_url,
            target_environment="disposable-test",
            confirm_disposable=True,
        )

    engine.dispose()


def test_schema_validation_rejects_missing_index(tmp_path):
    engine = create_engine(_sqlite_url(tmp_path / "invalid-baseline.sqlite"))
    with engine.begin() as connection:
        BASELINE_METADATA.create_all(connection, checkfirst=False)
        connection.execute(text("DROP INDEX ix_leads_email_normalized"))
        with pytest.raises(ValueError, match="indexes differ for leads"):
            validate_schema(connection)
    engine.dispose()


@pytest.mark.parametrize(
    ("table_name", "mutation", "expected_fragment"),
    [
        (
            "leads",
            "DROP TABLE leads",
            "missing table leads",
        ),
        (
            "leads",
            "DROP INDEX ix_leads_phone_normalized",
            "indexes differ for leads",
        ),
        (
            "ai_agents",
            "DROP INDEX uq_ai_agents_tenant_id",
            "indexes differ for ai_agents",
        ),
        (
            "ai_agent_versions",
            "DROP INDEX ix_ai_agent_versions_tenant_agent",
            "indexes differ for ai_agent_versions",
        ),
    ],
)
def test_schema_validation_detects_missing_tables_and_indexes(
    tmp_path, table_name, mutation, expected_fragment
):
    engine = create_engine(_sqlite_url(tmp_path / f"divergence-{table_name}.sqlite"))
    with engine.begin() as connection:
        BASELINE_METADATA.create_all(connection, checkfirst=False)
        connection.execute(text(mutation))
        with pytest.raises(ValueError, match=expected_fragment):
            validate_schema(connection)
    engine.dispose()


def test_schema_validation_detects_column_pk_unique_fk_default_and_check_divergence(
    tmp_path,
):
    engine = create_engine(_sqlite_url(tmp_path / "divergence-details.sqlite"))
    with engine.begin() as connection:
        BASELINE_METADATA.create_all(connection, checkfirst=False)

        connection.exec_driver_sql(
            "CREATE TABLE leads_wrong "
            "(id INTEGER, tenant_id TEXT, external_id TEXT, "
            "classification TEXT NOT NULL DEFAULT 'wrong', "
            "PRIMARY KEY (id, tenant_id), "
            "CONSTRAINT ck_leads_wrong CHECK (classification != 'blocked'))"
        )
        connection.exec_driver_sql("DROP TABLE leads")
        connection.exec_driver_sql(
            "ALTER TABLE leads_wrong RENAME TO leads"
        )

        with pytest.raises(ValueError) as captured:
            validate_schema(connection)

    message = str(captured.value)
    assert "columns/types/nullability/defaults differ for leads" in message
    assert "primary key differs for leads" in message
    assert "foreign keys/referential actions differ for leads" in message
    assert "unique constraints differ for leads" in message
    assert "indexes differ for leads" in message
    assert "check constraints differ for leads" in message
    engine.dispose()


def test_schema_validation_detects_fk_on_delete_divergence(tmp_path):
    engine = create_engine(_sqlite_url(tmp_path / "divergence-on-delete.sqlite"))
    with engine.begin() as connection:
        BASELINE_METADATA.create_all(connection, checkfirst=False)
        connection.exec_driver_sql("DROP TABLE ai_agent_versions")
        connection.exec_driver_sql(
            "CREATE TABLE ai_agent_versions "
            "(id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, tenant_id TEXT NOT NULL, "
            "version_number INTEGER NOT NULL, snapshot_json TEXT NOT NULL, "
            "created_by_uid TEXT NOT NULL, created_at TEXT NOT NULL, "
            "FOREIGN KEY (agent_id) REFERENCES ai_agents(id) ON DELETE SET NULL)"
        )
        with pytest.raises(
            ValueError,
            match="foreign keys/referential actions differ for ai_agent_versions",
        ):
            validate_schema(connection)
    engine.dispose()


def test_failed_validation_never_stamps_or_recovers_partial_schema(
    tmp_path, monkeypatch
):
    database_url = _sqlite_url(tmp_path / "partial.sqlite")

    def reject_schema(_connection, *, allow_alembic_version=False):
        raise ValueError("synthetic schema mismatch")

    with monkeypatch.context() as patch:
        patch.setattr(bootstrap, "validate_schema", reject_schema)
        with pytest.raises(bootstrap.BootstrapError, match="Pre-stamp bootstrap failure"):
            bootstrap.bootstrap_database(
                database_url,
                target_environment="disposable-test",
                confirm_disposable=True,
            )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        names = set(inspect(connection).get_table_names())
        assert "alembic_version" not in names
        partial = bool(names.intersection(expected_table_names()))
    assert partial
    if partial:
        with pytest.raises(bootstrap.BootstrapError, match="structurally empty"):
            bootstrap.bootstrap_database(
                database_url,
                target_environment="disposable-test",
                confirm_disposable=True,
            )
    engine.dispose()


def test_post_stamp_mismatch_fails_and_does_not_leave_a_false_revision(
    tmp_path, monkeypatch
):
    database_url = _sqlite_url(tmp_path / "stamp-mismatch.sqlite")
    actual_stamp = command.stamp

    def stamp_then_corrupt_schema(config, revision):
        actual_stamp(config, revision)
        config.attributes["connection"].exec_driver_sql(
            "DROP INDEX ix_leads_email_normalized"
        )

    with monkeypatch.context() as patch:
        patch.setattr(command, "stamp", stamp_then_corrupt_schema)
        with pytest.raises(bootstrap.BootstrapError, match="Post-stamp bootstrap failure"):
            bootstrap.bootstrap_database(
                database_url,
                target_environment="disposable-test",
                confirm_disposable=True,
            )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        version_rows = (
            connection.execute(text("SELECT version_num FROM alembic_version"))
            .scalars()
            .all()
            if "alembic_version" in inspector.get_table_names()
            else []
        )
        index_names = {
            index["name"] for index in inspector.get_indexes("leads")
        } if "leads" in inspector.get_table_names() else set()
        assert version_rows != [BASELINE_REVISION] or "ix_leads_email_normalized" in index_names
    with pytest.raises(bootstrap.BootstrapError, match="structurally empty"):
        bootstrap.bootstrap_database(
            database_url,
            target_environment="disposable-test",
            confirm_disposable=True,
        )
    engine.dispose()


@pytest.mark.parametrize(
    "starting_revision",
    [
        "0001_initial_schema",
        "0005_tenant_access_and_admin_actions",
        "0007_conversation_scoped_message_tombstones",
        "0009_knowledge_base",
    ],
)
def test_legacy_upgrade_preserves_existing_rows(
    tmp_path, monkeypatch, starting_revision
):
    database_url = _sqlite_url(tmp_path / f"legacy-{starting_revision}.sqlite")
    _set_safe_legacy_environment(monkeypatch, database_url)

    from backend.app import db

    def unexpected_connector(*_args, **_kwargs):
        raise AssertionError("SQLite legacy tests must not instantiate Cloud SQL.")

    monkeypatch.setattr(db, "Connector", unexpected_connector)
    _legacy_upgrade(database_url, starting_revision)

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO loss_reasons "
                "(id, name, active, created_at, updated_at) "
                "VALUES ('synthetic-id', 'synthetic-reason', 1, "
                "'2026-01-01', '2026-01-01')"
            )
        )
    engine.dispose()

    try:
        _legacy_upgrade(database_url, "head")
    finally:
        from backend.app.config import get_settings

        get_settings.cache_clear()

    engine = create_engine(database_url)
    try:
        assert _revision(engine) == BASELINE_REVISION
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT name FROM loss_reasons WHERE id = 'synthetic-id'")
            ).scalar_one() == "synthetic-reason"
    finally:
        engine.dispose()


def test_legacy_chain_head_matches_the_frozen_baseline(tmp_path, monkeypatch):
        database_url = _sqlite_url(tmp_path / "legacy-head.sqlite")
        _set_safe_legacy_environment(monkeypatch, database_url)
        _legacy_upgrade(database_url, "head")

        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                validate_schema(connection, allow_alembic_version=True)
        finally:
            engine.dispose()
            from backend.app.config import get_settings

            get_settings.cache_clear()


def test_postgresql_baseline_ddl_compiles_for_future_disposable_validation():
    compiled = {
        table_name: str(
            CreateTable(table).compile(dialect=postgresql.dialect())
        ).upper()
        for table_name, table in BASELINE_METADATA.tables.items()
    }

    assert "JSON" in compiled["karen_simulation_events"]
    assert "TIMESTAMP WITH TIME ZONE" in compiled["karen_simulations"]
    assert "ON DELETE RESTRICT" in compiled["karen_simulation_events"]
    assert "TENANT_ID, AGENT_ID" in compiled["karen_simulations"]
