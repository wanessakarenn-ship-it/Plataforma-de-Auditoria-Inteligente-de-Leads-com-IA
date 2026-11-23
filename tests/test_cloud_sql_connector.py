import pytest

from backend.app import db
from backend.app.config import get_settings


def test_cloud_sql_engine_uses_iam_connector_and_configured_connection(monkeypatch):
    calls = {}

    class FakeConnector:
        def __init__(self, **kwargs):
            calls["connector_options"] = kwargs

        def connect(self, instance_name, driver, **kwargs):
            calls["connect"] = (instance_name, driver, kwargs)
            return object()

        def close(self):
            calls["closed"] = True

    def fake_create_engine(url, **kwargs):
        calls["engine_url"] = url
        calls["engine_options"] = kwargs
        return object()

    monkeypatch.setattr(db, "_connector", None)
    monkeypatch.setattr(db, "Connector", FakeConnector)
    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    monkeypatch.setenv("APP_ENV", "homologation")
    monkeypatch.setenv("CLOUD_SQL_IAM_AUTH", "true")
    monkeypatch.setenv(
        "CLOUD_SQL_CONNECTION_NAME",
        "prime-amulet-439718-e3:us-central1:lead-intelligence-db-test",
    )
    monkeypatch.setenv("CLOUD_SQL_DB_NAME", "lead_intelligence")
    monkeypatch.setenv(
        "CLOUD_SQL_EXECUTION_IDENTITY",
        "lead-intelligence-api-runtime",
    )
    monkeypatch.setenv(
        "CLOUD_SQL_API_RUNTIME_DB_USER",
        "lead-intelligence-api-runtime@prime-amulet-439718-e3.iam",
    )
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "prime-amulet-439718-e3")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "prime-amulet-439718-e3")
    monkeypatch.setenv("API_CORS_ORIGINS", '["https://preview.example.invalid"]')
    monkeypatch.setenv("VERTEX_AI_ENABLED", "false")
    monkeypatch.setenv("VERTEX_AI_APPROVED", "false")
    monkeypatch.setenv("FIREBASE_ADMIN_USER_MANAGEMENT_ENABLED", "false")
    get_settings.cache_clear()

    try:
        engine = db.build_engine()
        connection = calls["engine_options"]["creator"]()

        assert engine is not None
        assert connection is not None
        assert calls["connector_options"] == {
            "enable_iam_auth": True,
            "refresh_strategy": "lazy",
        }
        assert calls["engine_url"] == "postgresql+psycopg://"
        assert calls["connect"] == (
            "prime-amulet-439718-e3:us-central1:lead-intelligence-db-test",
            "psycopg",
            {
                "user": "lead-intelligence-api-runtime@prime-amulet-439718-e3.iam",
                "db": "lead_intelligence",
                "ip_type": db.IPTypes.PUBLIC,
            },
        )
    finally:
        db.close_cloud_sql_connector()
        get_settings.cache_clear()

    assert calls["closed"] is True


def test_cloud_sql_engine_rejects_migrator_identity_for_api(monkeypatch):
    def unexpected_connector(**_kwargs):
        raise AssertionError("Identity mismatch must be rejected before connector creation.")

    monkeypatch.setattr(db, "_connector", None)
    monkeypatch.setattr(db, "Connector", unexpected_connector)
    monkeypatch.setenv("APP_ENV", "homologation")
    monkeypatch.setenv("CLOUD_SQL_IAM_AUTH", "true")
    monkeypatch.setenv(
        "CLOUD_SQL_CONNECTION_NAME",
        "prime-amulet-439718-e3:us-central1:lead-intelligence-db-test",
    )
    monkeypatch.setenv("CLOUD_SQL_DB_NAME", "lead_intelligence")
    monkeypatch.setenv(
        "CLOUD_SQL_EXECUTION_IDENTITY",
        "lead-intelligence-migrator",
    )
    monkeypatch.setenv(
        "CLOUD_SQL_MIGRATOR_DB_USER",
        "lead-intelligence-migrator@prime-amulet-439718-e3.iam",
    )
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "prime-amulet-439718-e3")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "prime-amulet-439718-e3")
    monkeypatch.setenv("API_CORS_ORIGINS", '["https://preview.example.invalid"]')
    monkeypatch.setenv("VERTEX_AI_ENABLED", "false")
    monkeypatch.setenv("VERTEX_AI_APPROVED", "false")
    monkeypatch.setenv("FIREBASE_ADMIN_USER_MANAGEMENT_ENABLED", "false")
    get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="lead-intelligence-api-runtime"):
            db.build_engine(expected_identity="lead-intelligence-api-runtime")
    finally:
        get_settings.cache_clear()
