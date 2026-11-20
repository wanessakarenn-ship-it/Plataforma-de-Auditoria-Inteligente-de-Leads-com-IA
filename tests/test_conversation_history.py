from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.app.models import (
    Audit,
    Conversation,
    Evidence,
    Lead,
    Message,
    MessageEvent,
    utc_now,
)
from backend.app.services.conversation_history import (
    DuplicateMessageConflict,
    persist_message,
    purge_expired_message_content,
    record_message_deletion,
    record_message_edit,
)


def create_lead_and_conversation(session):
    lead = Lead(
        tenant_id="test-tenant",
        classification="lost",
        loss_reason="Synthetic reason",
    )
    session.add(lead)
    session.flush()
    conversation = Conversation(
        lead_id=lead.id,
        channel="synthetic",
        capture_source="test fixture",
    )
    session.add(conversation)
    session.flush()
    return lead, conversation


def test_message_persistence_is_idempotent_and_rejects_conflicting_duplicate(
    db_session_factory,
):
    with db_session_factory() as session:
        _, conversation = create_lead_and_conversation(session)
        first = persist_message(
            session,
            conversation_id=conversation.id,
            direction="inbound",
            provider_message_id="synthetic-message-1",
            body="Synthetic authorized text.",
            authorized_for_audit=True,
        )
        same = persist_message(
            session,
            conversation_id=conversation.id,
            direction="inbound",
            provider_message_id="synthetic-message-1",
            body="Synthetic authorized text.",
            authorized_for_audit=True,
        )
        assert same.id == first.id
        with pytest.raises(DuplicateMessageConflict):
            persist_message(
                session,
                conversation_id=conversation.id,
                direction="inbound",
                provider_message_id="synthetic-message-1",
                body="Conflicting synthetic text.",
            )
        assert session.scalar(select(MessageEvent.id)) is None


def test_edits_and_deletions_are_audited_and_scrub_evidence(db_session_factory):
    with db_session_factory() as session:
        _, conversation = create_lead_and_conversation(session)
        message = persist_message(
            session,
            conversation_id=conversation.id,
            direction="inbound",
            provider_message_id="synthetic-message-2",
            body="Original synthetic text.",
            authorized_for_audit=True,
        )
        audit = Audit(lead_id=conversation.lead_id, original_reason="Synthetic reason")
        session.add(audit)
        session.flush()
        evidence = Evidence(
            audit_id=audit.id,
            message_id=message.id,
            source_type="message",
            source_id="synthetic-message-2",
            excerpt="Original synthetic text.",
            verified=True,
            retention_until=message.retention_until,
        )
        session.add(evidence)
        session.flush()

        record_message_edit(
            session,
            message,
            body="Edited synthetic text.",
            source="test fixture",
        )
        assert message.body == "Edited synthetic text."
        assert message.edited_at is not None
        assert session.scalar(
            select(MessageEvent).where(MessageEvent.event_type == "edited")
        )

        record_message_deletion(session, message)
        assert message.body == ""
        assert not message.authorized_for_audit
        assert message.provider_message_id is None
        assert evidence.excerpt == ""
        assert not evidence.verified
        assert session.scalar(
            select(MessageEvent).where(MessageEvent.event_type == "deleted")
        )
        with pytest.raises(DuplicateMessageConflict, match="remains suppressed"):
            persist_message(
                session,
                conversation_id=conversation.id,
                direction="inbound",
                provider_message_id="synthetic-message-2",
                body="Reimported synthetic text.",
            )
        other_conversation = Conversation(
            lead_id=conversation.lead_id,
            channel="synthetic",
            capture_source="test fixture",
        )
        session.add(other_conversation)
        session.flush()
        other_message = persist_message(
            session,
            conversation_id=other_conversation.id,
            direction="inbound",
            provider_message_id="synthetic-message-2",
            body="Same provider ID in another conversation.",
        )
        assert other_message.conversation_id == other_conversation.id


def test_expired_message_content_is_purged_and_marked(db_session_factory):
    with db_session_factory() as session:
        _, conversation = create_lead_and_conversation(session)
        message = persist_message(
            session,
            conversation_id=conversation.id,
            direction="inbound",
            body="Expired synthetic content.",
            authorized_for_audit=True,
        )
        message.retention_until = utc_now() - timedelta(seconds=1)
        session.flush()
        count = purge_expired_message_content(session)
        assert count == 1
        assert message.body == ""
        assert message.deleted_at is not None
        event = session.scalar(
            select(MessageEvent).where(MessageEvent.event_type == "retention_expired")
        )
        assert event is not None


def test_expired_deletion_tombstone_scrubs_both_message_identifiers(db_session_factory):
    with db_session_factory() as session:
        _, conversation = create_lead_and_conversation(session)
        message = persist_message(
            session,
            conversation_id=conversation.id,
            direction="inbound",
            provider_message_id="synthetic-expiring-message",
            body="Synthetic content.",
        )
        tombstone = record_message_deletion(session, message)
        assert tombstone.provider_id_hash
        assert tombstone.conversation_id_hash

        tombstone.tombstone_until = utc_now() - timedelta(seconds=1)
        purge_expired_message_content(session)

        session.refresh(tombstone)
        assert tombstone.provider_id_hash is None
        assert tombstone.conversation_id_hash is None
        assert tombstone.tombstone_until is None
