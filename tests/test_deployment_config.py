import pytest
from pydantic import ValidationError

from backend.app.config import (
    CLOUD_SQL_API_RUNTIME_IDENTITY,
    CLOUD_SQL_MIGRATOR_IDENTITY,
    SUPPORTED_APP_ENVS,
    Settings,
    require_cloud_sql_identity,
)


def _deployment_settings(**overrides):
    values = {
        "_env_file": None,
        "app_env": "homologation",
        "cloud_sql_iam_auth": True,
        "cloud_sql_connection_name": "synthetic-project:us-central1:synthetic-instance",
        "cloud_sql_db_name": "lead_intelligence",
        "cloud_sql_execution_identity": CLOUD_SQL_API_RUNTIME_IDENTITY,
        "cloud_sql_api_runtime_db_user": (
            "lead-intelligence-api-runtime@synthetic-project.iam"
        ),
        "api_cors_origins": ["https://preview.example.invalid"],
        "google_cloud_project": "synthetic-project",
        "firebase_project_id": "synthetic-project",
        "firebase_admin_user_management_enabled": False,
        "vertex_ai_enabled": False,
        "vertex_ai_approved": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_homologation_settings_require_cloud_sql_iam_auth_and_safe_app_settings():
    settings = _deployment_settings()
    assert settings.app_env == "homologation"
    assert settings.cloud_sql_iam_auth
    assert settings.cloud_sql_db_name == "lead_intelligence"


def test_cloud_sql_iam_auth_requires_explicit_connection_settings_in_development():
    with pytest.raises(ValidationError, match="requires a connection name"):
        Settings(_env_file=None, cloud_sql_iam_auth=True)


def test_cloud_sql_identity_is_explicit_and_migrator_cannot_be_used_as_runtime():
    with pytest.raises(ValidationError, match="explicit execution identity"):
        _deployment_settings(cloud_sql_execution_identity=None)

    migrator = _deployment_settings(
        cloud_sql_execution_identity=CLOUD_SQL_MIGRATOR_IDENTITY,
        cloud_sql_api_runtime_db_user="",
        cloud_sql_migrator_db_user="lead-intelligence-migrator@synthetic-project.iam",
    )
    require_cloud_sql_identity(migrator, CLOUD_SQL_MIGRATOR_IDENTITY)
    with pytest.raises(RuntimeError, match="lead-intelligence-api-runtime"):
        require_cloud_sql_identity(migrator, CLOUD_SQL_API_RUNTIME_IDENTITY)


def test_cloud_sql_selected_database_user_must_match_identity():
    with pytest.raises(ValidationError, match="must match the selected IAM identity"):
        _deployment_settings(cloud_sql_api_runtime_db_user="admin@synthetic-project.iam")


@pytest.mark.parametrize("app_env", sorted(SUPPORTED_APP_ENVS))
def test_supported_application_environments_are_accepted(app_env):
    assert _deployment_settings(app_env=app_env).app_env == app_env


@pytest.mark.parametrize("app_env", ["", "preview", "prod", "homologaton", "unknown"])
def test_unknown_application_environments_are_rejected(app_env):
    with pytest.raises(ValidationError, match="supported application environment"):
        Settings(_env_file=None, app_env=app_env)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cloud_sql_iam_auth": False}, "require Cloud SQL IAM"),
        ({"cloud_sql_connection_name": ""}, "requires a connection name"),
        ({"cloud_sql_db_name": ""}, "requires a connection name"),
        ({"cloud_sql_api_runtime_db_user": ""}, "requires its own database user"),
        (
            {"cloud_sql_connection_name": "another-project:us-central1:db"},
            "must match the configured project and region",
        ),
        ({"firebase_project_id": "another-project"}, "project IDs must match"),
        ({"api_cors_origins": ["http://localhost:3000"]}, "CORS origins must use HTTPS"),
        ({"vertex_ai_enabled": True}, "Vertex AI must remain disabled"),
        ({"firebase_admin_user_management_enabled": True}, "user management must remain disabled"),
    ],
)
def test_homologation_rejects_unsafe_deployment_settings(overrides, message):
    with pytest.raises(ValidationError, match=message):
        _deployment_settings(**overrides)
