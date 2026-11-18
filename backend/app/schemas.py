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
