from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CloudSqlExecutionIdentity = Literal[
    "lead-intelligence-api-runtime",
    "lead-intelligence-migrator",
]
CLOUD_SQL_API_RUNTIME_IDENTITY = "lead-intelligence-api-runtime"
CLOUD_SQL_MIGRATOR_IDENTITY = "lead-intelligence-migrator"
SUPPORTED_APP_ENVS = frozenset(
    {"development", "test", "staging", "homologation", "production"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./bc_lead_intelligence.db"
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=2, ge=0, le=20)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=120)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    cloud_sql_iam_auth: bool = False
    cloud_sql_connection_name: str = ""
    cloud_sql_db_name: str = ""
    cloud_sql_execution_identity: CloudSqlExecutionIdentity | None = None
    cloud_sql_api_runtime_db_user: str = ""
    cloud_sql_migrator_db_user: str = ""
    api_cors_origins: list[str] = ["http://localhost:3000"]
    google_cloud_project: str = "prime-amulet-439718-e3"
    firebase_project_id: str = ""
    firebase_admin_user_management_enabled: bool = False
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = True
    vertex_ai_model: str = "gemini-2.5-flash"
    vertex_ai_model_version: str = "gemini-2.5-flash"
    vertex_ai_enabled: bool = False
    vertex_ai_approved: bool = False
    vertex_ai_input_cost_per_million_usd: float = 0.0
    vertex_ai_output_cost_per_million_usd: float = 0.0
    vertex_ai_max_cost_per_audit_usd: float = 0.0
    vertex_ai_max_output_tokens: int = Field(default=512, ge=1, le=8192)
    vertex_ai_max_requests_per_minute: int = Field(default=10, ge=1, le=600)
    vertex_ai_max_concurrency: int = Field(default=2, ge=1, le=32)
    vertex_ai_max_history_messages: int = Field(default=50, ge=1, le=500)
    vertex_ai_max_context_characters: int = Field(default=16_000, ge=100, le=500_000)
    vertex_ai_prompt_version: str = "evidence-audit-v1"
    max_import_rows: int = 10_000
    max_import_file_mb: int = 20
    knowledge_max_file_mb: int = Field(default=5, ge=1, le=25)
    knowledge_max_extracted_chars: int = Field(default=500_000, ge=1_000, le=2_000_000)
    audit_max_batch_size: int = Field(default=20, ge=1, le=100)
    audit_timeout_seconds: int = Field(default=30, ge=1, le=120)
    message_retention_days: int = Field(default=90, ge=1, le=365)

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_APP_ENVS:
            raise ValueError("APP_ENV must name a supported application environment.")
        return normalized

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        else:
            origins = value
        if "*" in origins:
            raise ValueError("Wildcard CORS origins are not allowed.")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins.")
            if parsed.scheme == "http" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("Non-local CORS origins must use HTTPS.")
        return origins

    @model_validator(mode="after")
    def validate_deployment_settings(self):
        errors = []
        is_deployed = self.app_env in {"staging", "homologation", "production"}
        if self.cloud_sql_iam_auth:
            if (
                not self.cloud_sql_connection_name.strip()
                or not self.cloud_sql_db_name.strip()
            ):
                errors.append(
                    "Cloud SQL IAM authentication requires a connection name and database"
                )
            parts = self.cloud_sql_connection_name.strip().split(":")
            if len(parts) != 3 or any(not part for part in parts):
                errors.append("Cloud SQL connection name must be project:region:instance")
            elif (
                parts[0] != self.google_cloud_project.strip()
                or parts[1] != self.google_cloud_location.strip()
            ):
                errors.append(
                    "Cloud SQL connection name must match the configured project and region"
                )
            if self.cloud_sql_execution_identity is None:
                errors.append(
                    "Cloud SQL IAM authentication requires an explicit execution identity"
                )
            elif not self.selected_cloud_sql_db_user:
                errors.append("The selected Cloud SQL identity requires its own database user")
            elif self.selected_cloud_sql_db_user != (
                f"{self.cloud_sql_execution_identity}@{self.google_cloud_project.strip()}.iam"
            ):
                errors.append("The Cloud SQL database user must match the selected IAM identity")
        if not is_deployed:
            if errors:
                raise ValueError("; ".join(errors))
            return self

        if not self.cloud_sql_iam_auth:
            errors.append("deployed environments require Cloud SQL IAM database authentication")
        if (
            not self.firebase_project_id.strip()
            or self.firebase_project_id.strip() != self.google_cloud_project.strip()
        ):
            errors.append("Firebase and Google Cloud project IDs must match")
        if not self.api_cors_origins or any(
            urlsplit(origin).scheme != "https" for origin in self.api_cors_origins
        ):
            errors.append("deployed CORS origins must use HTTPS")
        if self.vertex_ai_enabled or self.vertex_ai_approved:
            errors.append("Vertex AI must remain disabled in this deployment")
        if self.firebase_admin_user_management_enabled:
            errors.append("runtime Firebase user management must remain disabled")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def selected_cloud_sql_db_user(self) -> str:
        if self.cloud_sql_execution_identity == CLOUD_SQL_API_RUNTIME_IDENTITY:
            return self.cloud_sql_api_runtime_db_user.strip()
        if self.cloud_sql_execution_identity == CLOUD_SQL_MIGRATOR_IDENTITY:
            return self.cloud_sql_migrator_db_user.strip()
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_cloud_sql_identity(
    settings: Settings,
    expected_identity: CloudSqlExecutionIdentity,
) -> None:
    if (
        settings.cloud_sql_iam_auth
        and settings.cloud_sql_execution_identity != expected_identity
    ):
        raise RuntimeError(
            f"This process requires Cloud SQL identity {expected_identity!r}."
        )
