from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth import Principal, require_roles
from backend.app.db import get_db
from backend.app.models import (
    AIAgent,
    AIAgentVersion,
    KnowledgeAgentLink,
    KnowledgeContent,
)
from backend.app.schemas import (
    AIAgentActivationUpdate,
    AIAgentPublicationAction,
    AIAgentWrite,
)

router = APIRouter(prefix="/studio/agents", tags=["AI Studio"])


def _snapshot(agent: AIAgent, values: dict | None = None) -> dict:
    data = values or {
        "name": agent.name,
        "purpose": agent.purpose,
        "description": agent.description,
        "process_role": agent.process_role,
        "model_id": agent.model_id,
        "instructions": agent.instructions,
        "system_prompt": agent.system_prompt,
        "decision_criteria": agent.decision_criteria,
        "safety_rules": agent.safety_rules,
        "human_handoff": agent.human_handoff,
        "temperature": agent.temperature,
        "max_output_tokens": agent.max_output_tokens,
        "max_cost_usd": agent.max_cost_usd,
    }
    return {
        **data,
        "max_cost_usd": str(data["max_cost_usd"]),
    }


def _serialize(agent: AIAgent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "purpose": agent.purpose,
        "description": agent.description,
        "process_role": agent.process_role,
        "model_id": agent.model_id,
        "instructions": agent.instructions,
        "system_prompt": agent.system_prompt,
        "decision_criteria": agent.decision_criteria,
        "safety_rules": agent.safety_rules,
        "human_handoff": agent.human_handoff,
        "temperature": agent.temperature,
        "max_output_tokens": agent.max_output_tokens,
        "max_cost_usd": float(agent.max_cost_usd),
        "knowledge_requires_approval": agent.knowledge_requires_approval,
        "publication_state": agent.publication_state,
        "is_active": agent.is_active,
        "execution_enabled": False,
        "current_version": agent.current_version,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "approved_by_uid": agent.approved_by_uid,
        "approved_at": agent.approved_at,
    }


def _get_agent(db: Session, agent_id: str, tenant_id: str) -> AIAgent:
    agent = db.scalar(
        select(AIAgent).where(AIAgent.id == agent_id, AIAgent.tenant_id == tenant_id)
    )
    if agent is None:
        raise HTTPException(404, "Agente não encontrado nesta organização.")
    return agent


def _add_version(db: Session, agent: AIAgent, actor_uid: str, values: dict | None = None) -> None:
    db.add(
        AIAgentVersion(
            agent_id=agent.id,
            tenant_id=agent.tenant_id,
            version_number=agent.current_version,
            snapshot_json=_snapshot(agent, values),
            created_by_uid=actor_uid,
        )
    )


def _template_values(template_key: str) -> dict:
    if template_key == "loss-reason-auditor":
        return {
            "name": "Auditor de Motivos de Perda",
            "purpose": "Revisar a consistência de motivos de perda com evidências disponíveis.",
            "description": "Modelo inicial para revisão humana de motivos comerciais.",
            "process_role": "auditoria_comercial",
            "model_id": "local-simulated",
            "instructions": "Analise somente os dados fornecidos e sinalize lacunas de evidência.",
            "system_prompt": (
                "Você apoia uma auditoria comercial em modo simulado. Não invente fatos, "
                "não use dados externos e encaminhe conclusões incertas para revisão humana."
            ),
            "decision_criteria": (
                "Classifique como sustentado, divergente ou inconclusivo; toda conclusão "
                "deve citar evidência fornecida."
            ),
            "safety_rules": (
                "Não contate pessoas, não revele dados pessoais e não faça chamadas a modelos "
                "externos nesta versão."
            ),
            "human_handoff": "Encaminhe casos sem evidência suficiente ou com conflito de informações.",
            "temperature": 0.1,
            "max_output_tokens": 512,
            "max_cost_usd": Decimal("0"),
            "knowledge_requires_approval": True,
        }
    return {
        "name": "Agente de Recuperação de Leads",
        "purpose": "Apoiar a elaboração revisada de próximos passos para oportunidades.",
        "description": "Modelo inicial de planejamento, sem contato ou execução automática.",
        "process_role": "recuperacao_de_oportunidades",
        "model_id": "local-simulated",
        "instructions": "Sugira próximos passos apenas como rascunho para aprovação humana.",
        "system_prompt": (
            "Você auxilia no planejamento de recuperação em modo simulado. Não envie "
            "mensagens, não acesse números reais e não presuma consentimento."
        ),
        "decision_criteria": (
            "Baseie cada sugestão no contexto fornecido e identifique quando faltam dados."
        ),
        "safety_rules": (
            "Nenhum contato externo, inferência paga ou alteração automática de dados é permitido."
        ),
        "human_handoff": (
            "Solicite revisão humana antes de qualquer plano que envolva contato ou decisão comercial."
        ),
        "temperature": 0.2,
        "max_output_tokens": 512,
        "max_cost_usd": Decimal("0"),
        "knowledge_requires_approval": True,
    }


@router.get("")
def list_agents(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    agents = db.scalars(
        select(AIAgent)
        .where(AIAgent.tenant_id == principal.tenant_id)
        .order_by(AIAgent.created_at, AIAgent.name)
    ).all()
    return [_serialize(agent) for agent in agents]


@router.post("")
def create_agent(
    request: AIAgentWrite,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    values = request.model_dump()
    agent = AIAgent(
        **values,
        tenant_id=principal.tenant_id,
        created_by_uid=principal.uid,
        current_version=1,
        publication_state="draft",
        is_active=False,
    )
    db.add(agent)
    db.flush()
    _add_version(db, agent, principal.uid, values)
    db.commit()
    db.refresh(agent)
    return _serialize(agent)


@router.post("/initial-templates")
def create_initial_templates(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    templates = (
        ("loss-reason-auditor", "Auditor de Motivos de Perda"),
        ("lead-recovery-agent", "Agente de Recuperação de Leads"),
    )
    for template_key, _ in templates:
        existing = db.scalar(
            select(AIAgent).where(
                AIAgent.tenant_id == principal.tenant_id,
                AIAgent.template_key == template_key,
            )
        )
        if existing is not None:
            continue
        values = _template_values(template_key)
        agent = AIAgent(
            **values,
            tenant_id=principal.tenant_id,
            template_key=template_key,
            created_by_uid=principal.uid,
            current_version=1,
            publication_state="draft",
            is_active=False,
        )
        db.add(agent)
        db.flush()
        _add_version(db, agent, principal.uid, values)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, "Os modelos iniciais foram criados em outra operação; atualize a lista."
        ) from exc
    agents = db.scalars(
        select(AIAgent)
        .where(AIAgent.tenant_id == principal.tenant_id)
        .order_by(AIAgent.created_at, AIAgent.name)
    ).all()
    return [_serialize(agent) for agent in agents]


@router.get("/{agent_id}")
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    return _serialize(_get_agent(db, agent_id, principal.tenant_id))


@router.put("/{agent_id}")
def update_agent(
    agent_id: str,
    request: AIAgentWrite,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    agent = _get_agent(db, agent_id, principal.tenant_id)
    values = request.model_dump()
    for key, value in values.items():
        setattr(agent, key, value)
    agent.current_version += 1
    agent.publication_state = "draft"
    agent.is_active = False
    agent.approved_by_uid = None
    agent.approved_at = None
    _add_version(db, agent, principal.uid, values)
    db.commit()
    db.refresh(agent)
    return _serialize(agent)


@router.get("/{agent_id}/versions")
def list_agent_versions(
    agent_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    _get_agent(db, agent_id, principal.tenant_id)
    versions = db.scalars(
        select(AIAgentVersion)
        .where(
            AIAgentVersion.agent_id == agent_id,
            AIAgentVersion.tenant_id == principal.tenant_id,
        )
        .order_by(AIAgentVersion.version_number.desc())
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


@router.post("/{agent_id}/publication")
def update_publication(
    agent_id: str,
    request: AIAgentPublicationAction,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    agent = _get_agent(db, agent_id, principal.tenant_id)
    if request.action == "approve":
        if agent.publication_state != "draft":
            raise HTTPException(409, "Somente agentes em rascunho podem ser aprovados.")
        agent.publication_state = "approved"
        agent.approved_by_uid = principal.uid
        agent.approved_at = datetime.now(timezone.utc)
    elif request.action == "publish":
        if agent.publication_state != "approved" or not agent.approved_by_uid:
            raise HTTPException(409, "O agente precisa de aprovação humana antes da publicação.")
        if agent.knowledge_requires_approval:
            unapproved_content = db.scalar(
                select(KnowledgeContent.id)
                .join(
                    KnowledgeAgentLink,
                    (KnowledgeAgentLink.content_id == KnowledgeContent.id)
                    & (KnowledgeAgentLink.tenant_id == KnowledgeContent.tenant_id),
                )
                .where(
                    KnowledgeAgentLink.tenant_id == principal.tenant_id,
                    KnowledgeAgentLink.agent_id == agent_id,
                    KnowledgeContent.tenant_id == principal.tenant_id,
                    KnowledgeContent.status != "approved",
                )
                .limit(1)
            )
            if unapproved_content is not None:
                raise HTTPException(
                    409,
                    "A política do agente exige aprovação de todos os conteúdos associados.",
                )
        agent.publication_state = "published"
    else:
        if agent.publication_state != "published":
            raise HTTPException(409, "Somente agentes publicados podem ser despublicados.")
        agent.publication_state = "approved"
        agent.is_active = False
    db.commit()
    db.refresh(agent)
    return _serialize(agent)


@router.put("/{agent_id}/activation")
def update_activation(
    agent_id: str,
    request: AIAgentActivationUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin")),
):
    agent = _get_agent(db, agent_id, principal.tenant_id)
    if request.is_active and agent.publication_state != "published":
        raise HTTPException(409, "Publique o agente após aprovação humana para ativá-lo.")
    agent.is_active = request.is_active
    db.commit()
    db.refresh(agent)
    return _serialize(agent)
