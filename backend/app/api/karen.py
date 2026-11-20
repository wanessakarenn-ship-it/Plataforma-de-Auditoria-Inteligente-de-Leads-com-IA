from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.auth import Principal, require_roles
from backend.app.db import get_db
from backend.app.models import AIAgent, KarenSimulation, KarenSimulationEvent
from backend.app.schemas import (
    KarenSimulationActionRequest,
    KarenSimulationApprovalRequest,
    KarenSimulationCreateRequest,
    KarenSimulationTurnRequest,
)
from backend.app.services.karen_simulation import (
    ACTION_LABELS,
    SCENARIOS,
    SENSITIVE_ACTIONS,
    STATES,
    TRANSITIONS,
    available_actions,
    draft_response,
    evaluate_response,
    transition_target,
)
from backend.app.services.knowledge_retrieval import retrieve_knowledge

router = APIRouter(prefix="/karen", tags=["Karen"])


def _get_simulation(db: Session, simulation_id: str, tenant_id: str) -> KarenSimulation:
    simulation = db.scalar(
        select(KarenSimulation)
        .where(
            KarenSimulation.id == simulation_id,
            KarenSimulation.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if simulation is None:
        raise HTTPException(404, "Simulação não encontrada nesta organização.")
    return simulation


def _append_event(
    db: Session,
    simulation: KarenSimulation,
    actor_uid: str,
    event_type: str,
    from_state: str | None,
    to_state: str | None,
    message: str | None = None,
    decision: dict | None = None,
    evidence: list | None = None,
    evaluation: dict | None = None,
) -> KarenSimulationEvent:
    last_sequence = db.scalar(
        select(func.max(KarenSimulationEvent.sequence_no)).where(
            KarenSimulationEvent.tenant_id == simulation.tenant_id,
            KarenSimulationEvent.simulation_id == simulation.id,
        )
    )
    event = KarenSimulationEvent(
        tenant_id=simulation.tenant_id,
        simulation_id=simulation.id,
        sequence_no=(last_sequence or 0) + 1,
        event_type=event_type,
        from_state=from_state,
        to_state=to_state,
        message=message,
        decision_json=decision or {},
        evidence_json=evidence or [],
        evaluation_json=evaluation or {},
        actor_uid=actor_uid,
    )
    db.add(event)
    db.flush()
    return event


def _serialize_event(event: KarenSimulationEvent) -> dict:
    return {
        "id": event.id,
        "sequence_no": event.sequence_no,
        "event_type": event.event_type,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "message": event.message,
        "decision": event.decision_json,
        "evidence": event.evidence_json,
        "evaluation": event.evaluation_json,
        "actor_uid": event.actor_uid,
        "created_at": event.created_at,
    }


def _serialize_simulation(
    simulation: KarenSimulation,
    events: list[KarenSimulationEvent] | None = None,
) -> dict:
    scenario = SCENARIOS[simulation.scenario_key]
    return {
        "id": simulation.id,
        "scenario_key": simulation.scenario_key,
        "scenario_title": scenario["title"],
        "state": simulation.state,
        "state_label": STATES[simulation.state],
        "available_actions": available_actions(simulation.state),
        "agent_id": simulation.agent_id,
        "created_at": simulation.created_at,
        "updated_at": simulation.updated_at,
        "synthetic_data_only": True,
        "outbound_enabled": False,
        "events": [_serialize_event(event) for event in events] if events is not None else None,
    }


def _simulation_events(
    db: Session, simulation: KarenSimulation
) -> list[KarenSimulationEvent]:
    events = db.scalars(
        select(KarenSimulationEvent)
        .where(
            KarenSimulationEvent.tenant_id == simulation.tenant_id,
            KarenSimulationEvent.simulation_id == simulation.id,
        )
        .order_by(KarenSimulationEvent.sequence_no.desc())
        .limit(500)
    ).all()
    return list(reversed(events))


def _pending_approval(
    db: Session, simulation: KarenSimulation, action: str
) -> KarenSimulationEvent | None:
    events = _simulation_events(db, simulation)
    consumed = {
        event.decision_json.get("approval_event_id")
        for event in events
        if event.event_type == "approval_consumed"
    }
    return next(
        (
            event
            for event in reversed(events)
            if event.event_type == "human_approval"
            and event.decision_json.get("action") == action
            and event.decision_json.get("for_state") == simulation.state
            and event.id not in consumed
        ),
        None,
    )


def _apply_action(
    db: Session,
    simulation: KarenSimulation,
    actor_uid: str,
    action: str,
    note: str | None = None,
) -> KarenSimulationEvent:
    if action != "opt_out" and action not in available_actions(simulation.state):
        raise HTTPException(409, "A ação não está disponível nesta etapa da jornada.")
    try:
        prior_suspend = next(
            (
                event
                for event in reversed(_simulation_events(db, simulation))
                if event.event_type == "transition"
                and event.decision_json.get("action") == "suspend"
            ),
            None,
        )
        previous_state = (
            prior_suspend.decision_json.get("previous_state") if prior_suspend else None
        )
        target = transition_target(simulation.state, action, previous_state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    approval = None
    if action in SENSITIVE_ACTIONS:
        approval = _pending_approval(db, simulation, action)
        if approval is None:
            raise HTTPException(
                409, "Esta ação comercial exige aprovação humana explícita nesta etapa."
            )

    old_state = simulation.state
    details = {"action": action, "note": note, "synthetic": True}
    if action == "suspend":
        details["previous_state"] = old_state
    if action == "create_contract_link":
        details["simulated_link"] = (
            f"https://example.invalid/simulated-contract/{uuid4()}"
        )
    if action == "confirm_contract_signed":
        details["contract_status"] = "simulated_only"

    simulation.state = target
    event = _append_event(
        db,
        simulation,
        actor_uid,
        "transition",
        old_state,
        target,
        decision=details,
        evidence=[
            {"source": "synthetic_scenario", "scenario_key": simulation.scenario_key},
            {"source": "human_action", "actor_uid": actor_uid},
        ],
    )
    if approval is not None:
        _append_event(
            db,
            simulation,
            actor_uid,
            "approval_consumed",
            old_state,
            target,
            decision={"approval_event_id": approval.id, "action": action},
            evidence=[{"source": "human_approval", "actor_uid": approval.actor_uid}],
        )
    return event


@router.get("/config")
def get_karen_config(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin", "gestor")),
):
    agent = db.scalar(
        select(AIAgent).where(
            AIAgent.tenant_id == principal.tenant_id,
            AIAgent.template_key == "karen-commercial-assistant",
        )
    )
    return {
        "configured": agent is not None,
        "agent": (
            {
                "id": agent.id,
                "name": agent.name,
                "current_version": agent.current_version,
                "publication_state": agent.publication_state,
                "is_active": agent.is_active,
                "execution_enabled": False,
            }
            if agent
            else None
        ),
        "states": [{"key": key, "label": label} for key, label in STATES.items()],
        "scenarios": [
            {"key": key, "title": value["title"]}
            for key, value in SCENARIOS.items()
        ],
        "sensitive_actions": sorted(SENSITIVE_ACTIONS),
        "action_labels": ACTION_LABELS,
        "transition_rules": TRANSITIONS,
        "outbound_enabled": False,
        "contract_integration": {
            "status": "not_connected",
            "provider": None,
            "document_generation": "fictional_only",
        },
    }


@router.post("/simulations")
def create_simulation(
    request: KarenSimulationCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin", "gestor")),
):
    agent = db.scalar(
        select(AIAgent).where(
            AIAgent.tenant_id == principal.tenant_id,
            AIAgent.template_key == "karen-commercial-assistant",
        )
    )
    if agent is None:
        raise HTTPException(409, "Crie primeiro o rascunho da Karen no Estúdio de IA.")
    scenario = SCENARIOS[request.scenario_key]
    simulation = KarenSimulation(
        tenant_id=principal.tenant_id,
        agent_id=agent.id,
        scenario_key=request.scenario_key,
        state=scenario["initial_state"],
        created_by_uid=principal.uid,
    )
    db.add(simulation)
    db.flush()
    _append_event(
        db,
        simulation,
        principal.uid,
        "scenario_started",
        None,
        simulation.state,
        decision={"scenario_key": request.scenario_key, "synthetic": True},
        evidence=[
            {"source": "scenario_catalog", "scenario_key": request.scenario_key},
            {"source": "prompt_version", "agent_version": agent.current_version},
        ],
    )
    db.commit()
    db.refresh(simulation)
    return _serialize_simulation(simulation, _simulation_events(db, simulation))


@router.get("/simulations")
def list_simulations(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin", "gestor")),
):
    simulations = db.scalars(
        select(KarenSimulation)
        .where(KarenSimulation.tenant_id == principal.tenant_id)
        .order_by(KarenSimulation.updated_at.desc())
        .limit(100)
    ).all()
    return [_serialize_simulation(item) for item in simulations]


@router.get("/simulations/{simulation_id}")
def get_simulation(
    simulation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin", "gestor")),
):
    simulation = _get_simulation(db, simulation_id, principal.tenant_id)
    return _serialize_simulation(simulation, _simulation_events(db, simulation))


@router.post("/simulations/{simulation_id}/turns")
def simulate_turn(
    simulation_id: str,
    request: KarenSimulationTurnRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin", "gestor")),
):
    simulation = _get_simulation(db, simulation_id, principal.tenant_id)
    if simulation.state in {"opt_out", "no_interest", "blocked"}:
        raise HTTPException(409, "A jornada foi encerrada ou bloqueada e não recebe novos turnos.")
    if simulation.state == "human_transfer":
        raise HTTPException(409, "A conversa foi transferida para revisão humana.")

    agent = db.scalar(
        select(AIAgent).where(
            AIAgent.id == simulation.agent_id,
            AIAgent.tenant_id == principal.tenant_id,
        )
    )
    if agent is None:
        raise HTTPException(404, "Agente Karen não encontrado nesta organização.")
    retrieved = retrieve_knowledge(
        db,
        principal.tenant_id,
        request.message,
        agent.id,
        top_k=3,
    )
    references = retrieved["references"]
    response, suggested_action = draft_response(
        request.message, simulation.state, simulation.scenario_key, references
    )
    old_state = simulation.state
    _append_event(
        db,
        simulation,
        principal.uid,
        "conversation_turn",
        old_state,
        old_state,
        message=(
            f"Lead (texto sintético): {request.message}\n"
            f"Karen (rascunho local, não enviado): {response}"
        ),
        decision={
            "suggested_action": suggested_action,
            "outbound_sent": False,
            "agent_version": agent.current_version,
        },
        evidence=[
            {"source": "prompt_version", "agent_version": agent.current_version},
            {"source": "synthetic_scenario", "scenario_key": simulation.scenario_key},
            *[
                {
                    "source": "approved_knowledge",
                    "content_id": item["content_id"],
                    "title": item["title"],
                    "version": item["version"],
                    "excerpt": item["excerpt"],
                }
                for item in references
            ],
        ],
        evaluation=evaluate_response(response, references),
    )
    if suggested_action:
        _apply_action(db, simulation, principal.uid, suggested_action)
    db.commit()
    db.refresh(simulation)
    return _serialize_simulation(simulation, _simulation_events(db, simulation))


@router.post("/simulations/{simulation_id}/actions")
def apply_simulation_action(
    simulation_id: str,
    request: KarenSimulationActionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin", "gestor")),
):
    simulation = _get_simulation(db, simulation_id, principal.tenant_id)
    event = _apply_action(db, simulation, principal.uid, request.action, request.note)
    if request.action == "create_contract_link":
        event.evaluation_json = {
            "status": "fake_link_only",
            "legal_document": False,
            "real_contract": False,
        }
    db.commit()
    db.refresh(simulation)
    return _serialize_simulation(simulation, _simulation_events(db, simulation))


@router.post("/simulations/{simulation_id}/approvals")
def approve_simulation_action(
    simulation_id: str,
    request: KarenSimulationApprovalRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("admin", "gestor")),
):
    simulation = _get_simulation(db, simulation_id, principal.tenant_id)
    if request.action not in available_actions(simulation.state):
        raise HTTPException(409, "Não é possível aprovar esta ação na etapa atual.")
    try:
        transition_target(simulation.state, request.action)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _append_event(
        db,
        simulation,
        principal.uid,
        "human_approval",
        simulation.state,
        simulation.state,
        decision={
            "action": request.action,
            "for_state": simulation.state,
            "approved_by_human": True,
        },
        evidence=[
            {"source": "authenticated_human_approval", "actor_uid": principal.uid},
            {"source": "synthetic_scenario", "scenario_key": simulation.scenario_key},
        ],
    )
    db.commit()
    db.refresh(simulation)
    return _serialize_simulation(simulation, _simulation_events(db, simulation))
