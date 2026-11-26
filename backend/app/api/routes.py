from datetime import datetime
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.auth import Principal, get_firebase_admin_app, require_roles
from backend.app.classification import audit_required
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.importer import ImportLimitExceeded, parse_file, validate_rows
from backend.app.models import (
    AuditQueueItem,
    ContactQueueItem,
    ContactPermission,
    DisqualificationReason,
    ImportBatch,
    Lead,
    LeadStatusHistory,
    LossReason,
    ProcessingLog,
)
from backend.app.schemas import (
    ImportConfirmResponse,
    ImportPreviewResponse,
    LeadResponse,
    QueueSummary,
    AdminUserRoleUpdate,
)
from backend.app.services.vertex_audit import VertexAuditNotConfigured

router = APIRouter()
logger = logging.getLogger(__name__)


def _record_log(
    db: Session, batch_id: str, level: str, event: str, message: str, details: dict | None = None
) -> None:
    db.add(
        ProcessingLog(
            import_batch_id=batch_id,
            level=level,
            event=event,
            message=message,
            details_json=details or {},
        )
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "lead-intelligence-ai-api"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.error("API readiness check failed (%s).", type(exc).__name__)
        raise HTTPException(503, "Service dependencies are unavailable.") from exc
    return {"status": "ready", "service": "lead-intelligence-ai-api"}


@router.post("/imports/preview", response_model=ImportPreviewResponse)
async def preview_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    settings = get_settings()
    filename = file.filename or "upload"
    if not filename.lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(415, "Envie um arquivo CSV ou XLSX.")
    content = await file.read(settings.max_import_file_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_import_file_mb * 1024 * 1024:
        raise HTTPException(413, "Arquivo acima do limite configurado.")
    try:
        parsed = parse_file(
            filename,
            content,
            max_rows=settings.max_import_rows,
        )
        checked = validate_rows(parsed.rows, parsed.mapping)
    except ImportLimitExceeded as exc:
        raise HTTPException(413, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    external_ids = {
        row["values"]["external_id"]
        for row in checked
        if row["values"]["external_id"]
    }
    emails = {
        row["values"]["email_normalized"]
        for row in checked
        if row["values"]["email_normalized"]
    }
    phones = {
        row["values"]["phone_normalized"]
        for row in checked
        if row["values"]["phone_normalized"]
    }
    duplicate_keys: set[tuple[str, str]] = set()
    existing_conditions = []
    if external_ids:
        existing_conditions.append(Lead.external_id.in_(external_ids))
    if emails:
        existing_conditions.append(Lead.email_normalized.in_(emails))
    if phones:
        existing_conditions.append(Lead.phone_normalized.in_(phones))
    if existing_conditions:
        existing_leads = db.execute(
            select(Lead.external_id, Lead.email_normalized, Lead.phone_normalized).where(
                or_(*existing_conditions),
                Lead.tenant_id == principal.tenant_id,
            )
        ).all()
        for external_id, email, phone in existing_leads:
            if external_id:
                duplicate_keys.add(("id", external_id.casefold()))
            if email:
                duplicate_keys.add(("email", email.casefold()))
            if phone:
                duplicate_keys.add(("phone", phone))
    for row in checked:
        values = row["values"]
        row["duplicate_in_database"] = any(
            key in duplicate_keys
            for key in (
                ("id", values["external_id"].casefold()) if values["external_id"] else None,
                ("email", values["email_normalized"]) if values["email_normalized"] else None,
                ("phone", values["phone_normalized"]) if values["phone_normalized"] else None,
            )
            if key is not None
        )

    errors = sum(bool(row["errors"]) for row in checked)
    warnings = sum(bool(row["warnings"]) for row in checked)
    duplicates = sum(
        row["duplicate_in_file"] or row["duplicate_in_database"] for row in checked
    )
    batch = ImportBatch(
        tenant_id=principal.tenant_id,
        filename=filename[:255],
        file_type=filename.rsplit(".", 1)[-1].lower(),
        mapping=parsed.mapping,
        records_json=checked,
        total_rows=len(checked),
        duplicate_rows=duplicates,
        error_rows=errors,
        warning_rows=warnings,
        errors_json=[
            {"row_number": row["row_number"], "errors": row["errors"]}
            for row in checked
            if row["errors"]
        ],
    )
    db.add(batch)
    db.flush()
    _record_log(db, batch.id, "info", "preview_created", "Import preview created.")
    db.commit()
    return ImportPreviewResponse(
        import_id=batch.id,
        filename=batch.filename,
        mapping=batch.mapping,
        total_rows=batch.total_rows,
        valid_rows=batch.total_rows - errors,
        duplicate_rows=duplicates,
        error_rows=errors,
        warning_rows=warnings,
        preview=checked[:25],
    )


@router.post("/imports/{import_id}/confirm", response_model=ImportConfirmResponse)
def confirm_import(
    import_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    batch = db.scalar(
        select(ImportBatch).where(
            ImportBatch.id == import_id,
            ImportBatch.tenant_id == principal.tenant_id,
        )
    )
    if batch is None:
        raise HTTPException(404, "Importação não encontrada.")
    if batch.status != "preview":
        raise HTTPException(409, "Esta importação já foi processada.")
    imported = duplicates = 0
    try:
        loss_reasons = set(db.scalars(select(LossReason.name)).all())
        disqualification_reasons = set(db.scalars(select(DisqualificationReason.name)).all())
        for row in batch.records_json:
            if row["errors"]:
                continue
            values = row["values"]
            if row["duplicate_in_file"]:
                duplicates += 1
                continue
            lead = None
            if values["external_id"]:
                lead = db.scalar(
                    select(Lead).where(
                        Lead.external_id == values["external_id"],
                        Lead.tenant_id == principal.tenant_id,
                    )
                )
            if lead is None and values["email_normalized"]:
                lead = db.scalar(
                    select(Lead).where(
                        Lead.email_normalized == values["email_normalized"],
                        Lead.tenant_id == principal.tenant_id,
                    )
                )
            if lead is None and values["phone_normalized"]:
                lead = db.scalar(
                    select(Lead).where(
                        Lead.phone_normalized == values["phone_normalized"],
                        Lead.tenant_id == principal.tenant_id,
                    )
                )
            if lead is not None:
                duplicates += 1
                continue

            lead_values = dict(values)
            if lead_values["crm_created_at"]:
                lead_values["crm_created_at"] = datetime.fromisoformat(
                    lead_values["crm_created_at"]
                )
            if lead_values["monthly_account_value"]:
                lead_values["monthly_account_value"] = Decimal(
                    lead_values["monthly_account_value"]
                )
            lead = Lead(
                **lead_values,
                import_batch_id=batch.id,
                tenant_id=principal.tenant_id,
            )
            db.add(lead)
            db.flush()
            if lead.loss_reason and lead.loss_reason not in loss_reasons:
                db.add(LossReason(name=lead.loss_reason))
                loss_reasons.add(lead.loss_reason)
            if (
                lead.disqualification_reason
                and lead.disqualification_reason not in disqualification_reasons
            ):
                db.add(DisqualificationReason(name=lead.disqualification_reason))
                disqualification_reasons.add(lead.disqualification_reason)
            db.add(
                LeadStatusHistory(
                    lead_id=lead.id,
                    current_status=lead.status,
                    current_phase=lead.phase,
                    origin="import",
                )
            )
            if audit_required(lead.classification):
                db.add(AuditQueueItem(lead_id=lead.id))
            if lead.classification in {
                "research",
                "connecting",
                "hand_raised",
                "nurture",
                "commercial_negotiation",
                "qualified_lost",
            }:
                db.add(ContactQueueItem(lead_id=lead.id, status="draft_needs_review"))
            imported += 1

        batch.imported_rows = imported
        batch.duplicate_rows = duplicates
        batch.status = "completed"
        _record_log(
            db,
            batch.id,
            "info",
            "import_confirmed",
            "Import confirmed; contact actions remain manual and disabled.",
            {"imported_rows": imported, "duplicate_rows": duplicates},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ImportConfirmResponse(
        import_id=batch.id,
        status=batch.status,
        imported_rows=imported,
        duplicate_rows=duplicates,
        error_rows=batch.error_rows,
    )


@router.get("/imports")
def list_imports(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    batches = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == principal.tenant_id)
        .order_by(ImportBatch.created_at.desc())
    ).all()
    return [
        {
            "id": batch.id,
            "filename": batch.filename,
            "status": batch.status,
            "total_rows": batch.total_rows,
            "imported_rows": batch.imported_rows,
            "duplicate_rows": batch.duplicate_rows,
            "error_rows": batch.error_rows,
            "created_at": batch.created_at,
        }
        for batch in batches
    ]


@router.get("/leads", response_model=list[LeadResponse])
def list_leads(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    if not 1 <= limit <= 500:
        raise HTTPException(422, "limit deve estar entre 1 e 500.")
    return db.scalars(
        select(Lead)
        .where(Lead.tenant_id == principal.tenant_id)
        .order_by(Lead.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead(
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
    return lead


@router.get("/leads/{lead_id}/detail")
def get_lead_detail(
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
    history = db.scalars(
        select(LeadStatusHistory)
        .where(LeadStatusHistory.lead_id == lead_id)
        .order_by(LeadStatusHistory.changed_at.desc())
    ).all()
    permission = db.scalar(
        select(ContactPermission).where(ContactPermission.lead_id == lead_id)
    )
    return {
        "lead": lead,
        "status_history": history,
        "contact_permission": (
            {
                "channel": permission.channel,
                "consent_status": permission.consent_status,
                "suppression_reason": permission.suppression_reason,
            }
            if permission
            else None
        ),
    }


@router.get("/queues/summary", response_model=QueueSummary)
def queue_summary(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("gestor")),
):
    return _queue_summary(db, principal.tenant_id)


def _queue_summary(db: Session, tenant_id: str) -> QueueSummary:
    return QueueSummary(
        audit_pending=db.scalar(
            select(func.count())
            .select_from(AuditQueueItem)
            .join(Lead, Lead.id == AuditQueueItem.lead_id)
            .where(
                AuditQueueItem.status == "pending",
                Lead.tenant_id == tenant_id,
            )
        )
        or 0,
        contact_drafts=db.scalar(
            select(func.count())
            .select_from(ContactQueueItem)
            .join(Lead, Lead.id == ContactQueueItem.lead_id)
            .where(Lead.tenant_id == tenant_id)
        )
        or 0,
        contact_eligible=db.scalar(
            select(func.count())
            .select_from(ContactQueueItem)
            .join(Lead, Lead.id == ContactQueueItem.lead_id)
            .where(
                ContactQueueItem.eligible.is_(True),
                Lead.tenant_id == tenant_id,
            )
        )
        or 0,
    )


@router.get("/queues/audit")
def audit_queue(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    rows = db.execute(
        select(AuditQueueItem, Lead)
        .join(Lead, Lead.id == AuditQueueItem.lead_id)
        .where(
            AuditQueueItem.status == "pending",
            Lead.tenant_id == principal.tenant_id,
        )
        .order_by(AuditQueueItem.created_at.desc())
        .limit(500)
    ).all()
    return [{"queue_id": item.id, "status": item.status, "lead": lead} for item, lead in rows]


@router.get("/queues/contact")
def contact_queue(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    rows = db.execute(
        select(ContactQueueItem, Lead)
        .join(Lead, Lead.id == ContactQueueItem.lead_id)
        .where(Lead.tenant_id == principal.tenant_id)
        .order_by(ContactQueueItem.created_at.desc())
        .limit(500)
    ).all()
    return [
        {
            "queue_id": item.id,
            "status": item.status,
            "eligible": item.eligible,
            "lead": lead,
            "outbound_enabled": False,
        }
        for item, lead in rows
    ]


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("gestor", "admin")),
):
    classifications = dict(
        db.execute(
            select(Lead.classification, func.count())
            .where(Lead.tenant_id == principal.tenant_id)
            .group_by(Lead.classification)
        ).all()
    )
    recent_imports = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == principal.tenant_id)
        .order_by(ImportBatch.created_at.desc())
        .limit(5)
    ).all()
    return {
        "total_leads": db.scalar(
            select(func.count()).select_from(Lead).where(Lead.tenant_id == principal.tenant_id)
        )
        or 0,
        "classifications": classifications,
        "queues": _queue_summary(db, principal.tenant_id),
        "recent_imports": [
            {
                "id": item.id,
                "filename": item.filename,
                "status": item.status,
                "total_rows": item.total_rows,
                "imported_rows": item.imported_rows,
                "created_at": item.created_at,
            }
            for item in recent_imports
        ],
    }


@router.get("/reasons")
def list_reasons(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("auditor")),
):
    return {
        "loss": [
            {"id": item.id, "name": item.name}
            for item in db.scalars(
                select(LossReason)
                .join(Lead, Lead.loss_reason == LossReason.name)
                .where(
                    LossReason.active.is_(True),
                    Lead.tenant_id == principal.tenant_id,
                )
                .distinct()
            ).all()
        ],
        "disqualification": [
            {"id": item.id, "name": item.name}
            for item in db.scalars(
                select(DisqualificationReason)
                .join(Lead, Lead.disqualification_reason == DisqualificationReason.name)
                .where(
                    DisqualificationReason.active.is_(True),
                    Lead.tenant_id == principal.tenant_id,
                )
                .distinct()
            ).all()
        ],
    }


@router.get("/admin/users")
def list_admin_users(
    page_token: str | None = None,
    principal: Principal = Depends(require_roles("admin")),
):
    if not get_settings().firebase_admin_user_management_enabled:
        raise HTTPException(503, "Firebase user management is disabled in this deployment.")
    app = get_firebase_admin_app()
    try:
        page = firebase_auth.list_users(
            app=app,
            max_results=1000,
            page_token=page_token,
        )
    except firebase_exceptions.FirebaseError as exc:
        logger.error("Firebase user listing failed (%s).", type(exc).__name__)
        raise HTTPException(
            503, "Firebase user management is temporarily unavailable."
        ) from exc
    users = [
        {
            "uid": user.uid,
            "email": user.email,
            "display_name": user.display_name,
            "role": (user.custom_claims or {}).get("role"),
        }
        for user in page.users
        if (user.custom_claims or {}).get("tenant_id") == principal.tenant_id
    ]
    return {"users": users, "next_page_token": page.next_page_token}


@router.put("/admin/users/{uid}/role")
def update_user_role(
    uid: str,
    request: AdminUserRoleUpdate,
    principal: Principal = Depends(require_roles("admin")),
):
    if uid == principal.uid:
        raise HTTPException(409, "Administrators cannot change their own access role.")
    if not get_settings().firebase_admin_user_management_enabled:
        raise HTTPException(503, "Firebase user management is disabled in this deployment.")
    app = get_firebase_admin_app()
    try:
        user = firebase_auth.get_user(uid, app=app)
        claims = dict(user.custom_claims or {})
        existing_tenant = claims.get("tenant_id")
        if existing_tenant and existing_tenant != principal.tenant_id:
            raise HTTPException(404, "User not found in this organization.")
        claims.update(role=request.role, tenant_id=principal.tenant_id)
        firebase_auth.set_custom_user_claims(uid, claims, app=app)
    except firebase_exceptions.FirebaseError as exc:
        if isinstance(exc, firebase_auth.UserNotFoundError):
            raise HTTPException(404, "User not found.") from exc
        logger.error("Firebase user role update failed (%s).", type(exc).__name__)
        raise HTTPException(
            503, "Firebase user management is temporarily unavailable."
        ) from exc
    return {
        "uid": uid,
        "role": request.role,
        "tenant_id": principal.tenant_id,
        "token_refresh_required": True,
    }
