import pytest

from backend.app.config import Settings
from backend.app.schemas import VertexAuditRequest
from backend.app.services.vertex_audit import VertexAuditNotConfigured, VertexAuditService


def test_vertex_audit_is_explicitly_disabled_without_consuming_data():
    service = VertexAuditService(Settings(_env_file=None, audit_max_batch_size=1))
    assert service.audit_batch([]) == []
    with pytest.raises(VertexAuditNotConfigured, match="intentionally disabled"):
        service.audit_batch([VertexAuditRequest(lead_id="synthetic", context="synthetic only")])


def test_vertex_audit_batch_limit_is_enforced():
    service = VertexAuditService(Settings(_env_file=None, audit_max_batch_size=1))
    request = VertexAuditRequest(lead_id="synthetic", context="synthetic")
    with pytest.raises(ValueError, match="processing limit"):
        service.audit_batch([request, request])
