from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./bc_lead_intelligence.db"
    api_cors_origins: list[str] = ["http://localhost:3000"]
    google_cloud_project: str = "prime-amulet-439718-e3"
    firebase_project_id: str = ""
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
    audit_max_batch_size: int = Field(default=20, ge=1, le=100)
    audit_timeout_seconds: int = Field(default=30, ge=1, le=120)
    message_retention_days: int = Field(default=90, ge=1, le=365)

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
