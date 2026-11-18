import asyncio
import logging

from backend.app.db import SessionLocal
from backend.app.services.conversation_history import purge_expired_message_content
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def purge_expired_content() -> int:
    with SessionLocal() as db:
        purged = purge_expired_message_content(db)
        db.commit()
        return purged


async def retention_cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(purge_expired_content)
        except SQLAlchemyError:
            logger.exception("Expired message retention cleanup failed.")
            await asyncio.sleep(5 * 60)
        else:
            await asyncio.sleep(24 * 60 * 60)
