from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def message_retention_deadline() -> datetime:
    return utc_now() + timedelta(days=90)


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ImportBatch(Base, Timestamped):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(24), default="preview")
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    records_json: Mapped[list] = mapped_column(JSON, default=list)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, default=0)
    errors_json: Mapped[list] = mapped_column(JSON, default=list)
    leads: Mapped[list["Lead"]] = relationship(back_populates="import_batch")


class LossReason(Base, Timestamped):
    __tablename__ = "loss_reasons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DisqualificationReason(Base, Timestamped):
    __tablename__ = "disqualification_reasons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lead(Base, Timestamped):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_email_normalized", "email_normalized"),
        Index("ix_leads_phone_normalized", "phone_normalized"),
        Index("ix_leads_classification", "classification"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    external_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    company: Mapped[str | None] = mapped_column(String(240), nullable=True)
    crm_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    campaign: Mapped[str | None] = mapped_column(String(240), nullable=True)
    monthly_account_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classification: Mapped[str] = mapped_column(String(40), default="unknown")
    loss_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    disqualification_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    loss_reason_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    import_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True
    )
    import_batch: Mapped[ImportBatch | None] = relationship(back_populates="leads")
    status_history: Mapped[list["LeadStatusHistory"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    audits: Mapped[list["Audit"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    audit_queue_item: Mapped["AuditQueueItem | None"] = relationship(
        back_populates="lead", cascade="all, delete-orphan", uselist=False
    )
    contact_queue_item: Mapped["ContactQueueItem | None"] = relationship(
        back_populates="lead", cascade="all, delete-orphan", uselist=False
    )
    contact_permission: Mapped["ContactPermission | None"] = relationship(
        back_populates="lead", cascade="all, delete-orphan", uselist=False
    )


class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    previous_phase: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_phase: Mapped[str | None] = mapped_column(String(120), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    origin: Mapped[str] = mapped_column(String(40), default="import")
    lead: Mapped[Lead] = relationship(back_populates="status_history")


class Conversation(Base, Timestamped):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="unknown")
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    capture_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sync_state: Mapped[str] = mapped_column(String(24), default="local")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead: Mapped[Lead] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "provider_message_id", name="uq_message_conversation_provider_id"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    direction: Mapped[str] = mapped_column(String(16))
    sender: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(32), default="text")
    capture_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    authorized_for_audit: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_state: Mapped[str] = mapped_column(String(24), default="local")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=message_retention_deadline
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    events: Mapped[list["MessageEvent"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessageEvent(Base):
    __tablename__ = "message_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[str] = mapped_column(String(120))
    before_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[Message] = relationship(back_populates="events")


class Audit(Base, Timestamped):
    __tablename__ = "audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="pending")
    execution_mode: Mapped[str] = mapped_column(String(16), default="simulated")
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    classification: Mapped[str] = mapped_column(String(24), default="inconclusive")
    original_reason: Mapped[str] = mapped_column(Text, default="")
    justification: Mapped[str] = mapped_column(Text, default="")
    limitations_json: Mapped[list] = mapped_column(JSON, default=list)
    alternative_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    reprocess_of_id: Mapped[str | None] = mapped_column(ForeignKey("audits.id"), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead: Mapped[Lead] = relationship(back_populates="audits")
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
    reprocess_of: Mapped["Audit | None"] = relationship(
        remote_side="Audit.id", foreign_keys=[reprocess_of_id]
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text)
    referenced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    audit: Mapped[Audit] = relationship(back_populates="evidence")


class AuditQueueItem(Base, Timestamped):
    __tablename__ = "audit_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    lead: Mapped[Lead] = relationship(back_populates="audit_queue_item")


class ContactQueueItem(Base, Timestamped):
    __tablename__ = "contact_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="draft_needs_review")
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    lead: Mapped[Lead] = relationship(back_populates="contact_queue_item")


class ContactPermission(Base, Timestamped):
    __tablename__ = "contact_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), unique=True)
    channel: Mapped[str] = mapped_column(String(32))
    consent_status: Mapped[str] = mapped_column(String(24), default="unknown")
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    suppression_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    lead: Mapped[Lead] = relationship(back_populates="contact_permission")


class ProcessingLog(Base):
    __tablename__ = "processing_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    import_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True, index=True
    )
    level: Mapped[str] = mapped_column(String(16), default="info")
    event: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
