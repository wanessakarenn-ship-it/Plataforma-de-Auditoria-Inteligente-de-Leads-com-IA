from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import backend.app.auth as api_auth
import backend.app.api.routes as api_routes
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.main import app
from backend.app.models import AdminActionLog, Audit, Conversation, Lead, Message, utc_now


@pytest.fixture
def firebase_api_client(db_session_factory, monkeypatch):
    app.dependency_overrides.pop(api_auth.get_current_principal, None)
    settings = Settings(
        _env_file=None,
        google_cloud_project="synthetic-firebase-project",
        firebase_project_id="synthetic-firebase-project",
        firebase_admin_user_management_enabled=True,
    )
    monkeypatch.setattr(api_auth, "get_settings", lambda: settings)
    monkeypatch.setattr(api_routes, "get_settings", lambda: settings)
    verified_tokens = {
        "auditor-a": {"uid": "synthetic-auditor", "role": "auditor", "tenant_id": "tenant-a"},
        "auditor-b": {"uid": "synthetic-auditor-b", "role": "auditor", "tenant_id": "tenant-b"},
        "admin-a": {"uid": "synthetic-admin", "role": "admin", "tenant_id": "tenant-a"},
        "admin-b": {
            "uid": "synthetic-admin-b",
            "role": "admin",
            "tenant_id": "tenant-b",
        },
        "gestor-a": {"uid": "synthetic-manager", "role": "gestor", "tenant_id": "tenant-a"},
        "no-role": {"uid": "synthetic-no-role", "tenant_id": "tenant-a"},
        "bad-role": {"uid": "synthetic-bad-role", "role": "owner", "tenant_id": "tenant-a"},
        "no-tenant": {"uid": "synthetic-no-tenant", "role": "auditor"},
    }

    def verify(token, project_id):
        assert project_id == "synthetic-firebase-project"
        if token not in verified_tokens:
            raise ValueError("synthetic invalid token")
        return verified_tokens[token]

    monkeypatch.setattr(api_auth, "verify_firebase_id_token", verify)
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_public_but_business_data_requires_a_bearer_token(firebase_api_client):
    assert firebase_api_client.get("/api/health").status_code == 200
    assert firebase_api_client.get("/api/health/ready").status_code == 200
    response = firebase_api_client.get("/api/leads")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert firebase_api_client.get("/api/dashboard").status_code == 401
    assert firebase_api_client.get("/api/imports").status_code == 401


def test_all_non_health_api_routes_publish_bearer_authentication():
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/") or path.startswith("/api/health"):
            continue
        for operation in methods.values():
            assert operation.get("security") == [{"HTTPBearer": []}], path


def test_firebase_admin_verification_checks_revocation(monkeypatch):
    observed = {}
    fake_app = object()
    monkeypatch.setattr(api_auth, "_firebase_app", lambda project_id: fake_app)

    def verify(token, *, app, check_revoked):
        observed.update(token=token, app=app, check_revoked=check_revoked)
        return {"uid": "synthetic"}

    monkeypatch.setattr(api_auth.firebase_auth, "verify_id_token", verify)
    assert api_auth.verify_firebase_id_token("synthetic-token", "synthetic-project") == {
        "uid": "synthetic"
    }
    assert observed == {
        "token": "synthetic-token",
        "app": fake_app,
        "check_revoked": True,
    }


def test_invalid_token_is_rejected_without_logging_token_contents(
    firebase_api_client, caplog
):
    token = "synthetic-invalid-token-that-must-not-be-logged"
    response = firebase_api_client.get(
        "/api/leads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert token not in caplog.text
    assert token not in response.text


@pytest.mark.parametrize("token", ["no-role", "bad-role", "no-tenant"])
def test_missing_or_unrecognized_claims_are_forbidden(firebase_api_client, token):
    response = firebase_api_client.get(
        "/api/leads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_firebase_project_must_be_explicitly_configured(
    firebase_api_client, monkeypatch
):
    monkeypatch.setattr(
        api_auth,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            google_cloud_project="synthetic-firebase-project",
            firebase_project_id="",
        ),
    )
    response = firebase_api_client.get(
        "/api/leads",
        headers={"Authorization": "Bearer auditor-a"},
    )
    assert response.status_code == 503


def test_firebase_project_mismatch_is_rejected(firebase_api_client, monkeypatch):
    monkeypatch.setattr(
        api_auth,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            google_cloud_project="prime-amulet-439718-e3",
            firebase_project_id="different-firebase-project",
        ),
    )
    response = firebase_api_client.get(
        "/api/leads",
        headers={"Authorization": "Bearer auditor-a"},
    )
    assert response.status_code == 503


def test_cors_rejects_wildcards_and_insecure_remote_origins():
    with pytest.raises(ValueError, match="Wildcard"):
        Settings(_env_file=None, api_cors_origins=["*"])
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(_env_file=None, api_cors_origins=["http://example.invalid"])
    assert Settings(
        _env_file=None,
        api_cors_origins=["https://app.example.invalid", "http://localhost:3000"],
    ).api_cors_origins == ["https://app.example.invalid", "http://localhost:3000"]


def test_cors_origins_load_from_environment_as_json(monkeypatch):
    monkeypatch.setenv(
        "API_CORS_ORIGINS",
        '["https://app.example.invalid","http://localhost:3000"]',
    )
    assert Settings(_env_file=None).api_cors_origins == [
        "https://app.example.invalid",
        "http://localhost:3000",
    ]


def test_roles_restrict_imports_leads_audits_and_metrics(firebase_api_client):
    def request(method, path, token, **kwargs):
        return firebase_api_client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )

    assert request("GET", "/api/dashboard", "gestor-a").status_code == 200
    assert request("GET", "/api/dashboard", "admin-a").status_code == 200
    assert request("GET", "/api/leads", "gestor-a").status_code == 403
    assert request("GET", "/api/dashboard", "auditor-a").status_code == 403
    assert request("GET", "/api/leads", "admin-a").status_code == 403
    assert request("GET", "/api/imports", "auditor-a").status_code == 403
    assert request("POST", "/api/imports/preview", "gestor-a").status_code == 403
    assert request("GET", "/api/admin/users", "auditor-a").status_code == 403
    assert request("POST", "/api/leads/synthetic-id/audits", "gestor-a", json={}).status_code == 403
    assert request("GET", "/api/queues/contact", "gestor-a").status_code == 403
    assert request("GET", "/api/messages", "auditor-a").status_code == 404


def test_admin_dashboard_remains_tenant_scoped(firebase_api_client, db_session_factory):
    with db_session_factory() as session:
        session.add_all(
            [
                Lead(tenant_id="tenant-a", classification="lost"),
                Lead(tenant_id="tenant-b", classification="won"),
            ]
        )
        session.commit()

    response = firebase_api_client.get(
        "/api/dashboard",
        headers={"Authorization": "Bearer admin-a"},
    )

    assert response.status_code == 200
    assert response.json()["total_leads"] == 1
    assert response.json()["classifications"] == {"lost": 1}


def test_synthetic_xlsx_import_updates_only_the_admins_tenant_dashboard(
    firebase_api_client,
):
    def workbook_for(email: str) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Name", "Email", "Status", "Stage"])
        sheet.append(["Synthetic Lead", email, "Qualified", "Research"])
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def import_for(token: str, email: str) -> str:
        headers = {"Authorization": f"Bearer {token}"}
        preview = firebase_api_client.post(
            "/api/imports/preview",
            headers=headers,
            files={
                "file": (
                    "synthetic.xlsx",
                    workbook_for(email),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert preview.status_code == 200
        assert preview.json()["total_rows"] == 1
        assert preview.json()["valid_rows"] == 1

        import_id = preview.json()["import_id"]
        confirmed = firebase_api_client.post(
            f"/api/imports/{import_id}/confirm",
            headers=headers,
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["imported_rows"] == 1
        return import_id

    tenant_a_import = import_for("admin-a", "tenant-a@example.invalid")
    tenant_b_import = import_for("admin-b", "tenant-b@example.invalid")
    admin_a_headers = {"Authorization": "Bearer admin-a"}
    admin_b_headers = {"Authorization": "Bearer admin-b"}

    tenant_a_dashboard = firebase_api_client.get(
        "/api/dashboard", headers=admin_a_headers
    )
    tenant_b_dashboard = firebase_api_client.get(
        "/api/dashboard", headers=admin_b_headers
    )
    tenant_a_imports = firebase_api_client.get(
        "/api/imports", headers=admin_a_headers
    )

    assert tenant_a_dashboard.status_code == tenant_b_dashboard.status_code == 200
    assert tenant_a_dashboard.json()["total_leads"] == 1
    assert tenant_a_dashboard.json()["classifications"] == {"research": 1}
    assert [item["id"] for item in tenant_a_dashboard.json()["recent_imports"]] == [
        tenant_a_import
    ]
    assert tenant_b_dashboard.json()["total_leads"] == 1
    assert tenant_b_dashboard.json()["classifications"] == {"research": 1}
    assert tenant_a_imports.status_code == 200
    assert [item["id"] for item in tenant_a_imports.json()] == [tenant_a_import]
    assert tenant_a_imports.json()[0]["status"] == "completed"
    assert tenant_a_imports.json()[0]["imported_rows"] == 1

    foreign_confirm = firebase_api_client.post(
        f"/api/imports/{tenant_b_import}/confirm",
        headers=admin_a_headers,
    )
    assert foreign_confirm.status_code == 404


def test_lead_lists_details_and_conversation_history_are_tenant_scoped(
    firebase_api_client, db_session_factory
):
    with db_session_factory() as session:
        lead = Lead(
            tenant_id="tenant-b",
            classification="lost",
            loss_reason="Synthetic private reason",
        )
        session.add(lead)
        session.commit()
        foreign_lead_id = lead.id
        conversation = Conversation(
            lead_id=lead.id,
            channel="synthetic",
            capture_source="synthetic test",
        )
        session.add(conversation)
        session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                direction="inbound",
                body="Synthetic private message.",
                authorized_for_audit=True,
                retention_until=utc_now(),
            )
        )
        audit = Audit(lead_id=lead.id, original_reason="Synthetic reason")
        session.add(audit)
        session.commit()
        foreign_audit_id = audit.id
        unassigned = Lead(classification="lost", loss_reason="Legacy unassigned")
        session.add(unassigned)
        session.commit()
        unassigned_id = unassigned.id

    headers = {"Authorization": "Bearer auditor-a"}
    assert firebase_api_client.get("/api/leads", headers=headers).json() == []
    assert (
        firebase_api_client.get(f"/api/leads/{foreign_lead_id}", headers=headers).status_code
        == 404
    )
    assert (
        firebase_api_client.get(
            f"/api/leads/{foreign_lead_id}/audit-context",
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        firebase_api_client.get(
            f"/api/leads/{foreign_lead_id}/audits",
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        firebase_api_client.post(
            f"/api/audits/{foreign_audit_id}/reprocess",
            headers=headers,
            json={"mode": "simulated"},
        ).status_code
        == 404
    )
    assert (
        firebase_api_client.post(
            f"/api/audits/{foreign_audit_id}/review",
            headers=headers,
            json={"decision": "confirmed"},
        ).status_code
        == 404
    )
    assert (
        firebase_api_client.get(f"/api/leads/{unassigned_id}", headers=headers).status_code
        == 404
    )
    assert firebase_api_client.get("/api/reasons", headers=headers).json() == {
        "loss": [],
        "disqualification": [],
    }


def test_admin_user_listing_and_role_changes_are_tenant_bound_and_logged(
    firebase_api_client, db_session_factory, monkeypatch
):
    class FakeUser:
        uid = "synthetic-target-user"
        email = "synthetic@example.invalid"
        display_name = "Synthetic User"
        custom_claims = {"role": "auditor", "tenant_id": "tenant-a"}

    class FakePage:
        users = [
            FakeUser(),
            SimpleNamespace(
                uid="foreign-user",
                email="foreign@example.invalid",
                display_name="Foreign User",
                custom_claims={"role": "auditor", "tenant_id": "tenant-b"},
            ),
        ]
        next_page_token = None

    recorded_claims = {}
    monkeypatch.setattr(api_routes, "get_firebase_admin_app", lambda: object())
    monkeypatch.setattr(api_routes.firebase_auth, "list_users", lambda **kwargs: FakePage())
    monkeypatch.setattr(api_routes.firebase_auth, "get_user", lambda uid, **kwargs: FakeUser())
    monkeypatch.setattr(
        api_routes.firebase_auth,
        "set_custom_user_claims",
        lambda uid, claims, **kwargs: recorded_claims.update(uid=uid, claims=claims),
    )

    admin_headers = {"Authorization": "Bearer admin-a"}
    listing = firebase_api_client.get("/api/admin/users", headers=admin_headers)
    assert listing.status_code == 200
    assert [user["uid"] for user in listing.json()["users"]] == ["synthetic-target-user"]

    update = firebase_api_client.put(
        "/api/admin/users/synthetic-target-user/role",
        headers=admin_headers,
        json={"role": "gestor"},
    )
    assert update.status_code == 200
    assert update.json()["token_refresh_required"] is True
    assert recorded_claims["claims"] == {"role": "gestor", "tenant_id": "tenant-a"}

    self_update = firebase_api_client.put(
        "/api/admin/users/synthetic-admin/role",
        headers=admin_headers,
        json={"role": "auditor"},
    )
    assert self_update.status_code == 409

    with db_session_factory() as session:
        records = session.scalars(select(AdminActionLog)).all()
        assert len(records) == 3
        assert sorted(record.outcome for record in records) == [
            "failed",
            "succeeded",
            "succeeded",
        ]
        assert all(record.tenant_id == "tenant-a" for record in records)
        assert all("synthetic@example.invalid" not in record.route for record in records)
        assert all("/admin/users" in record.route for record in records), [
            record.route for record in records
        ]


def test_firebase_user_management_can_be_disabled_without_auth_admin_permissions(
    firebase_api_client, monkeypatch
):
    settings = Settings(
        _env_file=None,
        google_cloud_project="synthetic-firebase-project",
        firebase_project_id="synthetic-firebase-project",
        firebase_admin_user_management_enabled=False,
    )
    monkeypatch.setattr(api_routes, "get_settings", lambda: settings)

    def unexpected_firebase_access():
        raise AssertionError("Firebase Admin user APIs must not be called when disabled.")

    monkeypatch.setattr(api_routes, "get_firebase_admin_app", unexpected_firebase_access)
    headers = {"Authorization": "Bearer admin-a"}
    assert firebase_api_client.get("/api/admin/users", headers=headers).status_code == 503
    assert (
        firebase_api_client.put(
            "/api/admin/users/synthetic-target-user/role",
            headers=headers,
            json={"role": "gestor"},
        ).status_code
        == 503
    )


def test_readiness_does_not_expose_database_errors(firebase_api_client, caplog):
    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("synthetic-private-database-detail")

    def broken_database():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_database
    response = firebase_api_client.get("/api/health/ready")

    assert response.status_code == 503
    assert "synthetic-private-database-detail" not in response.text
    assert "synthetic-private-database-detail" not in caplog.text


def test_import_preview_is_admin_only_and_persists_scoped_action_log(
    firebase_api_client, db_session_factory
):
    content = (
        "Name,Email,Status,Stage\n"
        "Synthetic,private-contact@example.invalid,Lost,Lost\n"
    )
    denied = firebase_api_client.post(
        "/api/imports/preview",
        headers={"Authorization": "Bearer auditor-a"},
        files={"file": ("synthetic.csv", content.encode(), "text/csv")},
    )
    assert denied.status_code == 403

    allowed = firebase_api_client.post(
        "/api/imports/preview",
        headers={"Authorization": "Bearer admin-a"},
        files={"file": ("synthetic.csv", content.encode(), "text/csv")},
    )
    assert allowed.status_code == 200

    with db_session_factory() as session:
        record = session.scalar(select(AdminActionLog).order_by(AdminActionLog.created_at.desc()))
        assert record is not None
        assert record.actor_uid == "synthetic-admin"
        assert record.outcome == "succeeded"
        assert record.status_code == 200
        assert "private-contact@example.invalid" not in record.route
        assert record.resource_id is None


def test_import_duplicate_checks_do_not_disclose_other_tenants(
    firebase_api_client, db_session_factory
):
    with db_session_factory() as session:
        session.add(
            Lead(
                tenant_id="tenant-b",
                external_id="synthetic-cross-tenant-id",
                email="other-tenant@example.invalid",
                email_normalized="other-tenant@example.invalid",
                classification="unknown",
            )
        )
        session.commit()
    content = (
        "Id,Name,Email,Status,Stage\n"
        "synthetic-cross-tenant-id,Synthetic,other-tenant@example.invalid,Research,Research\n"
    )
    response = firebase_api_client.post(
        "/api/imports/preview",
        headers={"Authorization": "Bearer admin-a"},
        files={"file": ("synthetic.csv", content.encode(), "text/csv")},
    )
    assert response.status_code == 200
    preview = response.json()["preview"][0]
    assert preview["duplicate_in_database"] is False


def test_unconfigured_health_does_not_expose_project_configuration(firebase_api_client):
    response = firebase_api_client.get("/api/health")
    assert response.status_code == 200
    assert "project" not in response.text.lower()
