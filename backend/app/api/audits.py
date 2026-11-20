from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import Principal, require_roles
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.models import Audit, Conversation, Evidence, Lead, Message
from backend.app.schemas import AuditReviewRequest, AuditRunRequest
from backend.app.services.conversation_history import utc_datetime
from backend.app.services.vertex_audit import (
    AuditExecutionError,
    AuditInput,
    AuditMessage,
    VertexAuditNotConfigured,
    VertexAuditService,
)

router = APIRouter()


@lru_cache(maxsize=1)
def _service() -> VertexAuditService:
    return VertexAuditService(get_settings())


def _audit_reason(lead: Lead) -> str:
    return lead.loss_reason or lead.disqualification_reason or lead.loss_reason_description or ""


def _context_for_lead(db: Session, lead_id: str) -> tuple[bool, list[Message]]:
    conversation_ids = db.scalars(
        select(Conversation.id).where(Conversation.lead_id == lead_id)
    ).all()
    if not conversation_ids:
        return False, []
    messages = db.scalars(
        select(Message)
        .where(
            Message.conversation_id.in_(conversation_ids),
            Message.authorized_for_audit.is_(True),
            Message.deleted_at.is_(None),
            Message.retention_until.is_not(None),
            Message.body != "",
        )
        .order_by(Message.sent_at.asc(), Message.id.asc())
    ).all()
    now = datetime.now(timezone.utc)
    eligible = [
        message
        for message in messages
        if utc_datetime(message.retention_until) > now
    ]
    return True, eligible


def _serialize_audit(db: Session, audit: Audit) -> dict:
    now = datetime.now(timezone.utc)
    evidence_items = []
    for evidence in db.scalars(
        select(Evidence).where(Evidence.audit_id == audit.id).order_by(Evidence.id)
    ).all():
        message = db.get(Message, evidence.message_id) if evidence.message_id else None
        valid = (
            evidence.verified
            and bool(evidence.excerpt)
            and message is not None
            and message.deleted_at is None
            and message.authorized_for_audit
            and message.retention_until is not None
            and utc_datetime(message.retention_until) > now
            and (
                evidence.retention_until is None
                or utc_datetime(evidence.retention_until) > now
            )
        )
        evidence_items.append(
            {
                "id": evidence.id,
                "message_id": evidence.message_id,
                "source_id": evidence.source_id if valid else None,
                "excerpt": evidence.excerpt if valid else None,
                "referenced_at": evidence.referenced_at,
                "verified": bool(valid),
            }
        )
    return {
        "id": audit.id,
        "lead_id": audit.lead_id,
        "execution_mode": audit.execution_mode,
        "model": audit.model,
        "model_version": audit.model_version,
        "prompt_version": audit.prompt_version,
        "status": audit.status,
        "classification": audit.classification,
        "original_reason": audit.original_reason,
        "justification": audit.justification,
        "limitations": audit.limitations_json or [],
        "alternative_reason": audit.alternative_reason,
        "requires_human_review": audit.requires_human_review,
        "estimated_cost_usd": audit.estimated_cost_usd,
        "input_tokens": audit.input_tokens,
        "output_tokens": audit.output_tokens,
        "reprocess_of_id": audit.reprocess_of_id,
        "review_status": audit.review_status,
        "review_notes": audit.review_notes,
        "reviewed_at": audit.reviewed_at,
        "created_at": audit.created_at,
        "finished_at": audit.finished_at,
        "error_message": audit.error_message,
        "evidence": evidence_items,
    }


async def _run_and_persist(
    db: Session,
    lead: Lead,
    mode: str,
    reprocess_of: str | None = None,
) -> dict:
    history_available, messages = _context_for_lead(db, lead.id)
    settings = get_settings()
    audit = Audit(
        lead_id=lead.id,
        execution_mode=mode,
        model=settings.vertex_ai_model if mode == "vertex" else None,
        prompt_version=settings.vertex_ai_prompt_version,
        original_reason=_audit_reason(lead),
        reprocess_of_id=reprocess_of,
        status="pending",
    )
    db.add(audit)
    db.flush()
    request = AuditInput(
        lead_id=lead.id,
        original_reason=audit.original_reason,
        history_available=history_available,
        messages=[
            AuditMessage(
                id=message.id,
                provider_message_id=message.provider_message_id,
                body=message.body,
                sent_at=message.sent_at,
                edited_at=message.edited_at,
            )
            for message in messages
        ],
    )
    try:
        outcome = (await _service().run_batch([request], mode=mode))[0]
    except VertexAuditNotConfigured as exc:
        audit.status = "blocked"
        audit.error_message = str(exc)
        audit.justification = "A execução real foi bloqueada pela configuração segura."
    except AuditExecutionError as exc:
        audit.status = "failed"
        audit.error_message = str(exc)
        audit.justification = "A auditoria não foi concluída; requer revisão humana."
    except ValueError as exc:
        audit.status = "failed"
        audit.error_message = str(exc)
        audit.justification = "A auditoria excedeu os limites configurados."
    else:
        audit.status = "completed"
        audit.provider = outcome.provider
        audit.model = outcome.model
        audit.model_version = outcome.model_version
        audit.prompt_version = outcome.prompt_version
        audit.classification = outcome.classification
        audit.justification = outcome.justification
        audit.limitations_json = outcome.limitations
        audit.alternative_reason = outcome.alternative_reason
        audit.requires_human_review = outcome.requires_human_review
        audit.estimated_cost_usd = outcome.estimated_cost_usd
        audit.input_tokens = outcome.input_tokens
        audit.output_tokens = outcome.output_tokens
        audit.request_hash = outcome.request_hash
        audit.result_json = {
            "evidence_count": len(outcome.evidence),
            "history_message_count": len(messages),
        }
        message_by_id = {message.id: message for message in messages}
        for item in outcome.evidence:
            source = message_by_id[item.message_id]
            db.add(
                Evidence(
                    audit_id=audit.id,
                    message_id=source.id,
                    source_type="message",
                    source_id=item.source_id or source.id,
                    excerpt=item.excerpt,
                    referenced_at=item.referenced_at,
                    verified=True,
                    retention_until=source.retention_until,
                )
            )
    audit.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(audit)
    return _serialize_audit(db, audit)


@router.get("/leads/{lead_id}/audit-context")
def get_audit_context(
    lead_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    lead = db.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
        )
    )
    if lead is None:
        raise HTTPException(404, "Lead não encontrado.")
    available, messages = _context_for_lead(db, lead_id)
    return {
        "history_available": available,
        "messages": [
            {
                "id": message.id,
                "sent_at": message.sent_at,
                "direction": message.direction,
                "message_type": message.message_type,
                "body": message.body,
                "capture_source": message.capture_source,
            }
            for message in messages
        ],
    }


@router.get("/leads/{lead_id}/audits")
def list_lead_audits(
    lead_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    if db.scalar(
        select(Lead.id).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
        )
    ) is None:
        raise HTTPException(404, "Lead não encontrado.")
    audits = db.scalars(
        select(Audit).where(Audit.lead_id == lead_id).order_by(Audit.created_at.desc())
    ).all()
    return [_serialize_audit(db, audit) for audit in audits]


@router.post("/leads/{lead_id}/audits")
async def create_lead_audit(
    lead_id: str,
    request: AuditRunRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    lead = db.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
        )
    )
    if lead is None:
        raise HTTPException(404, "Lead não encontrado.")
    return await _run_and_persist(db, lead, request.mode)


@router.post("/audits/{audit_id}/reprocess")
async def reprocess_audit(
    audit_id: str,
    request: AuditRunRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    previous = db.scalar(
        select(Audit)
        .join(Lead, Lead.id == Audit.lead_id)
        .where(
            Audit.id == audit_id,
            Lead.tenant_id == principal.tenant_id,
        )
    )
    if previous is None:
        raise HTTPException(404, "Auditoria não encontrada.")
    lead = db.scalar(
        select(Lead).where(
            Lead.id == previous.lead_id,
            Lead.tenant_id == principal.tenant_id,
        )
    )
    if lead is None:
        raise HTTPException(404, "Lead não encontrado.")
    return await _run_and_persist(db, lead, request.mode, reprocess_of=previous.id)


@router.post("/audits/{audit_id}/review")
def review_audit(
    audit_id: str,
    request: AuditReviewRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    audit = db.scalar(
        select(Audit)
        .join(Lead, Lead.id == Audit.lead_id)
        .where(
            Audit.id == audit_id,
            Lead.tenant_id == principal.tenant_id,
        )
    )
    if audit is None:
        raise HTTPException(404, "Auditoria não encontrada.")
    audit.review_status = request.decision
    audit.review_notes = request.notes
    audit.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(audit)
    return _serialize_audit(db, audit)
