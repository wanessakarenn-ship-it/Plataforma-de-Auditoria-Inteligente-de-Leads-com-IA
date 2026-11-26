"""Frozen SQLAlchemy Core schema for the 0010 bootstrap baseline.

This metadata is intentionally independent of the application's ORM models and the
legacy Alembic revision files.
"""

from __future__ import annotations

import re

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.engine import Connection
from sqlalchemy.sql.schema import CheckConstraint

BASELINE_REVISION = "0010_karen_simulations"
BASELINE_METADATA = MetaData()


def _timestamps() -> tuple[Column, Column]:
    return (
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )


Table(
    "import_batches",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=True),
    Column("filename", String(255), nullable=False),
    Column("file_type", String(10), nullable=False),
    Column("status", String(24), nullable=False),
    Column("mapping", JSON, nullable=False),
    Column("records_json", JSON, nullable=False),
    Column("total_rows", Integer, nullable=False),
    Column("imported_rows", Integer, nullable=False),
    Column("duplicate_rows", Integer, nullable=False),
    Column("error_rows", Integer, nullable=False),
    Column("warning_rows", Integer, nullable=False),
    Column("errors_json", JSON, nullable=False),
    *_timestamps(),
)
Index("ix_import_batches_tenant_id", BASELINE_METADATA.tables["import_batches"].c.tenant_id)

for table_name in ("loss_reasons", "disqualification_reasons"):
    Table(
        table_name,
        BASELINE_METADATA,
        Column("id", String(36), primary_key=True),
        Column("name", String(160), nullable=False, unique=True),
        Column("active", Boolean, nullable=False),
        *_timestamps(),
    )

Table(
    "leads",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=True),
    Column("external_id", String(160), nullable=True),
    Column("first_name", String(120), nullable=True),
    Column("last_name", String(160), nullable=True),
    Column("company", String(240), nullable=True),
    Column("crm_created_at", DateTime(timezone=True), nullable=True),
    Column("campaign", String(240), nullable=True),
    Column("monthly_account_value", Numeric(14, 2), nullable=True),
    Column("email", String(320), nullable=True),
    Column("email_normalized", String(320), nullable=True),
    Column("phone", String(80), nullable=True),
    Column("phone_normalized", String(24), nullable=True),
    Column("source", String(120), nullable=True),
    Column("status", String(120), nullable=True),
    Column("phase", String(120), nullable=True),
    Column("classification", String(40), nullable=False),
    Column("loss_reason", String(240), nullable=True),
    Column("disqualification_reason", String(240), nullable=True),
    Column("loss_reason_description", Text, nullable=True),
    Column("raw_fields", JSON, nullable=False),
    Column("import_batch_id", String(36), ForeignKey("import_batches.id"), nullable=True),
    *_timestamps(),
    UniqueConstraint("tenant_id", "external_id", name="uq_leads_tenant_external_id"),
)
Index("ix_leads_tenant_id", BASELINE_METADATA.tables["leads"].c.tenant_id)
Index("ix_leads_email_normalized", BASELINE_METADATA.tables["leads"].c.email_normalized)
Index("ix_leads_phone_normalized", BASELINE_METADATA.tables["leads"].c.phone_normalized)
Index("ix_leads_classification", BASELINE_METADATA.tables["leads"].c.classification)

Table(
    "lead_status_history",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("lead_id", String(36), ForeignKey("leads.id"), nullable=False),
    Column("previous_status", String(120), nullable=True),
    Column("current_status", String(120), nullable=True),
    Column("previous_phase", String(120), nullable=True),
    Column("current_phase", String(120), nullable=True),
    Column("changed_at", DateTime(timezone=True), nullable=False),
    Column("origin", String(40), nullable=False),
)
Index(
    "ix_lead_status_history_lead_id",
    BASELINE_METADATA.tables["lead_status_history"].c.lead_id,
)

Table(
    "conversations",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("lead_id", String(36), ForeignKey("leads.id"), nullable=False),
    Column("channel", String(32), nullable=False),
    Column("external_id", String(160), nullable=True),
    Column("capture_source", String(120), nullable=True),
    Column("sync_state", String(24), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("ended_at", DateTime(timezone=True), nullable=True),
    *_timestamps(),
)
Index("ix_conversations_lead_id", BASELINE_METADATA.tables["conversations"].c.lead_id)

Table(
    "messages",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("conversation_id", String(36), ForeignKey("conversations.id"), nullable=False),
    Column("provider_message_id", String(160), nullable=True),
    Column("direction", String(16), nullable=False),
    Column("sender", String(320), nullable=True),
    Column("recipient", String(320), nullable=True),
    Column("body", Text, nullable=False),
    Column("message_type", String(32), nullable=False),
    Column("capture_source", String(120), nullable=True),
    Column("authorized_for_audit", Boolean, nullable=False),
    Column("sync_state", String(24), nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=True),
    Column("edited_at", DateTime(timezone=True), nullable=True),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("retention_until", DateTime(timezone=True), nullable=True),
    Column("metadata_json", JSON, nullable=False),
    UniqueConstraint(
        "conversation_id",
        "provider_message_id",
        name="uq_message_conversation_provider_id",
    ),
)
Index("ix_messages_conversation_id", BASELINE_METADATA.tables["messages"].c.conversation_id)

Table(
    "message_events",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column(
        "message_id",
        String(36),
        ForeignKey("messages.id", name="fk_message_events_message_id"),
        nullable=False,
    ),
    Column("event_type", String(24), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("source", String(120), nullable=False),
    Column("before_content_sha256", String(64), nullable=True),
    Column("after_content_sha256", String(64), nullable=True),
    Column("provider_id_hash", String(64), nullable=True),
    Column("conversation_id_hash", String(64), nullable=True),
    Column("tombstone_until", DateTime(timezone=True), nullable=True),
)
Index("ix_message_events_message_id", BASELINE_METADATA.tables["message_events"].c.message_id)

Table(
    "audits",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("lead_id", String(36), ForeignKey("leads.id"), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("execution_mode", String(16), nullable=False),
    Column("model", String(120), nullable=True),
    Column("model_version", String(160), nullable=True),
    Column("prompt_version", String(64), nullable=True),
    Column("status", String(24), nullable=False),
    Column("classification", String(24), nullable=False),
    Column("original_reason", Text, nullable=False),
    Column("justification", Text, nullable=False),
    Column("limitations_json", JSON, nullable=False),
    Column("alternative_reason", Text, nullable=True),
    Column("requires_human_review", Boolean, nullable=False),
    Column("estimated_cost_usd", Float, nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column(
        "reprocess_of_id",
        String(36),
        ForeignKey("audits.id", name="fk_audits_reprocess_of_id"),
        nullable=True,
    ),
    Column("review_status", String(24), nullable=False),
    Column("review_notes", Text, nullable=True),
    Column("reviewed_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("result_json", JSON, nullable=False),
    Column("error_message", Text, nullable=True),
    *_timestamps(),
)
Index("ix_audits_lead_id", BASELINE_METADATA.tables["audits"].c.lead_id)
Index("ix_audits_reprocess_of_id", BASELINE_METADATA.tables["audits"].c.reprocess_of_id)

Table(
    "evidence",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("audit_id", String(36), ForeignKey("audits.id"), nullable=False),
    Column(
        "message_id",
        String(36),
        ForeignKey("messages.id", name="fk_evidence_message_id"),
        nullable=True,
    ),
    Column("source_type", String(40), nullable=False),
    Column("source_id", String(160), nullable=True),
    Column("excerpt", Text, nullable=False),
    Column("referenced_at", DateTime(timezone=True), nullable=True),
    Column("verified", Boolean, nullable=False),
    Column("retention_until", DateTime(timezone=True), nullable=True),
    Column("relevance_score", Float, nullable=True),
)
Index("ix_evidence_audit_id", BASELINE_METADATA.tables["evidence"].c.audit_id)
Index("ix_evidence_message_id", BASELINE_METADATA.tables["evidence"].c.message_id)

Table(
    "audit_queue",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("lead_id", String(36), ForeignKey("leads.id"), nullable=False, unique=True),
    Column("status", String(24), nullable=False),
    *_timestamps(),
)

Table(
    "contact_queue",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("lead_id", String(36), ForeignKey("leads.id"), nullable=False, unique=True),
    Column("status", String(40), nullable=False),
    Column("eligible", Boolean, nullable=False),
    *_timestamps(),
)

Table(
    "contact_permissions",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("lead_id", String(36), ForeignKey("leads.id"), nullable=False, unique=True),
    Column("channel", String(32), nullable=False),
    Column("consent_status", String(24), nullable=False),
    Column("consented_at", DateTime(timezone=True), nullable=True),
    Column("source", String(120), nullable=True),
    Column("suppression_reason", String(240), nullable=True),
    *_timestamps(),
)

Table(
    "processing_logs",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("import_batch_id", String(36), ForeignKey("import_batches.id"), nullable=True),
    Column("level", String(16), nullable=False),
    Column("event", String(80), nullable=False),
    Column("message", Text, nullable=False),
    Column("details_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index(
    "ix_processing_logs_import_batch_id",
    BASELINE_METADATA.tables["processing_logs"].c.import_batch_id,
)

Table(
    "admin_action_logs",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("actor_uid", String(128), nullable=False),
    Column("actor_role", String(24), nullable=False),
    Column("tenant_id", String(128), nullable=False),
    Column("method", String(8), nullable=False),
    Column("route", String(240), nullable=False),
    Column("resource_id", String(160), nullable=True),
    Column("outcome", String(24), nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_admin_action_logs_tenant_id", BASELINE_METADATA.tables["admin_action_logs"].c.tenant_id)

Table(
    "ai_agents",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("template_key", String(80), nullable=True),
    Column("name", String(120), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("process_role", String(120), nullable=False),
    Column("model_id", String(64), nullable=False),
    Column("instructions", Text, nullable=False),
    Column("system_prompt", Text, nullable=False),
    Column("decision_criteria", Text, nullable=False),
    Column("safety_rules", Text, nullable=False),
    Column("human_handoff", Text, nullable=False),
    Column("temperature", Float, nullable=False),
    Column("max_output_tokens", Integer, nullable=False),
    Column("max_cost_usd", Numeric(10, 4), nullable=False),
    Column("publication_state", String(16), nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column(
        "knowledge_requires_approval",
        Boolean,
        nullable=False,
        server_default="true",
    ),
    Column("current_version", Integer, nullable=False),
    Column("created_by_uid", String(128), nullable=False),
    Column("approved_by_uid", String(128), nullable=True),
    Column("approved_at", DateTime(timezone=True), nullable=True),
    *_timestamps(),
    UniqueConstraint("tenant_id", "template_key", name="uq_ai_agents_tenant_template"),
)
Index("ix_ai_agents_tenant_id", BASELINE_METADATA.tables["ai_agents"].c.tenant_id)
Index(
    "ix_ai_agents_tenant_active",
    BASELINE_METADATA.tables["ai_agents"].c.tenant_id,
    BASELINE_METADATA.tables["ai_agents"].c.is_active,
)
Index(
    "uq_ai_agents_tenant_id",
    BASELINE_METADATA.tables["ai_agents"].c.tenant_id,
    BASELINE_METADATA.tables["ai_agents"].c.id,
    unique=True,
)

Table(
    "ai_agent_versions",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column(
        "agent_id",
        String(36),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("tenant_id", String(128), nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("snapshot_json", JSON, nullable=False),
    Column("created_by_uid", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("agent_id", "version_number", name="uq_ai_agent_versions_number"),
)
Index(
    "ix_ai_agent_versions_tenant_id",
    BASELINE_METADATA.tables["ai_agent_versions"].c.tenant_id,
)
Index(
    "ix_ai_agent_versions_tenant_agent",
    BASELINE_METADATA.tables["ai_agent_versions"].c.tenant_id,
    BASELINE_METADATA.tables["ai_agent_versions"].c.agent_id,
)

Table(
    "knowledge_contents",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("title", String(200), nullable=False),
    Column("category", String(32), nullable=False),
    Column("body", Text, nullable=False),
    Column("origin", String(300), nullable=False),
    Column("source_type", String(16), nullable=False),
    Column("source_name", String(255), nullable=True),
    Column("source_sha256", String(64), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=True),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    Column("status", String(16), nullable=False),
    Column("current_version", Integer, nullable=False),
    Column("created_by_uid", String(128), nullable=False),
    Column("approved_by_uid", String(128), nullable=True),
    Column("approved_at", DateTime(timezone=True), nullable=True),
    Column("archived_at", DateTime(timezone=True), nullable=True),
    *_timestamps(),
    UniqueConstraint("tenant_id", "id", name="uq_knowledge_contents_tenant_id"),
)
Index(
    "ix_knowledge_contents_tenant_id",
    BASELINE_METADATA.tables["knowledge_contents"].c.tenant_id,
)
Index(
    "ix_knowledge_contents_status",
    BASELINE_METADATA.tables["knowledge_contents"].c.status,
)
Index(
    "ix_knowledge_contents_tenant_status",
    BASELINE_METADATA.tables["knowledge_contents"].c.tenant_id,
    BASELINE_METADATA.tables["knowledge_contents"].c.status,
)
Index(
    "ix_knowledge_contents_tenant_category",
    BASELINE_METADATA.tables["knowledge_contents"].c.tenant_id,
    BASELINE_METADATA.tables["knowledge_contents"].c.category,
)

Table(
    "knowledge_content_versions",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("content_id", String(36), nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("snapshot_json", JSON, nullable=False),
    Column("created_by_uid", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "content_id"],
        ["knowledge_contents.tenant_id", "knowledge_contents.id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "tenant_id",
        "content_id",
        "version_number",
        name="uq_knowledge_versions",
    ),
)
Index(
    "ix_knowledge_versions_tenant_id",
    BASELINE_METADATA.tables["knowledge_content_versions"].c.tenant_id,
)
Index(
    "ix_knowledge_versions_tenant_content",
    BASELINE_METADATA.tables["knowledge_content_versions"].c.tenant_id,
    BASELINE_METADATA.tables["knowledge_content_versions"].c.content_id,
)

Table(
    "knowledge_agent_links",
    BASELINE_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("agent_id", String(36), primary_key=True),
    Column("content_id", String(36), primary_key=True),
    Column("created_by_uid", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "agent_id"],
        ["ai_agents.tenant_id", "ai_agents.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "content_id"],
        ["knowledge_contents.tenant_id", "knowledge_contents.id"],
        ondelete="CASCADE",
    ),
)
Index(
    "ix_knowledge_agent_links_agent",
    BASELINE_METADATA.tables["knowledge_agent_links"].c.tenant_id,
    BASELINE_METADATA.tables["knowledge_agent_links"].c.agent_id,
)
Index(
    "ix_knowledge_agent_links_content",
    BASELINE_METADATA.tables["knowledge_agent_links"].c.tenant_id,
    BASELINE_METADATA.tables["knowledge_agent_links"].c.content_id,
)

Table(
    "karen_simulations",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("agent_id", String(36), nullable=False),
    Column("scenario_key", String(48), nullable=False),
    Column("state", String(48), nullable=False),
    Column("created_by_uid", String(128), nullable=False),
    *_timestamps(),
    ForeignKeyConstraint(
        ["tenant_id", "agent_id"],
        ["ai_agents.tenant_id", "ai_agents.id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_karen_simulations_tenant_id"),
)
Index(
    "ix_karen_simulations_tenant_state",
    BASELINE_METADATA.tables["karen_simulations"].c.tenant_id,
    BASELINE_METADATA.tables["karen_simulations"].c.state,
)

Table(
    "karen_simulation_events",
    BASELINE_METADATA,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("simulation_id", String(36), nullable=False),
    Column("sequence_no", Integer, nullable=False),
    Column("event_type", String(48), nullable=False),
    Column("from_state", String(48), nullable=True),
    Column("to_state", String(48), nullable=True),
    Column("message", Text, nullable=True),
    Column("decision_json", JSON, nullable=False),
    Column("evidence_json", JSON, nullable=False),
    Column("evaluation_json", JSON, nullable=False),
    Column("actor_uid", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "simulation_id"],
        ["karen_simulations.tenant_id", "karen_simulations.id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id",
        "simulation_id",
        "sequence_no",
        name="uq_karen_simulation_event_sequence",
    ),
)
Index(
    "ix_karen_simulation_events_tenant_simulation",
    BASELINE_METADATA.tables["karen_simulation_events"].c.tenant_id,
    BASELINE_METADATA.tables["karen_simulation_events"].c.simulation_id,
    BASELINE_METADATA.tables["karen_simulation_events"].c.created_at,
)


def _normalized_sql(value: object | None) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value)).strip().lower()
    while result.startswith("(") and result.endswith(")"):
        result = result[1:-1].strip()
    return result.strip("'\"")


def _normalized_default(value: object | None, sql_type: object) -> str | None:
    normalized = _normalized_sql(value)
    if isinstance(sql_type, Boolean) and normalized in {"1", "true"}:
        return "true"
    return normalized


def _type_signature(sql_type: object, dialect: object) -> str:
    return re.sub(r"\s+", " ", sql_type.compile(dialect=dialect)).strip().upper()


def _column_signature(column: Column, dialect: object) -> tuple[object, ...]:
    default = column.server_default.arg if column.server_default is not None else None
    return (
        column.name,
        _type_signature(column.type, dialect),
        bool(column.nullable),
        _normalized_default(default, column.type),
    )


def _expected_foreign_keys(table: Table) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted([
        (
            tuple(element.parent.name for element in constraint.elements),
            constraint.referred_table.name,
            tuple(element.column.name for element in constraint.elements),
            _normalized_sql(constraint.ondelete) or "",
            _normalized_sql(constraint.onupdate) or "",
            bool(constraint.deferrable),
            _normalized_sql(constraint.initially) or "",
        )
        for constraint in table.foreign_key_constraints
    ], key=repr))


def _actual_foreign_keys(
    connection: Connection, table_name: str
) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted([
        (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
            _normalized_sql(item.get("options", {}).get("ondelete")) or "",
            _normalized_sql(item.get("options", {}).get("onupdate")) or "",
            bool(item.get("options", {}).get("deferrable")),
            _normalized_sql(item.get("options", {}).get("initially")) or "",
        )
        for item in inspect(connection).get_foreign_keys(table_name)
    ], key=repr))


def _expected_uniques(table: Table) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted([
        (
            tuple(column.name for column in constraint.columns),
            bool(constraint.deferrable),
            _normalized_sql(constraint.initially) or "",
        )
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ], key=repr))


def _actual_uniques(
    connection: Connection, table_name: str
) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted([
        (
            tuple(item["column_names"]),
            bool(item.get("deferrable")),
            _normalized_sql(item.get("initially")) or "",
        )
        for item in inspect(connection).get_unique_constraints(table_name)
    ], key=repr))


def _expected_indexes(table: Table) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted([
        (
            index.name,
            tuple(column.name for column in index.columns),
            bool(index.unique),
            (),
            "",
            (),
            (),
        )
        for index in table.indexes
    ], key=repr))


def _normalized_index_options(item: dict[str, object]) -> tuple[tuple[str, str], ...]:
    options = dict(item.get("dialect_options", {}))
    if str(options.get("postgresql_using", "")).lower() == "btree":
        options.pop("postgresql_using")
    if options.get("postgresql_include") == []:
        options.pop("postgresql_include")
    if options.get("postgresql_ops") == {}:
        options.pop("postgresql_ops")
    if options.get("postgresql_nulls_not_distinct") is False:
        options.pop("postgresql_nulls_not_distinct")
    options.pop("postgresql_where", None)
    return tuple(sorted((str(key), repr(value)) for key, value in options.items()))


def _actual_indexes(
    connection: Connection, table_name: str
) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted([
        (
            item["name"],
            tuple(item.get("column_names") or ()),
            bool(item["unique"]),
            tuple(item.get("expressions") or ()),
            _normalized_sql(item.get("dialect_options", {}).get("postgresql_where"))
            or "",
            tuple(item.get("include_columns") or ()),
            _normalized_index_options(item),
        )
        for item in inspect(connection).get_indexes(table_name)
        if not item.get("duplicates_constraint")
    ], key=repr))


def _expected_checks(table: Table) -> tuple[str, ...]:
    return tuple(sorted([
        _normalized_sql(constraint.sqltext) or ""
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]))


def _actual_checks(connection: Connection, table_name: str) -> tuple[str, ...]:
    return tuple(sorted([
        _normalized_sql(item["sqltext"]) or ""
        for item in inspect(connection).get_check_constraints(table_name)
    ]))


def _schema_differences(
    connection: Connection, *, allow_alembic_version: bool
) -> list[str]:
    inspector = inspect(connection)
    expected_names = set(BASELINE_METADATA.tables)
    actual_names = set(inspector.get_table_names())
    differences: list[str] = []
    if "alembic_version" in actual_names and allow_alembic_version:
        version_columns = inspector.get_columns("alembic_version")
        version_pk = inspector.get_pk_constraint("alembic_version")
        if (
            len(version_columns) != 1
            or version_columns[0]["name"] != "version_num"
            or _type_signature(version_columns[0]["type"], connection.dialect)
            != _type_signature(String(32), connection.dialect)
            or version_columns[0]["nullable"]
            or tuple(version_pk.get("constrained_columns") or ()) != ("version_num",)
        ):
            differences.append("Alembic version table schema differs")

    for name in sorted(expected_names - actual_names):
        differences.append(f"missing table {name}")
    allowed_extra_tables = {"alembic_version"} if allow_alembic_version else set()
    for name in sorted(actual_names - expected_names - allowed_extra_tables):
        differences.append(f"unexpected table {name}")

    for table_name in sorted(expected_names & actual_names):
        expected = BASELINE_METADATA.tables[table_name]
        actual_columns = inspector.get_columns(table_name)
        expected_columns = {
            column.name: _column_signature(column, connection.dialect)
            for column in expected.columns
        }
        actual_column_signatures = {
            column["name"]: (
                column["name"],
                _type_signature(column["type"], connection.dialect),
                bool(column["nullable"]),
                _normalized_default(column.get("default"), column["type"]),
            )
            for column in actual_columns
        }
        if actual_column_signatures != expected_columns:
            differences.append(f"columns/types/nullability/defaults differ for {table_name}")

        expected_pk = tuple(column.name for column in expected.primary_key.columns)
        actual_pk = tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
        if actual_pk != expected_pk:
            differences.append(f"primary key differs for {table_name}")

        if _expected_foreign_keys(expected) != _actual_foreign_keys(connection, table_name):
            differences.append(f"foreign keys/referential actions differ for {table_name}")
        if _expected_uniques(expected) != _actual_uniques(connection, table_name):
            differences.append(f"unique constraints differ for {table_name}")
        if _expected_indexes(expected) != _actual_indexes(connection, table_name):
            differences.append(f"indexes differ for {table_name}")
        if _expected_checks(expected) != _actual_checks(connection, table_name):
            differences.append(f"check constraints differ for {table_name}")

    if "alembic_version" in actual_names and not allow_alembic_version:
        differences.append("alembic_version exists before baseline validation")
    if inspector.get_view_names():
        differences.append("unexpected views exist")
    return differences


def validate_schema(connection: Connection, *, allow_alembic_version: bool = False) -> None:
    differences = _schema_differences(
        connection, allow_alembic_version=allow_alembic_version
    )
    if differences:
        raise ValueError("Baseline schema validation failed: " + "; ".join(differences))


def expected_table_names() -> frozenset[str]:
    return frozenset(BASELINE_METADATA.tables)


def expected_column_names(table_name: str) -> tuple[str, ...]:
    if table_name not in BASELINE_METADATA.tables:
        raise KeyError(table_name)
    return tuple(BASELINE_METADATA.tables[table_name].columns.keys())
