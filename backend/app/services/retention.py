import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.db import SessionLocal, engine
from backend.app.services.conversation_history import purge_expired_message_content

logger = logging.getLogger(__name__)
RETENTION_CLEANUP_LOCK_KEY = 0x4C494149


class RetentionLockAcquisitionError(SQLAlchemyError):
    pass


class RetentionLockReleaseError(SQLAlchemyError):
    pass


def _discard_connection(connection, cause: BaseException) -> None:
    try:
        connection.invalidate(cause)
    except BaseException as invalidate_error:
        if not connection.invalidated:
            try:
                connection.detach()
            except BaseException as detach_error:
                raise BaseExceptionGroup(
                    "Could not invalidate or detach the connection holding a retention lock.",
                    [cause, invalidate_error, detach_error],
                ) from None
        raise BaseExceptionGroup(
            "Connection invalidation failed while handling a retention lock error.",
            [cause, invalidate_error],
        ) from None

    if not connection.invalidated:
        try:
            connection.detach()
        except BaseException as detach_error:
            raise BaseExceptionGroup(
                "Could not invalidate or detach the connection holding a retention lock.",
                [cause, detach_error],
            ) from None


def _release_advisory_lock(connection) -> None:
    try:
        released = connection.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": RETENTION_CLEANUP_LOCK_KEY},
        ).scalar_one()
        if not released:
            raise RetentionLockReleaseError(
                "PostgreSQL did not confirm advisory lock release."
            )
    except BaseException as release_error:
        _discard_connection(connection, release_error)
        if isinstance(release_error, RetentionLockReleaseError):
            raise
        if isinstance(release_error, Exception):
            raise RetentionLockReleaseError(
                "Could not confirm PostgreSQL advisory lock release."
            ) from release_error
        raise


def _run_cleanup(connection) -> int:
    with SessionLocal(bind=connection) as db:
        purged = purge_expired_message_content(db)
        db.commit()
        return purged


def purge_expired_content() -> int:
    with engine.connect() as connection:
        uses_advisory_lock = connection.dialect.name == "postgresql"
        if uses_advisory_lock:
            try:
                acquired = connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": RETENTION_CLEANUP_LOCK_KEY},
                ).scalar_one()
            except BaseException as acquisition_error:
                _discard_connection(connection, acquisition_error)
                if isinstance(acquisition_error, Exception):
                    raise RetentionLockAcquisitionError(
                        "Could not confirm PostgreSQL advisory lock acquisition."
                    ) from acquisition_error
                raise
            if not acquired:
                return 0

        if not uses_advisory_lock:
            return _run_cleanup(connection)

        try:
            purged = _run_cleanup(connection)
        except BaseException as cleanup_error:
            try:
                _release_advisory_lock(connection)
            except BaseException as release_error:
                raise BaseExceptionGroup(
                    "Retention cleanup and advisory lock release both failed.",
                    [cleanup_error, release_error],
                ) from None
            raise

        _release_advisory_lock(connection)
        return purged


async def retention_cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(purge_expired_content)
        except (SQLAlchemyError, ExceptionGroup) as exc:
            logger.error("Expired message retention cleanup failed (%s).", type(exc).__name__)
            await asyncio.sleep(5 * 60)
        else:
            await asyncio.sleep(24 * 60 * 60)
