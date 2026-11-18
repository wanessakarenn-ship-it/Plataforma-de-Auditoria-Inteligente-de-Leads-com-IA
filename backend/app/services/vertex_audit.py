from backend.app.config import Settings
from backend.app.schemas import VertexAuditRequest, VertexAuditResult


class VertexAuditNotConfigured(RuntimeError):
    pass


class VertexAuditService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def audit_batch(self, items: list[VertexAuditRequest]) -> list[VertexAuditResult]:
        if len(items) > self.settings.audit_max_batch_size:
            raise ValueError("Audit batch exceeds configured processing limit.")
        if not items:
            return []
        raise VertexAuditNotConfigured(
            "Vertex AI execution is intentionally disabled in Sprint 01; no customer data was sent."
        )
