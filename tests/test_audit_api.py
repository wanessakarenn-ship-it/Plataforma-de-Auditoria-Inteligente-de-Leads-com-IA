from datetime import timedelta

from backend.app.models import Conversation, Lead, Message, utc_now


def make_auditable_lead(session, *, include_history=True):
    lead = Lead(
        tenant_id="test-tenant",
        classification="lost",
        loss_reason="Synthetic budget reason",
        status="Lost",
        phase="Lost",
    )
    session.add(lead)
    session.flush()
    if include_history:
        conversation = Conversation(
            lead_id=lead.id,
            channel="synthetic",
            capture_source="synthetic test data",
        )
        session.add(conversation)
        session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                direction="inbound",
                provider_message_id="synthetic-audit-message",
                body="Synthetic budget reason: budget was above the agreed limit.",
                authorized_for_audit=True,
                retention_until=utc_now() + timedelta(days=30),
                sent_at=utc_now(),
            )
        )
        session.flush()
    return lead


def test_audit_workflow_persists_evidence_reprocessing_and_human_review(
    client, db_session_factory
):
    with db_session_factory() as session:
        lead = make_auditable_lead(session)
        lead_id = lead.id
        session.commit()

    response = client.post(f"/api/leads/{lead_id}/audits", json={"mode": "simulated"})
    assert response.status_code == 200
    audit = response.json()
    assert audit["execution_mode"] == "simulated"
    assert audit["classification"] == "confirmed"
    assert audit["status"] == "completed"
    assert audit["evidence"][0]["verified"] is True
    assert audit["evidence"][0]["excerpt"] == "Synthetic budget reason"

    reprocessed = client.post(
        f"/api/audits/{audit['id']}/reprocess",
        json={"mode": "simulated"},
    )
    assert reprocessed.status_code == 200
    assert reprocessed.json()["reprocess_of_id"] == audit["id"]

    reviewed = client.post(
        f"/api/audits/{audit['id']}/review",
        json={"decision": "confirmed", "notes": "Synthetic review"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "confirmed"
    assert reviewed.json()["reviewed_at"] is not None


def test_unavailable_message_history_is_not_auditable(client, db_session_factory):
    with db_session_factory() as session:
        lead = make_auditable_lead(session, include_history=False)
        lead_id = lead.id
        session.commit()

    response = client.post(f"/api/leads/{lead_id}/audits", json={"mode": "simulated"})
    assert response.status_code == 200
    result = response.json()
    assert result["classification"] == "not_auditable"
    assert result["evidence"] == []


def test_real_vertex_request_is_persisted_as_blocked_without_external_call(
    client, db_session_factory
):
    with db_session_factory() as session:
        lead = make_auditable_lead(session)
        lead_id = lead.id
        session.commit()

    response = client.post(f"/api/leads/{lead_id}/audits", json={"mode": "vertex"})
    assert response.status_code == 200
    result = response.json()
    assert result["execution_mode"] == "vertex"
    assert result["status"] == "blocked"
    assert result["estimated_cost_usd"] == 0
    assert result["evidence"] == []


def test_deleted_or_expired_messages_are_not_returned_as_audit_evidence(
    client, db_session_factory
):
    with db_session_factory() as session:
        lead = make_auditable_lead(session)
        lead_id = lead.id
        message = session.query(Message).filter_by(provider_message_id="synthetic-audit-message").one()
        message.authorized_for_audit = False
        session.commit()

    context = client.get(f"/api/leads/{lead_id}/audit-context")
    assert context.status_code == 200
    assert context.json()["messages"] == []

    audit = client.post(f"/api/leads/{lead_id}/audits", json={"mode": "simulated"}).json()
    assert audit["classification"] == "not_auditable"
    assert audit["evidence"] == []


def test_salesforce_import_confirmation_persists_date_and_decimal_value(client):
    content = (
        "Salesforce export; Nov 2026\n"
        "Created Date,Stage,Lead Status,Campaign,Lead Source,Last Name,Email,Mobile,"
        "Monthly Account Value,Reason Description,Loss Reason,Loss Reason Description\n"
        "2026-11-18T09:30:00,Lost,Qualified,Test Campaign,Web,Synthetic,"
        "lead-002@example.invalid,+1 202 555 0102,1234.56,Test detail,Budget,Test note\n"
    )
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("synthetic.csv", content.encode(), "text/csv")},
    )
    assert preview.status_code == 200
    result = preview.json()
    confirmed = client.post(f"/api/imports/{result['import_id']}/confirm")
    assert confirmed.status_code == 200
    leads = client.get("/api/leads").json()
    imported = next(lead for lead in leads if lead["last_name"] == "Synthetic")
    assert imported["crm_created_at"].startswith("2026-11-18T09:30:00")
    assert imported["monthly_account_value"] == "1234.56"
