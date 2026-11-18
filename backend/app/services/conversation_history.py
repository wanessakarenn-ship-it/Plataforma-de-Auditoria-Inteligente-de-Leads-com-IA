from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from backend.app.models import (
    Evidence,
    Message,
    MessageEvent,
    message_retention_deadline,
    utc_now,
)


class DuplicateMessageConflict(ValueError):
    pass


def persist_message(
    db: Session,
    *,
    conversation_id: str,
    direction: str,
    body: str,
    provider_message_id: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    message_type: str = "text",
    capture_source: str | None = None,
    authorized_for_audit: bool = False,
    sent_at: datetime | None = None,
    metadata: dict | None = None,
) -> Message:
    if provider_message_id:
        message_id_hash = sha256(provider_message_id.encode()).hexdigest()
        conversation_id_hash = sha256(conversation_id.encode()).hexdigest()
        suppressed = db.scalar(
            select(MessageEvent.id)
            .where(
                MessageEvent.provider_id_hash == message_id_hash,
                or_(
                    MessageEvent.conversation_id_hash == conversation_id_hash,
                    MessageEvent.conversation_id_hash.is_(None),
                ),
                MessageEvent.tombstone_until.is_not(None),
                MessageEvent.tombstone_until > utc_now(),
            )
            .limit(1)
        )
        if suppressed:
            raise DuplicateMessageConflict(
                "Deleted provider message remains suppressed by its deletion event."
            )
        existing = db.scalar(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.provider_message_id == provider_message_id,
            )
        )
        if existing:
            if existing.body != body or existing.deleted_at is not None:
                raise DuplicateMessageConflict(
                    "Provider message identifier already exists with different content."
                )
            return existing
    message = Message(
        conversation_id=conversation_id,
        direction=direction,
        body=body,
        provider_message_id=provider_message_id,
        sender=sender,
        recipient=recipient,
        message_type=message_type,
        capture_source=capture_source,
        authorized_for_audit=authorized_for_audit,
        sent_at=sent_at,
        metadata_json=metadata or {},
    )
    db.add(message)
    db.flush()
    return message


def record_message_edit(
    db: Session,
    message: Message,
    *,
    body: str,
    source: str,
    authorized_for_audit: bool | None = None,
) -> MessageEvent:
    if message.deleted_at is not None:
        raise ValueError("A deleted message cannot be edited.")
    event = MessageEvent(message_id=message.id, event_type="edited", source=source)
    message.body = body
    message.edited_at = utc_now()
    if authorized_for_audit is not None:
        message.authorized_for_audit = authorized_for_audit
    db.add(event)
    db.flush()
    return event


def record_message_deletion(
    db: Session, message: Message, *, source: str = "authorized_deletion"
) -> MessageEvent:
    provider_id_hash = (
        sha256(message.provider_message_id.encode()).hexdigest()
        if message.provider_message_id
        else None
    )
    conversation_id_hash = (
        sha256(message.conversation_id.encode()).hexdigest()
        if message.provider_message_id
        else None
    )
    event = MessageEvent(
        message_id=message.id,
        event_type="deleted",
        source=source,
        provider_id_hash=provider_id_hash,
        conversation_id_hash=conversation_id_hash,
        tombstone_until=message.retention_until or message_retention_deadline(),
    )
    _scrub_message(message, db)
    db.add(event)
    db.flush()
    return event


def purge_expired_message_content(
    db: Session, *, now: datetime | None = None
) -> int:
    cutoff = now or utc_now()
    expired = db.scalars(
        select(Message).where(
            Message.retention_until <= cutoff,
            Message.deleted_at.is_(None),
        )
    ).all()
    for message in expired:
        event = MessageEvent(
            message_id=message.id,
            event_type="retention_expired",
            source="retention_policy",
            occurred_at=cutoff,
        )
        _scrub_message(message, db, deleted_at=cutoff)
        db.add(event)
    db.flush()
    db.execute(
        update(MessageEvent)
        .where(
            MessageEvent.tombstone_until.is_not(None),
            MessageEvent.tombstone_until <= cutoff,
        )
        .values(
            provider_id_hash=None,
            conversation_id_hash=None,
            tombstone_until=None,
        )
    )
    db.flush()
    return len(expired)


def _scrub_message(
    message: Message,
    db: Session,
    *,
    deleted_at: datetime | None = None,
) -> None:
    message.body = ""
    message.sender = None
    message.recipient = None
    message.provider_message_id = None
    message.metadata_json = {}
    message.authorized_for_audit = False
    message.deleted_at = deleted_at or utc_now()
    for evidence in db.scalars(
        select(Evidence).where(Evidence.message_id == message.id)
    ).all():
        evidence.excerpt = ""
        evidence.source_id = None
        evidence.verified = False


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
