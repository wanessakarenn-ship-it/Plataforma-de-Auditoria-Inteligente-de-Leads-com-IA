from sqlalchemy import select

from backend.app.api import routes
from backend.app.config import Settings


def test_preview_confirm_persists_leads_and_separates_queues(client):
    csv_data = (
        "Salesforce Lead Report\n"
        "Id,Name,Email,Phone,Status,Stage,Company,Loss Reason\n"
        "00Q1,Ana Silva,ana@example.com,+14155550100,Qualified,Research,Acme,\n"
        "00Q2,Bia Lima,bia@example.com,+14155550101,Perdido,Closed Lost,Example,Budget\n"
        "00Q3,Caio Reis,broken-email,123,Qualified,Research,Example,\n"
        "00Q4,Dora Souza,dora@example.com,+14155550102,Ganho,Closed Won,Example,\n"
    )
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("salesforce.csv", csv_data.encode(), "text/csv")},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["total_rows"] == 4
    assert preview_body["error_rows"] == 1

    confirmed = client.post(f"/api/imports/{preview_body['import_id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["imported_rows"] == 3
    assert confirmed.json()["error_rows"] == 1

    leads = client.get("/api/leads").json()
    assert len(leads) == 3
    audit_items = client.get("/api/queues/audit").json()
    contact_items = client.get("/api/queues/contact").json()
    assert len(audit_items) == 2
    assert all(not item["eligible"] for item in contact_items)
    assert all(item["outbound_enabled"] is False for item in contact_items)
    assert {item["lead"]["classification"] for item in contact_items} == {"research"}
    assert [item["name"] for item in client.get("/api/reasons").json()["loss"]] == ["Budget"]


def test_preview_import_returns_payload_too_large_for_row_limit(client, monkeypatch):
    settings = Settings(_env_file=None, app_env="test", max_import_rows=1)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    content = b"Id,Email\n00Q1,one@example.test\n00Q2,two@example.test\n"

    response = client.post(
        "/api/imports/preview",
        files={"file": ("bounded.csv", content, "text/csv")},
    )

    assert response.status_code == 413


def test_confirmed_batch_cannot_be_confirmed_twice(client):
    preview = client.post(
        "/api/imports/preview",
        files={
            "file": (
                "leads.csv",
                b"Email,Status\nana@example.com,Levantada de Mao\n",
                "text/csv",
            )
        },
    ).json()
    assert client.post(f"/api/imports/{preview['import_id']}/confirm").status_code == 200
    assert client.post(f"/api/imports/{preview['import_id']}/confirm").status_code == 409


def test_deduplicates_between_imports_and_stores_unique_reason_catalog(client):
    first = client.post(
        "/api/imports/preview",
        files={
            "file": (
                "first.csv",
                b"Id,Email,Status,Loss Reason\n00Q1,one@example.com,Lost,Budget\n00Q2,two@example.com,Lost,Budget\n",
                "text/csv",
            )
        },
    ).json()
    assert client.post(f"/api/imports/{first['import_id']}/confirm").json()["imported_rows"] == 2
    second = client.post(
        "/api/imports/preview",
        files={
            "file": (
                "second.csv",
                b"Id,Email,Status\n00Q3,ONE@example.com,Research\n",
                "text/csv",
            )
        },
    ).json()
    assert second["duplicate_rows"] == 1
    assert second["preview"][0]["duplicate_in_database"] is True
    result = client.post(f"/api/imports/{second['import_id']}/confirm").json()
    assert result["imported_rows"] == 0
    assert result["duplicate_rows"] == 1
    assert len(client.get("/api/leads").json()) == 2
    assert [item["name"] for item in client.get("/api/reasons").json()["loss"]] == ["Budget"]


def test_individual_lead_detail_includes_history_and_default_unknown_permission(client):
    preview = client.post(
        "/api/imports/preview",
        files={
            "file": (
                "detail.csv",
                b"Id,Name,Email,Status,Stage\n00Q7,Sample Lead,lead@example.com,Qualified,Research\n",
                "text/csv",
            )
        },
    ).json()
    client.post(f"/api/imports/{preview['import_id']}/confirm")
    lead = client.get("/api/leads").json()[0]
    detail = client.get(f"/api/leads/{lead['id']}/detail").json()
    assert detail["lead"]["first_name"] == "Sample"
    assert detail["status_history"][0]["current_phase"] == "Research"
    assert detail["contact_permission"] is None


def test_no_outbound_message_api_exists(client):
    paths = [
        path.lower()
        for route in client.app.routes
        if (path := getattr(route, "path", None)) is not None
    ]
    assert not any(
        any(term in path for term in ("send", "whatsapp", "outbound"))
        for path in paths
    )
    response = client.get("/api/queues/contact")
    assert response.status_code == 200
    assert all(row["outbound_enabled"] is False for row in response.json())


def test_import_history_status_history_and_processing_logs_persist(client, db_session_factory):
    preview = client.post(
        "/api/imports/preview",
        files={
            "file": (
                "history.csv",
                b"Id,Email,Status\n00Q99,history@example.com,Lost\n",
                "text/csv",
            )
        },
    ).json()
    client.post(f"/api/imports/{preview['import_id']}/confirm")
    assert client.get("/api/imports").json()[0]["status"] == "completed"
    assert len(client.get("/api/leads").json()) == 1
    assert len(client.get("/api/queues/audit").json()) == 1
    assert len(client.get("/api/queues/contact").json()) == 0
    from backend.app.models import ImportBatch, LeadStatusHistory, ProcessingLog

    with db_session_factory() as db:
        assert db.get(ImportBatch, preview["import_id"]).status == "completed"
        assert db.scalar(select(LeadStatusHistory)) is not None
        assert db.scalar(select(ProcessingLog)) is not None
