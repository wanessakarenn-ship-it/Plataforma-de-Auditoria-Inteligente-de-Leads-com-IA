from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./bc_lead_intelligence.db"
    api_cors_origins: list[str] = ["http://localhost:3000"]
    google_cloud_project: str = "prime-amulet-439718-e3"
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = True
    vertex_ai_model: str = "gemini-2.5-flash"
    max_import_rows: int = 10_000
    max_import_file_mb: int = 20
    audit_max_batch_size: int = 20
    audit_timeout_seconds: int = 30

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
