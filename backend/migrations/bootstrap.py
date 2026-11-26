"""Explicit bootstrap for new, disposable databases at Alembic revision 0010."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from stat import S_ISREG
from pathlib import Path
from typing import Sequence
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from backend.migrations.bootstrap_schema import (
    BASELINE_METADATA,
    BASELINE_REVISION,
    validate_schema,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = REPOSITORY_ROOT / "alembic.ini"
SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}
SQLITE_SCHEMAS = {"main", "temp"}
DISPOSABLE_DIR_ENV = "LEAD_INTELLIGENCE_BOOTSTRAP_DIR"
PERSISTENT_SQLITE_NAME = "bc_lead_intelligence.db"
REPARSE_ATTRIBUTES = 0x400


class BootstrapError(RuntimeError):
    """Bootstrap refused or did not complete successfully."""


@dataclass(frozen=True)
class TableInventory:
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[str, ...]
    unique_constraints: tuple[str, ...]
    check_constraints: tuple[str, ...]
    indexes: tuple[str, ...]
    has_data: bool


@dataclass(frozen=True)
class TargetInventory:
    dialect: str
    schemas: tuple[str, ...]
    tables: dict[str, TableInventory]
    views: tuple[str, ...]
    sequences: tuple[str, ...]
    versions: tuple[str, ...] | None
    unexpected_schemas: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (
            self.tables
            or self.views
            or self.sequences
            or self.unexpected_schemas
        )

    def describe(self) -> str:
        table_descriptions = {
            name: {
                "columns": item.columns,
                "primary_key": item.primary_key,
                "foreign_keys": item.foreign_keys,
                "unique_constraints": item.unique_constraints,
                "check_constraints": item.check_constraints,
                "indexes": item.indexes,
                "has_data": item.has_data,
            }
            for name, item in self.tables.items()
        }
        return (
            f"dialect={self.dialect}; schemas={self.schemas}; tables={table_descriptions}; "
            f"views={self.views}; sequences={self.sequences}; "
            f"alembic_versions={self.versions}; "
            f"unexpected_schemas={self.unexpected_schemas}"
        )


@dataclass(frozen=True)
class BootstrapResult:
    dialect: str
    revision: str
    table_count: int


@dataclass(frozen=True)
class TargetIdentity:
    exists: bool
    device: int | None = None
    inode: int | None = None


def _disposable_directory() -> Path:
    configured = os.environ.get(DISPOSABLE_DIR_ENV)
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            raise BootstrapError(
                "The configured disposable bootstrap directory must be an absolute path."
            )
    else:
        root = Path(tempfile.mkdtemp(prefix="lead-intelligence-bootstrap-", suffix="-disposable"))

    _reject_symlink_components(root)
    if not root.exists() and configured:
        raise BootstrapError("The configured disposable bootstrap directory does not exist.")
    if root.is_symlink() or _has_windows_reparse_point(root):
        raise BootstrapError("The disposable bootstrap directory cannot be a symlink or reparse point.")
    root = root.absolute()
    if not root.exists():
        raise BootstrapError("The disposable bootstrap directory does not exist.")
    if not root.is_dir():
        raise BootstrapError("The disposable bootstrap directory is not a directory.")
    _require_private_directory(root)
    return root


def _has_windows_reparse_point(path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        get_file_attributes = ctypes.windll.kernel32.GetFileAttributesW
        get_file_attributes.argtypes = [ctypes.c_wchar_p]
        get_file_attributes.restype = ctypes.c_uint32
        attributes = get_file_attributes(str(path))
        if attributes == 0xFFFFFFFF:
            return False
        return bool(attributes & REPARSE_ATTRIBUTES)
    except (AttributeError, OSError):
        return True


def _require_private_directory(root: Path) -> None:
    if os.name == "nt":
        return
    try:
        mode = root.stat(follow_symlinks=False).st_mode
        uid = root.stat(follow_symlinks=False).st_uid
    except (AttributeError, OSError) as exc:
        raise BootstrapError("Could not verify the disposable directory permissions.") from exc
    if uid != os.geteuid():
        raise BootstrapError("The disposable bootstrap directory is owned by another process or user.")
    if mode & 0o022:
        raise BootstrapError("The disposable bootstrap directory is writable by other users.")


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(str(path)))
    components = list(reversed(absolute.parents)) + [absolute]
    for component in components:
        if component.is_symlink() or _has_windows_reparse_point(component):
            raise BootstrapError(
                f"Bootstrap target contains a symlink or reparse-point component: {component}"
            )
        if component.exists():
            try:
                if not component.is_dir() and component != absolute:
                    raise BootstrapError(
                        f"Bootstrap target crosses a non-directory component: {component}"
                    )
            except OSError as exc:
                raise BootstrapError("Could not inspect a bootstrap path component.") from exc


def _capture_target_identity(target: Path) -> TargetIdentity:
    _reject_symlink_components(target)
    if not target.exists():
        return TargetIdentity(exists=False)
    try:
        status = target.lstat()
    except OSError as exc:
        raise BootstrapError("Could not verify the physical SQLite target.") from exc
    if target.is_symlink() or _has_windows_reparse_point(target):
        raise BootstrapError("The SQLite target is a symlink or reparse point.")
    if not S_ISREG(status.st_mode):
        raise BootstrapError("The SQLite target is not a regular file.")
    inode = getattr(status, "st_ino", None)
    if os.name == "nt" and (not inode or inode == 0):
        raise BootstrapError(
            "This Windows runtime cannot provide a physical file identity; "
            "bootstrap is blocked to prevent SQLite target substitution."
        )
    return TargetIdentity(
        exists=True,
        device=getattr(status, "st_dev", None),
        inode=inode,
    )


def _verify_target_identity(target: Path, identity: TargetIdentity) -> None:
    current = _capture_target_identity(target)
    if current != identity:
        raise BootstrapError(
            "The SQLite target was removed or replaced during the bootstrap operation."
        )


def _validate_database_url(database_url: str) -> tuple[object, Path]:
    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError) as exc:
        raise BootstrapError("A valid explicit database URL is required.") from exc

    if url.get_backend_name() != "sqlite":
        raise BootstrapError(
            "Only disposable SQLite bootstrap targets are allowed; "
            "PostgreSQL URLs are blocked."
        )
    if not url.database or url.database == ":memory:":
        raise BootstrapError("Bootstrap requires an explicit SQLite file path.")
    if url.query.get("mode") == "ro":
        raise BootstrapError("The selected SQLite URL is read-only.")

    raw_path = Path(url.database)
    if not raw_path.is_absolute():
        raise BootstrapError(
            "Relative SQLite paths are rejected; use an absolute path in the "
            "disposable bootstrap directory."
        )

    _reject_symlink_components(raw_path)
    root = _disposable_directory()
    target = Path(os.path.abspath(str(raw_path)))
    if target.name == PERSISTENT_SQLITE_NAME:
        raise BootstrapError(
            "The persistent bc_lead_intelligence.db database is not an allowed bootstrap target."
        )
    if not target.is_relative_to(root):
        raise BootstrapError(
            "The SQLite target is outside the authorized disposable bootstrap directory."
        )
    _reject_symlink_components(target)
    return url, target


@contextmanager
def _exclusive_target_lock(target: Path) -> Iterator[None]:
    lock_path = target.parent / f".{target.name}.bootstrap.lock"
    if lock_path.is_symlink() or _has_windows_reparse_point(lock_path):
        raise BootstrapError("The bootstrap lock path is a symlink or reparse point.")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BootstrapError(
                    "The disposable bootstrap target is already being bootstrapped "
                    "by another process."
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BootstrapError(
                    "The disposable bootstrap target is already being bootstrapped "
                    "by another process."
                ) from exc
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


def _inventory_table(
    connection: Connection,
    table_name: str,
    schema: str | None,
) -> TableInventory:
    inspector = inspect(connection)
    kwargs = {"schema": schema} if schema is not None else {}
    reflected = Table(
        table_name,
        MetaData(),
        autoload_with=connection,
        **kwargs,
    )
    has_data = connection.execute(select(1).select_from(reflected).limit(1)).first() is not None
    primary_key = inspector.get_pk_constraint(table_name, **kwargs)
    foreign_keys = inspector.get_foreign_keys(table_name, **kwargs)
    unique_constraints = inspector.get_unique_constraints(table_name, **kwargs)
    check_constraints = inspector.get_check_constraints(table_name, **kwargs)
    indexes = inspector.get_indexes(table_name, **kwargs)
    return TableInventory(
        columns=tuple(column.name for column in reflected.columns),
        primary_key=tuple(primary_key.get("constrained_columns") or ()),
        foreign_keys=tuple(
            sorted(
                f"{item['constrained_columns']}->{item['referred_table']}."
                f"{item['referred_columns']} {item.get('options', {})}"
                for item in foreign_keys
            )
        ),
        unique_constraints=tuple(
            sorted(str(item.get("column_names")) for item in unique_constraints)
        ),
        check_constraints=tuple(
            sorted(str(item.get("sqltext")) for item in check_constraints)
        ),
        indexes=tuple(
            sorted(
                f"{item['name']}:{item['column_names']}:unique={item['unique']}"
                for item in indexes
            )
        ),
        has_data=has_data,
    )


def inspect_target(connection: Connection) -> TargetInventory:
    inspector = inspect(connection)
    dialect = connection.dialect.name
    default_schema = inspector.default_schema_name
    schemas = tuple(inspector.get_schema_names())
    allowed_schemas = SYSTEM_SCHEMAS | (
        SQLITE_SCHEMAS if dialect == "sqlite" else {default_schema}
    )
    unexpected_schemas = tuple(sorted(set(schemas) - allowed_schemas))
    tables: dict[str, TableInventory] = {}
    views: list[str] = []
    sequences: list[str] = []
    versions: tuple[str, ...] | None = None

    for schema in schemas:
        if schema in SYSTEM_SCHEMAS or schema.startswith(
            ("pg_temp_", "pg_toast_temp_")
        ):
            continue
        kwargs = {"schema": schema}
        for table_name in inspector.get_table_names(**kwargs):
            qualified_name = f"{schema}.{table_name}"
            is_version_table = table_name == "alembic_version"
            try:
                details = _inventory_table(
                    connection,
                    table_name,
                    schema,
                )
                tables[qualified_name] = details
                if is_version_table:
                    versions = tuple(
                        connection.execute(
                            text(
                                f'SELECT version_num FROM "{schema}"."alembic_version"'
                                if dialect == "postgresql"
                                else "SELECT version_num FROM alembic_version"
                            )
                        )
                        .scalars()
                        .all()
                    )
            except SQLAlchemyError as exc:
                tables[qualified_name] = TableInventory(
                    columns=(f"inspection-error:{type(exc).__name__}",),
                    primary_key=(),
                    foreign_keys=(),
                    unique_constraints=(),
                    check_constraints=(),
                    indexes=(),
                    has_data=False,
                )
        views.extend(
            f"{schema}.{view_name}" for view_name in inspector.get_view_names(**kwargs)
        )
        if dialect == "postgresql":
            views.extend(
                f"{schema}.{view_name}"
                for view_name in inspector.get_materialized_view_names(**kwargs)
            )
            sequences.extend(
                f"{schema}.{sequence_name}"
                for sequence_name in inspector.get_sequence_names(**kwargs)
            )

    return TargetInventory(
        dialect=dialect,
        schemas=schemas,
        tables=tables,
        views=tuple(sorted(views)),
        sequences=tuple(sorted(sequences)),
        versions=versions,
        unexpected_schemas=unexpected_schemas,
    )


def _verify_alembic_revision(connection: Connection) -> None:
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        raise BootstrapError("Alembic did not create its version table.")
    columns = inspector.get_columns("alembic_version")
    if len(columns) != 1 or columns[0]["name"] != "version_num":
        raise BootstrapError("The Alembic version table has an unexpected schema.")
    if columns[0]["nullable"]:
        raise BootstrapError("The Alembic version column must be non-null.")
    versions = tuple(
        connection.execute(text("SELECT version_num FROM alembic_version"))
        .scalars()
        .all()
    )
    if versions != (BASELINE_REVISION,):
        raise BootstrapError(
            f"Expected exactly one Alembic revision {BASELINE_REVISION}; got {versions}."
        )


def bootstrap_database(
    database_url: str,
    *,
    target_environment: str,
    confirm_disposable: bool,
) -> BootstrapResult:
    if target_environment != "disposable-test" or not confirm_disposable:
        raise BootstrapError(
            "Explicit target-environment=disposable-test and confirmation are required."
        )
    url, target = _validate_database_url(database_url)
    identity = _capture_target_identity(target)
    with _exclusive_target_lock(target):
        _verify_target_identity(target, identity)
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                if identity.exists is False:
                    identity = _capture_target_identity(target)
                else:
                    _verify_target_identity(target, identity)
                inventory = inspect_target(connection)
                if not inventory.is_empty:
                    raise BootstrapError(
                        "Bootstrap requires a structurally empty target; "
                        + inventory.describe()
                    )
                _verify_target_identity(target, identity)

                try:
                    BASELINE_METADATA.create_all(connection, checkfirst=False)
                    identity = _capture_target_identity(target)
                    _verify_target_identity(target, identity)
                    validate_schema(connection)
                    _verify_target_identity(target, identity)
                except BootstrapError:
                    raise
                except Exception as exc:
                    raise BootstrapError(
                        "Pre-stamp bootstrap failure: schema creation or initial "
                        f"validation failed ({type(exc).__name__})."
                    ) from exc

                config = Config(str(ALEMBIC_CONFIG_PATH))
                config.attributes["bootstrap_stamp"] = True
                config.attributes["connection"] = connection
                try:
                    _verify_target_identity(target, identity)
                    command.stamp(config, BASELINE_REVISION)
                    identity = _capture_target_identity(target)
                    validate_schema(connection, allow_alembic_version=True)
                    _verify_alembic_revision(connection)
                    _verify_target_identity(target, identity)
                except Exception as exc:
                    raise BootstrapError(
                        "Post-stamp bootstrap failure: an Alembic stamp was attempted "
                        "and the subsequent verification did not complete "
                        f"({type(exc).__name__})."
                    ) from exc

            return BootstrapResult(
                dialect=engine.dialect.name,
                revision=BASELINE_REVISION,
                table_count=len(BASELINE_METADATA.tables),
            )
        finally:
            engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--target-environment",
        required=True,
        choices=("disposable-test",),
    )
    parser.add_argument("--confirm-disposable", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_disposable:
        parser.error("--confirm-disposable is required")

    try:
        result = bootstrap_database(
            args.database_url,
            target_environment=args.target_environment,
            confirm_disposable=args.confirm_disposable,
        )
    except BootstrapError as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Bootstrap validated and recorded {result.revision} "
        f"for {result.dialect} ({result.table_count} tables)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
