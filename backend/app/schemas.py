from datetime import datetime
from decimal import Decimal
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_synthetic_text(value: str | None) -> str | None:
    if value and re.search(
        r"(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})|(?:\+?\d[\d\s().-]{7,}\d)",
        value,
        re.IGNORECASE,
    ):
        raise ValueError("Use somente texto fictício; e-mail e telefone não são aceitos.")
    return value


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


class AIAgentWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=3000)
    process_role: str = Field(min_length=1, max_length=120)
    model_id: Literal["local-simulated"] = "local-simulated"
    instructions: str = Field(min_length=1, max_length=6000)
    system_prompt: str = Field(min_length=1, max_length=12000)
    decision_criteria: str = Field(min_length=1, max_length=6000)
    safety_rules: str = Field(min_length=1, max_length=6000)
    human_handoff: str = Field(min_length=1, max_length=3000)
    temperature: float = Field(default=0.2, ge=0, le=1.5)
    max_output_tokens: int = Field(default=512, ge=1, le=4096)
    max_cost_usd: Decimal = Field(default=Decimal("0"), ge=0, le=10)
    knowledge_requires_approval: bool = True


class AIAgentPublicationAction(BaseModel):
    action: Literal["approve", "publish", "unpublish"]


class AIAgentActivationUpdate(BaseModel):
    is_active: bool


KarenScenarioKey = Literal[
    "no_interest",
    "incorrect_disqualification",
    "resume_negotiation",
    "proposal_questions",
    "unauthorized_discount",
    "human_service",
    "contact_refusal",
    "accepts_proposal",
    "awaiting_signature",
    "contract_signed",
]

KarenAction = Literal[
    "confirm_contact",
    "confirm_commercial_status",
    "confirm_interest",
    "start_qualification",
    "prepare_proposal",
    "approve_proposal",
    "start_negotiation",
    "request_documents",
    "prepare_contract",
    "create_contract_link",
    "confirm_contract_signed",
    "start_post_sale",
    "record_no_interest",
    "transfer_human",
    "opt_out",
    "block",
    "suspend",
    "resume",
]


class KarenSimulationCreateRequest(BaseModel):
    scenario_key: KarenScenarioKey


class KarenSimulationTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def reject_personal_contact_data(cls, value: str) -> str:
        return _validate_synthetic_text(value) or ""


class KarenSimulationActionRequest(BaseModel):
    action: KarenAction
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def reject_personal_contact_data(cls, value: str | None) -> str | None:
        return _validate_synthetic_text(value)


class KarenSimulationApprovalRequest(BaseModel):
    action: Literal[
        "confirm_contact",
        "prepare_proposal",
        "approve_proposal",
        "prepare_contract",
        "create_contract_link",
        "confirm_contract_signed",
    ]
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def reject_personal_contact_data(cls, value: str | None) -> str | None:
        return _validate_synthetic_text(value)


KnowledgeCategory = Literal[
    "text",
    "faq",
    "policy",
    "product",
    "service",
    "objection",
    "approved_answer",
    "document",
]


class KnowledgeContentWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    category: KnowledgeCategory
    body: str = Field(min_length=1, max_length=500_000)
    origin: str = Field(min_length=1, max_length=300)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    agent_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def validate_validity_window(self):
        if any(
            value is not None and value.utcoffset() is None
            for value in (self.valid_from, self.valid_until)
        ):
            raise ValueError("Datas de validade precisam incluir fuso horário.")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until precisa ser posterior a valid_from.")
        if len(set(self.agent_ids)) != len(self.agent_ids):
            raise ValueError("agent_ids não pode conter duplicatas.")
        return self


class KnowledgeAgentIdsUpdate(BaseModel):
    agent_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def reject_duplicate_agents(self):
        if len(set(self.agent_ids)) != len(self.agent_ids):
            raise ValueError("agent_ids não pode conter duplicatas.")
        return self


class KnowledgeContentAction(BaseModel):
    action: Literal["approve", "archive", "restore"]


class KnowledgeRetrieveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=1000)
    agent_id: str | None = Field(default=None, max_length=36)
    top_k: int = Field(default=5, ge=1, le=10)


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
