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
