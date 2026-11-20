import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.auth import Principal, require_roles
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.models import (
    AIAgent,
    KnowledgeAgentLink,
    KnowledgeContent,
    KnowledgeContentVersion,
)
from backend.app.schemas import (
    KnowledgeAgentIdsUpdate,
    KnowledgeCategory,
    KnowledgeContentAction,
    KnowledgeContentWrite,
    KnowledgeRetrieveRequest,
)
from backend.app.services.knowledge_index import excerpt_for, local_lexical_indexer
from backend.app.services.knowledge_retrieval import retrieve_knowledge
from backend.app.services.knowledge_storage import extract_document_text

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


def _get_content(db: Session, content_id: str, tenant_id: str) -> KnowledgeContent:
    content = db.scalar(
        select(KnowledgeContent).where(
            KnowledgeContent.id == content_id,
            KnowledgeContent.tenant_id == tenant_id,
        )
    )
    if content is None:
        raise HTTPException(404, "Conteúdo não encontrado nesta organização.")
    return content


def _linked_agent_ids(db: Session, content_id: str, tenant_id: str) -> list[str]:
    return db.scalars(
        select(KnowledgeAgentLink.agent_id)
        .where(
            KnowledgeAgentLink.content_id == content_id,
            KnowledgeAgentLink.tenant_id == tenant_id,
        )
        .order_by(KnowledgeAgentLink.agent_id)
    ).all()


def _snapshot(content: KnowledgeContent, agent_ids: list[str]) -> dict:
    return {
        "title": content.title,
        "category": content.category,
        "body": content.body,
        "origin": content.origin,
        "source_type": content.source_type,
        "source_name": content.source_name,
        "source_sha256": content.source_sha256,
        "valid_from": content.valid_from.isoformat() if content.valid_from else None,
        "valid_until": content.valid_until.isoformat() if content.valid_until else None,
        "status": content.status,
        "agent_ids": agent_ids,
    }


def _record_version(db: Session, content: KnowledgeContent, actor_uid: str) -> None:
    db.add(
        KnowledgeContentVersion(
            tenant_id=content.tenant_id,
            content_id=content.id,
            version_number=content.current_version,
            snapshot_json=_snapshot(
                content,
                _linked_agent_ids(db, content.id, content.tenant_id),
            ),
            created_by_uid=actor_uid,
        )
    )


def _set_agent_links(
    db: Session,
    content: KnowledgeContent,
    agent_ids: list[str],
    actor_uid: str,
) -> None:
    requested = set(agent_ids)
    if requested:
        owned_ids = set(
            db.scalars(
                select(AIAgent.id).where(
                    AIAgent.tenant_id == content.tenant_id,
                    AIAgent.id.in_(requested),
                )
            ).all()
        )
        if owned_ids != requested:
            raise HTTPException(404, "Um ou mais agentes não pertencem a esta organização.")

    db.execute(
        delete(KnowledgeAgentLink).where(
            KnowledgeAgentLink.tenant_id == content.tenant_id,
            KnowledgeAgentLink.content_id == content.id,
        )
    )
    db.add_all(
        KnowledgeAgentLink(
            tenant_id=content.tenant_id,
            agent_id=agent_id,
            content_id=content.id,
            created_by_uid=actor_uid,
        )
        for agent_id in sorted(requested)
    )
    db.flush()


def _serialize(
    content: KnowledgeContent,
    agent_ids: list[str],
    score: float | None = None,
    excerpt: str | None = None,
) -> dict:
    return {
        "id": content.id,
        "title": content.title,
        "category": content.category,
        "body": content.body,
        "origin": content.origin,
        "source_type": content.source_type,
        "source_name": content.source_name,
        "source_sha256": content.source_sha256,
        "valid_from": content.valid_from,
        "valid_until": content.valid_until,
        "status": content.status,
        "current_version": content.current_version,
        "created_by_uid": content.created_by_uid,
        "approved_by_uid": content.approved_by_uid,
        "approved_at": content.approved_at,
        "archived_at": content.archived_at,
        "created_at": content.created_at,
        "updated_at": content.updated_at,
        "agent_ids": agent_ids,
        "score": score,
        "excerpt": excerpt,
    }


def _create_content(
    db: Session,
    request: KnowledgeContentWrite,
    principal: Principal,
    source_type: str = "text",
    source_name: str | None = None,
    source_sha256: str | None = None,
) -> KnowledgeContent:
    values = request.model_dump(exclude={"agent_ids"})
    content = KnowledgeContent(
        **values,
        tenant_id=principal.tenant_id,
        source_type=source_type,
        source_name=source_name,
        source_sha256=source_sha256,
        status="draft",
        current_version=1,
        created_by_uid=principal.uid,
    )
    db.add(content)
    db.flush()
    _set_agent_links(db, content, request.agent_ids, principal.uid)
    _record_version(db, content, principal.uid)
    db.commit()
    db.refresh(content)
    return content


@router.get("/contents")
def list_contents(
    q: str | None = None,
    category: KnowledgeCategory | None = None,
    status: str | None = None,
    agent_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit precisa estar entre 1 e 200.")
    if status is not None and status not in {"draft", "approved", "archived"}:
        raise HTTPException(422, "Estado de conteúdo inválido.")
    statement = select(KnowledgeContent).where(
        KnowledgeContent.tenant_id == principal.tenant_id
    )
    if category:
        statement = statement.where(KnowledgeContent.category == category)
    if status:
        statement = statement.where(KnowledgeContent.status == status)
    if agent_id:
        agent = db.scalar(
            select(AIAgent.id).where(
                AIAgent.id == agent_id,
                AIAgent.tenant_id == principal.tenant_id,
            )
        )
        if agent is None:
            raise HTTPException(404, "Agente não encontrado nesta organização.")
        statement = statement.join(
            KnowledgeAgentLink,
            (KnowledgeAgentLink.content_id == KnowledgeContent.id)
            & (KnowledgeAgentLink.tenant_id == KnowledgeContent.tenant_id),
        ).where(
            KnowledgeAgentLink.tenant_id == principal.tenant_id,
            KnowledgeAgentLink.agent_id == agent_id,
        )
    term = (q or "").strip()
    if term:
        contents = db.scalars(
            statement.order_by(KnowledgeContent.updated_at.desc())
        ).all()
        results = local_lexical_indexer.rank(term, contents, limit)
    else:
        contents = db.scalars(
            statement.order_by(KnowledgeContent.updated_at.desc()).limit(limit)
        ).all()
        results = [(None, content) for content in contents]
    return [
        _serialize(
            content,
            _linked_agent_ids(db, content.id, principal.tenant_id),
            score=score,
            excerpt=excerpt_for(term, content.title + "\n" + content.body) if term else None,
        )
        for score, content in results
    ]


@router.post("/contents")
def create_content(
    request: KnowledgeContentWrite,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    content = _create_content(db, request, principal)
    return _serialize(content, _linked_agent_ids(db, content.id, principal.tenant_id))


@router.post("/files")
async def upload_content_file(
    file: UploadFile = File(...),
    category: KnowledgeCategory = Form(...),
    origin: str = Form(min_length=1, max_length=300),
    title: str | None = Form(default=None, max_length=200),
    agent_ids: str = Form(default="[]"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    settings = get_settings()
    data = await file.read(settings.knowledge_max_file_mb * 1024 * 1024 + 1)
    await file.close()
    try:
        body, source_type, source_name, source_sha256 = extract_document_text(
            file.filename or "",
            data,
        )
        parsed_agent_ids = json.loads(agent_ids)
        if not isinstance(parsed_agent_ids, list) or not all(
            isinstance(agent_id, str) for agent_id in parsed_agent_ids
        ):
            raise ValueError("agent_ids precisa ser uma lista JSON de identificadores.")
        request = KnowledgeContentWrite(
            title=(title or source_name),
            category=category,
            body=body,
            origin=origin,
            agent_ids=parsed_agent_ids,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    content = _create_content(
        db,
        request,
        principal,
        source_type=source_type,
        source_name=source_name,
        source_sha256=source_sha256,
    )
    return _serialize(content, _linked_agent_ids(db, content.id, principal.tenant_id))


@router.get("/contents/{content_id}")
def get_content(
    content_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    content = _get_content(db, content_id, principal.tenant_id)
    return _serialize(content, _linked_agent_ids(db, content.id, principal.tenant_id))


@router.put("/contents/{content_id}")
def update_content(
    content_id: str,
    request: KnowledgeContentWrite,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    content = _get_content(db, content_id, principal.tenant_id)
    if content.status == "archived":
        raise HTTPException(409, "Restaure o conteúdo antes de editá-lo.")
    values = request.model_dump(exclude={"agent_ids"})
    for key, value in values.items():
        setattr(content, key, value)
    content.current_version += 1
    content.status = "draft"
    content.approved_by_uid = None
    content.approved_at = None
    _set_agent_links(db, content, request.agent_ids, principal.uid)
    _record_version(db, content, principal.uid)
    db.commit()
    db.refresh(content)
    return _serialize(content, _linked_agent_ids(db, content.id, principal.tenant_id))


@router.put("/contents/{content_id}/agents")
def update_content_agents(
    content_id: str,
    request: KnowledgeAgentIdsUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    content = _get_content(db, content_id, principal.tenant_id)
    if content.status == "archived":
        raise HTTPException(409, "Restaure o conteúdo antes de alterar suas associações.")
    _set_agent_links(db, content, request.agent_ids, principal.uid)
    content.current_version += 1
    content.status = "draft"
    content.approved_by_uid = None
    content.approved_at = None
    _record_version(db, content, principal.uid)
    db.commit()
    db.refresh(content)
    return _serialize(content, _linked_agent_ids(db, content.id, principal.tenant_id))


@router.post("/contents/{content_id}/state")
def update_content_state(
    content_id: str,
    request: KnowledgeContentAction,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    content = _get_content(db, content_id, principal.tenant_id)
    changed = False
    if request.action == "approve":
        if content.status == "archived":
            raise HTTPException(409, "Restaure o conteúdo antes de aprová-lo.")
        if content.status != "approved":
            content.status = "approved"
            content.approved_by_uid = principal.uid
            content.approved_at = datetime.now(timezone.utc)
            changed = True
    elif request.action == "archive":
        if content.status != "archived":
            content.status = "archived"
            content.archived_at = datetime.now(timezone.utc)
            changed = True
    else:
        if content.status != "archived":
            raise HTTPException(409, "Somente conteúdos arquivados podem ser restaurados.")
        content.status = "draft"
        content.archived_at = None
        content.approved_by_uid = None
        content.approved_at = None
        changed = True
    if changed:
        content.current_version += 1
        _record_version(db, content, principal.uid)
        db.commit()
        db.refresh(content)
    return _serialize(content, _linked_agent_ids(db, content.id, principal.tenant_id))


@router.get("/contents/{content_id}/versions")
def list_content_versions(
    content_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    _get_content(db, content_id, principal.tenant_id)
    versions = db.scalars(
        select(KnowledgeContentVersion)
        .where(
            KnowledgeContentVersion.content_id == content_id,
            KnowledgeContentVersion.tenant_id == principal.tenant_id,
        )
        .order_by(KnowledgeContentVersion.version_number.desc())
    ).all()
    return [
        {
            "version_number": version.version_number,
            "snapshot": version.snapshot_json,
            "created_by_uid": version.created_by_uid,
            "created_at": version.created_at,
        }
        for version in versions
    ]


@router.post("/retrieve")
def retrieve_content(
    request: KnowledgeRetrieveRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    return retrieve_knowledge(
        db,
        principal.tenant_id,
        request.query,
        request.agent_id,
        request.top_k,
    )
