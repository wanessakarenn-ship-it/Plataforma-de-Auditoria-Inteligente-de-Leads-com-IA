from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None
    first_name: str | None
    last_name: str | None
    company: str | None
    email: str | None
    phone: str | None
    status: str | None
    phase: str | None
    classification: str
    loss_reason: str | None
    disqualification_reason: str | None
    loss_reason_description: str | None = None
    campaign: str | None = None
    source: str | None = None
    crm_created_at: datetime | None = None
    monthly_account_value: Decimal | None = None


class ImportPreviewResponse(BaseModel):
    import_id: str
    filename: str
    mapping: dict[str, str]
    total_rows: int
    valid_rows: int
    duplicate_rows: int
    error_rows: int
    warning_rows: int
    preview: list[dict]


class ImportConfirmResponse(BaseModel):
    import_id: str
    status: str
    imported_rows: int
    duplicate_rows: int
    error_rows: int


class QueueSummary(BaseModel):
    audit_pending: int
    contact_drafts: int
    contact_eligible: int


class VertexAuditRequest(BaseModel):
    lead_id: str
    context: str


class VertexAuditResult(BaseModel):
    summary: str
    signals: list[str]
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool = True


class AuditRunRequest(BaseModel):
    mode: Literal["simulated", "vertex"] = "simulated"


class AuditReviewRequest(BaseModel):
    decision: Literal["confirmed", "divergent", "inconclusive", "not_auditable"]
    notes: str | None = Field(default=None, max_length=4000)


class AdminUserRoleUpdate(BaseModel):
    role: Literal["admin", "auditor", "gestor"]


class AuditEvidenceResponse(BaseModel):
    id: str
    message_id: str | None
    source_id: str | None
    excerpt: str | None
    referenced_at: datetime | None
    verified: bool


class AuditResponse(BaseModel):
    id: str
    lead_id: str
    execution_mode: str
    model: str | None
    model_version: str | None
    prompt_version: str | None
    status: str
    classification: str
    original_reason: str
    justification: str
    limitations: list[str]
    alternative_reason: str | None
    requires_human_review: bool
    estimated_cost_usd: float
    input_tokens: int
    output_tokens: int
    reprocess_of_id: str | None
    review_status: str
    review_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime
    finished_at: datetime | None
    error_message: str | None
    evidence: list[AuditEvidenceResponse]
