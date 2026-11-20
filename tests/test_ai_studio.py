from sqlalchemy import func, select
import pytest
from fastapi.testclient import TestClient

import backend.app.auth as api_auth
from backend.app.config import Settings
from backend.app.main import app
from backend.app.models import AIAgent, AIAgentVersion, AdminActionLog


@pytest.fixture
def firebase_api_client(db_session_factory, monkeypatch):
    app.dependency_overrides.pop(api_auth.get_current_principal, None)
    settings = Settings(
        _env_file=None,
        google_cloud_project="synthetic-firebase-project",
        firebase_project_id="synthetic-firebase-project",
    )
    monkeypatch.setattr(api_auth, "get_settings", lambda: settings)
    verified_tokens = {
        "auditor-a": {"uid": "synthetic-auditor", "role": "auditor", "tenant_id": "tenant-a"},
        "gestor-a": {"uid": "synthetic-manager", "role": "gestor", "tenant_id": "tenant-a"},
        "admin-a": {"uid": "synthetic-admin", "role": "admin", "tenant_id": "tenant-a"},
        "admin-b": {"uid": "synthetic-admin-b", "role": "admin", "tenant_id": "tenant-b"},
    }

    def verify(token, project_id):
        assert project_id == "synthetic-firebase-project"
        if token not in verified_tokens:
            raise ValueError("synthetic invalid token")
        return verified_tokens[token]

    monkeypatch.setattr(api_auth, "verify_firebase_id_token", verify)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _agent_payload(name: str = "Synthetic agent") -> dict:
    return {
        "name": name,
        "purpose": "Review synthetic test cases.",
        "description": "Test-only configuration.",
        "process_role": "review",
        "model_id": "local-simulated",
        "instructions": "Use only the supplied synthetic context.",
        "system_prompt": "Do not contact anyone or use an external model.",
        "decision_criteria": "Return inconclusive when evidence is missing.",
        "safety_rules": "Never send messages or expose personal data.",
        "human_handoff": "Ask a human to review uncertain cases.",
        "temperature": 0.2,
        "max_output_tokens": 512,
        "max_cost_usd": 0,
    }


def test_ai_studio_is_admin_only_and_requires_authentication(firebase_api_client):
    assert firebase_api_client.get("/api/studio/agents").status_code == 401
    assert firebase_api_client.get(
        "/api/studio/agents", headers=_headers("auditor-a")
    ).status_code == 403
    assert firebase_api_client.get(
        "/api/studio/agents", headers=_headers("admin-a")
    ).status_code == 200


def test_initial_agent_templates_are_idempotent_and_tenant_scoped(
    firebase_api_client, db_session_factory
):
    first = firebase_api_client.post(
        "/api/studio/agents/initial-templates", headers=_headers("admin-a")
    )
    second = firebase_api_client.post(
        "/api/studio/agents/initial-templates", headers=_headers("admin-a")
    )
    other_tenant = firebase_api_client.get(
        "/api/studio/agents", headers=_headers("admin-b")
    )

    assert first.status_code == second.status_code == 200
    assert [agent["name"] for agent in first.json()] == [
        "Auditor de Motivos de Perda",
        "Agente de Recuperação de Leads",
    ]
    assert [agent["id"] for agent in first.json()] == [agent["id"] for agent in second.json()]
    assert all(not agent["is_active"] for agent in first.json())
    assert all(not agent["execution_enabled"] for agent in first.json())
    assert all(agent["publication_state"] == "draft" for agent in first.json())
    assert other_tenant.status_code == 200
    assert other_tenant.json() == []
    with db_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(AIAgent).where(AIAgent.tenant_id == "tenant-a")
        ) == 2


def test_agent_versions_need_human_approval_and_never_enable_execution(
    firebase_api_client, db_session_factory
):
    headers = _headers("admin-a")
    created = firebase_api_client.post(
        "/api/studio/agents", headers=headers, json=_agent_payload()
    )
    assert created.status_code == 200
    agent = created.json()
    agent_id = agent["id"]
    assert agent["publication_state"] == "draft"
    assert agent["execution_enabled"] is False
    assert agent["is_active"] is False

    denied_publish = firebase_api_client.post(
        f"/api/studio/agents/{agent_id}/publication",
        headers=headers,
        json={"action": "publish"},
    )
    assert denied_publish.status_code == 409

    approved = firebase_api_client.post(
        f"/api/studio/agents/{agent_id}/publication",
        headers=headers,
        json={"action": "approve"},
    )
    published = firebase_api_client.post(
        f"/api/studio/agents/{agent_id}/publication",
        headers=headers,
        json={"action": "publish"},
    )
    activated = firebase_api_client.put(
        f"/api/studio/agents/{agent_id}/activation",
        headers=headers,
        json={"is_active": True},
    )
    assert approved.json()["publication_state"] == "approved"
    assert published.json()["publication_state"] == "published"
    assert activated.json()["is_active"] is True
    assert activated.json()["execution_enabled"] is False

    updated_payload = _agent_payload("Updated synthetic agent")
    updated = firebase_api_client.put(
        f"/api/studio/agents/{agent_id}", headers=headers, json=updated_payload
    )
    versions = firebase_api_client.get(
        f"/api/studio/agents/{agent_id}/versions", headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["current_version"] == 2
    assert updated.json()["publication_state"] == "draft"
    assert updated.json()["is_active"] is False
    assert updated.json()["execution_enabled"] is False
    assert [version["version_number"] for version in versions.json()] == [2, 1]
    assert versions.json()[0]["snapshot"]["name"] == "Updated synthetic agent"
    assert versions.json()[1]["snapshot"]["name"] == "Synthetic agent"
    assert firebase_api_client.post(
        f"/api/studio/agents/{agent_id}/execute", headers=headers
    ).status_code == 404
    assert firebase_api_client.get(
        f"/api/studio/agents/{agent_id}", headers=_headers("admin-b")
    ).status_code == 404

    with db_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(AIAgentVersion).where(
                AIAgentVersion.agent_id == agent_id,
                AIAgentVersion.tenant_id == "tenant-a",
            )
        ) == 2
        assert session.scalar(
            select(AdminActionLog).where(
                AdminActionLog.tenant_id == "tenant-a",
                AdminActionLog.route == "/studio/agents/{agent_id}/publication",
            )
        ) is not None


def test_agent_model_and_runtime_parameters_are_validated(firebase_api_client):
    payload = _agent_payload()
    payload["model_id"] = "external-paid-model"
    invalid_model = firebase_api_client.post(
        "/api/studio/agents", headers=_headers("admin-a"), json=payload
    )
    assert invalid_model.status_code == 422

    payload = _agent_payload()
    payload["temperature"] = 2
    invalid_temperature = firebase_api_client.post(
        "/api/studio/agents", headers=_headers("admin-a"), json=payload
    )
    assert invalid_temperature.status_code == 422


def _create_karen_and_simulation(client, scenario: str, token: str = "admin-a"):
    headers = _headers(token)
    agent = client.post("/api/studio/agents/karen-template", headers=headers)
    assert agent.status_code == 200
    simulation = client.post(
        "/api/karen/simulations",
        headers=headers,
        json={"scenario_key": scenario},
    )
    assert simulation.status_code == 200
    return headers, agent.json(), simulation.json()


def test_karen_template_is_versioned_inactive_and_tenant_scoped(firebase_api_client):
    headers = _headers("admin-a")
    first = firebase_api_client.post("/api/studio/agents/karen-template", headers=headers)
    second = firebase_api_client.post("/api/studio/agents/karen-template", headers=headers)
    other_tenant = firebase_api_client.get(
        "/api/studio/agents", headers=_headers("admin-b")
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["name"] == "Karen"
    assert first.json()["publication_state"] == "draft"
    assert first.json()["is_active"] is False
    assert first.json()["execution_enabled"] is False
    assert "assistente virtual" in first.json()["system_prompt"]
    assert "preço" in first.json()["system_prompt"]
    assert other_tenant.json() == []
    versions = firebase_api_client.get(
        f"/api/studio/agents/{first.json()['id']}/versions", headers=headers
    )
    assert [version["version_number"] for version in versions.json()] == [1]


def test_karen_simulation_requires_auth_role_and_is_tenant_isolated(firebase_api_client):
    assert firebase_api_client.get("/api/karen/config").status_code == 401
    assert firebase_api_client.get(
        "/api/karen/config", headers=_headers("auditor-a")
    ).status_code == 403
    assert firebase_api_client.get(
        "/api/karen/config", headers=_headers("gestor-a")
    ).status_code == 200
    headers, _, simulation = _create_karen_and_simulation(
        firebase_api_client, "resume_negotiation"
    )

    other_tenant_list = firebase_api_client.get(
        "/api/karen/simulations", headers=_headers("admin-b")
    )
    other_tenant_detail = firebase_api_client.get(
        f"/api/karen/simulations/{simulation['id']}", headers=_headers("admin-b")
    )
    assert other_tenant_list.status_code == 200
    assert other_tenant_list.json() == []
    assert other_tenant_detail.status_code == 404
    assert simulation["synthetic_data_only"] is True
    assert simulation["outbound_enabled"] is False
    assert headers["Authorization"] == "Bearer admin-a"


def test_karen_contact_eligibility_requires_human_approval(firebase_api_client):
    headers, _, simulation = _create_karen_and_simulation(
        firebase_api_client, "incorrect_disqualification"
    )
    simulation_id = simulation["id"]
    action_path = f"/api/karen/simulations/{simulation_id}/actions"
    approval_path = f"/api/karen/simulations/{simulation_id}/approvals"
    assert firebase_api_client.post(
        action_path, headers=headers, json={"action": "confirm_contact"}
    ).status_code == 409
    assert firebase_api_client.post(
        approval_path,
        headers=_headers("auditor-a"),
        json={"action": "confirm_contact"},
    ).status_code == 403
    approved = firebase_api_client.post(
        approval_path, headers=_headers("gestor-a"), json={"action": "confirm_contact"}
    )
    contact_approved = firebase_api_client.post(
        action_path, headers=_headers("gestor-a"), json={"action": "confirm_contact"}
    )
    assert approved.status_code == contact_approved.status_code == 200
    assert contact_approved.json()["state"] == "contact_approved"
    assert contact_approved.json()["outbound_enabled"] is False


def test_karen_sensitive_commercial_actions_require_human_approval(firebase_api_client):
    headers, _, simulation = _create_karen_and_simulation(
        firebase_api_client, "accepts_proposal"
    )
    simulation_id = simulation["id"]
    turn = firebase_api_client.post(
        f"/api/karen/simulations/{simulation_id}/turns",
        headers=headers,
        json={"message": "Aceito a proposta simulada."},
    )
    assert turn.status_code == 200
    assert turn.json()["state"] == "proposal_preparation"
    assert "não cria uma contratação" in turn.json()["events"][-1]["message"]

    action_path = f"/api/karen/simulations/{simulation_id}/actions"
    denied = firebase_api_client.post(
        action_path, headers=headers, json={"action": "approve_proposal"}
    )
    assert denied.status_code == 409
    approval = firebase_api_client.post(
        f"/api/karen/simulations/{simulation_id}/approvals",
        headers=headers,
        json={"action": "approve_proposal", "note": "Revisão comercial fictícia."},
    )
    approved = firebase_api_client.post(
        action_path, headers=headers, json={"action": "approve_proposal"}
    )
    assert approval.status_code == 200
    assert approved.status_code == 200
    assert approved.json()["state"] == "proposal_approved"
    assert any(event["event_type"] == "approval_consumed" for event in approved.json()["events"])
    assert firebase_api_client.post(
        action_path, headers=headers, json={"action": "start_negotiation"}
    ).json()["state"] == "negotiation"


def test_karen_opt_out_is_terminal_and_preserves_simulation_evidence(firebase_api_client):
    headers, _, simulation = _create_karen_and_simulation(
        firebase_api_client, "contact_refusal"
    )
    simulation_id = simulation["id"]
    opted_out = firebase_api_client.post(
        f"/api/karen/simulations/{simulation_id}/turns",
        headers=headers,
        json={"message": "Não quero receber mais contato, por favor."},
    )
    assert opted_out.status_code == 200
    assert opted_out.json()["state"] == "opt_out"
    assert opted_out.json()["events"][-1]["to_state"] == "opt_out"

    rejected_action = firebase_api_client.post(
        f"/api/karen/simulations/{simulation_id}/actions",
        headers=headers,
        json={"action": "confirm_contact"},
    )
    rejected_turn = firebase_api_client.post(
        f"/api/karen/simulations/{simulation_id}/turns",
        headers=headers,
        json={"message": "Quero continuar a negociação."},
    )
    history = firebase_api_client.get(
        f"/api/karen/simulations/{simulation_id}", headers=headers
    ).json()["events"]
    assert rejected_action.status_code == 409
    assert rejected_turn.status_code == 409
    assert any(
        event["event_type"] == "conversation_turn" and "Não quero receber" in event["message"]
        for event in history
    )
    assert history[-1]["to_state"] == "opt_out"


def test_karen_scenario_intents_respect_message_and_distinguish_opt_out(firebase_api_client):
    headers, _, no_interest = _create_karen_and_simulation(
        firebase_api_client, "no_interest"
    )
    no_interest_result = firebase_api_client.post(
        f"/api/karen/simulations/{no_interest['id']}/turns",
        headers=headers,
        json={"message": "Não tenho interesse em continuar."},
    )
    assert no_interest_result.json()["state"] == "no_interest"

    _, _, opt_out = _create_karen_and_simulation(firebase_api_client, "contact_refusal")
    opt_out_result = firebase_api_client.post(
        f"/api/karen/simulations/{opt_out['id']}/turns",
        headers=headers,
        json={"message": "Não quero mais contato."},
    )
    assert opt_out_result.json()["state"] == "opt_out"

    _, _, discount = _create_karen_and_simulation(
        firebase_api_client, "unauthorized_discount"
    )
    discount_result = firebase_api_client.post(
        f"/api/karen/simulations/{discount['id']}/turns",
        headers=headers,
        json={"message": "Você pode me oferecer um desconto?"},
    )
    discount_turn = next(
        event
        for event in discount_result.json()["events"]
        if event["event_type"] == "conversation_turn"
    )
    assert discount_result.json()["state"] == "negotiation"
    assert "não posso confirmar descontos" in discount_turn["message"].casefold()


def test_karen_scenarios_are_synthetic_and_turns_include_evaluation(firebase_api_client):
    headers, _, _ = _create_karen_and_simulation(firebase_api_client, "no_interest")
    config = firebase_api_client.get("/api/karen/config", headers=headers).json()
    assert len(config["scenarios"]) == 10
    for scenario in config["scenarios"]:
        created = firebase_api_client.post(
            "/api/karen/simulations",
            headers=headers,
            json={"scenario_key": scenario["key"]},
        )
        assert created.status_code == 200
        turned = firebase_api_client.post(
            f"/api/karen/simulations/{created.json()['id']}/turns",
            headers=headers,
            json={"message": "Quero entender os próximos passos fictícios."},
        )
        assert turned.status_code == 200
        turn_event = next(
            event for event in turned.json()["events"] if event["event_type"] == "conversation_turn"
        )
        assert "assistente virtual" in turn_event["message"].lower()
        assert turn_event["decision"]["outbound_sent"] is False
        assert turn_event["evaluation"]["kindness"] >= 4
        assert turn_event["evaluation"]["compliance"] == 5

    created = firebase_api_client.post(
        "/api/karen/simulations",
        headers=headers,
        json={"scenario_key": "resume_negotiation"},
    ).json()
    personal_data = firebase_api_client.post(
        f"/api/karen/simulations/{created['id']}/turns",
        headers=headers,
        json={"message": "contato fictício lead@example.test"},
    )
    assert personal_data.status_code == 422
    personal_note = firebase_api_client.post(
        f"/api/karen/simulations/{created['id']}/actions",
        headers=headers,
        json={"action": "confirm_interest", "note": "Ligar para +1 (202) 555-0198"},
    )
    assert personal_note.status_code == 422


def test_karen_contract_simulation_requires_approvals_and_stays_fictitious(firebase_api_client):
    headers, _, simulation = _create_karen_and_simulation(
        firebase_api_client, "resume_negotiation"
    )
    simulation_id = simulation["id"]
    action_path = f"/api/karen/simulations/{simulation_id}/actions"
    approval_path = f"/api/karen/simulations/{simulation_id}/approvals"

    for action in ("confirm_interest", "start_qualification"):
        result = firebase_api_client.post(action_path, headers=headers, json={"action": action})
        assert result.status_code == 200
    for action in ("prepare_proposal", "approve_proposal"):
        approval = firebase_api_client.post(
            approval_path, headers=headers, json={"action": action}
        )
        assert approval.status_code == 200
        result = firebase_api_client.post(action_path, headers=headers, json={"action": action})
        assert result.status_code == 200
    assert firebase_api_client.post(
        action_path, headers=headers, json={"action": "start_negotiation"}
    ).json()["state"] == "negotiation"
    assert firebase_api_client.post(
        action_path, headers=headers, json={"action": "request_documents"}
    ).json()["state"] == "documentation_pending"

    approval = firebase_api_client.post(
        approval_path, headers=headers, json={"action": "prepare_contract"}
    )
    prepared = firebase_api_client.post(
        action_path, headers=headers, json={"action": "prepare_contract"}
    )
    assert approval.status_code == prepared.status_code == 200
    assert prepared.json()["state"] == "contract_validation"

    firebase_api_client.post(
        approval_path, headers=headers, json={"action": "create_contract_link"}
    )
    awaiting = firebase_api_client.post(
        action_path, headers=headers, json={"action": "create_contract_link"}
    )
    link_event = next(
        event
        for event in awaiting.json()["events"]
        if event["event_type"] == "transition"
        and event["decision"].get("action") == "create_contract_link"
    )
    assert awaiting.json()["state"] == "awaiting_signature"
    assert link_event["decision"]["simulated_link"].startswith(
        "https://example.invalid/simulated-contract/"
    )
    assert link_event["evaluation"]["legal_document"] is False

    firebase_api_client.post(
        approval_path, headers=headers, json={"action": "confirm_contract_signed"}
    )
    signed = firebase_api_client.post(
        action_path, headers=headers, json={"action": "confirm_contract_signed"}
    )
    assert signed.json()["state"] == "contract_signed_simulated"
    signed_transition = next(
        event
        for event in signed.json()["events"]
        if event["event_type"] == "transition"
        and event["decision"].get("action") == "confirm_contract_signed"
    )
    assert signed_transition["decision"]["contract_status"] == "simulated_only"
    assert signed.json()["outbound_enabled"] is False
    sequences = [event["sequence_no"] for event in signed.json()["events"]]
    assert sequences == list(range(1, len(sequences) + 1))


def test_karen_state_machine_rejects_invalid_transitions_and_resumes_auditably(
    firebase_api_client,
):
    headers, _, simulation = _create_karen_and_simulation(
        firebase_api_client, "resume_negotiation"
    )
    simulation_id = simulation["id"]
    action_path = f"/api/karen/simulations/{simulation_id}/actions"
    invalid = firebase_api_client.post(
        action_path, headers=headers, json={"action": "prepare_proposal"}
    )
    assert invalid.status_code == 409

    suspended = firebase_api_client.post(
        action_path, headers=headers, json={"action": "suspend"}
    )
    resumed = firebase_api_client.post(
        action_path, headers=headers, json={"action": "resume"}
    )
    assert suspended.json()["state"] == "suspended"
    assert resumed.json()["state"] == "commercial_confirmation"
    transitions = [
        (event["from_state"], event["to_state"])
        for event in resumed.json()["events"]
        if event["event_type"] == "transition"
    ]
    assert transitions == [
        ("commercial_confirmation", "suspended"),
        ("suspended", "commercial_confirmation"),
    ]
