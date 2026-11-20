import asyncio
from types import SimpleNamespace

import google.genai
import pytest

from backend.app.config import Settings
from backend.app.services.vertex_audit import (
    AuditDecision,
    AuditExecutionError,
    AuditEvidenceQuote,
    AuditInput,
    AuditMessage,
    VertexAuditNotConfigured,
    VertexAuditProvider,
    VertexAuditService,
)


class FakeProvider:
    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    async def generate(self, prompt):
        self.calls += 1
        assert "Messages JSON" in prompt
        return self.decision, 120, 45


def audit_input(reason="Budget", messages=None, history_available=True):
    return AuditInput(
        lead_id="synthetic-lead",
        original_reason=reason,
        history_available=history_available,
        messages=messages
        if messages is not None
        else [
            AuditMessage(
                id="synthetic-message",
                provider_message_id="provider-msg-001",
                body="Budget was above the agreed limit.",
            )
        ],
    )


def test_simulated_mode_produces_verified_confirmed_evidence_without_provider_call():
    provider = FakeProvider(
        AuditDecision(
            classification="inconclusive",
            justification="unused",
        )
    )
    outcome = asyncio.run(
        VertexAuditService(Settings(_env_file=None), provider).run(audit_input())
    )

    assert outcome.execution_mode == "simulated"
    assert outcome.classification == "confirmed"
    assert outcome.evidence[0].excerpt == "Budget"
    assert outcome.requires_human_review
    assert provider.calls == 0


def test_simulated_mode_without_matching_evidence_is_inconclusive():
    request = audit_input(messages=[
        AuditMessage(id="synthetic-message", body="The deal was paused.")
    ])
    outcome = asyncio.run(VertexAuditService(Settings(_env_file=None)).run(request))
    assert outcome.classification == "inconclusive"
    assert outcome.evidence == []
    assert outcome.requires_human_review


def test_missing_authorized_history_is_not_auditable():
    request = audit_input(messages=[], history_available=False)
    outcome = asyncio.run(VertexAuditService(Settings(_env_file=None)).run(request))
    assert outcome.classification == "not_auditable"
    assert "Histórico autorizado indisponível." in outcome.limitations


def test_request_hash_tracks_reason_and_authorized_message_content():
    service = VertexAuditService(Settings(_env_file=None))
    original = audit_input()
    changed_reason = audit_input(reason="Different synthetic reason")
    changed_message = audit_input(
        messages=[
            AuditMessage(
                id="synthetic-message",
                provider_message_id="provider-msg-001",
                body="Different synthetic message text.",
            )
        ]
    )

    original_hash = asyncio.run(service.run(original)).request_hash
    reason_hash = asyncio.run(service.run(changed_reason)).request_hash
    message_hash = asyncio.run(service.run(changed_message)).request_hash

    assert original_hash != reason_hash
    assert original_hash != message_hash


def test_conclusive_vertex_result_requires_an_exact_quote_from_known_message():
    provider = FakeProvider(
        AuditDecision(
            classification="divergent",
            justification="A mensagem aponta uma razão diferente.",
            evidence=[
                AuditEvidenceQuote(
                    message_id="synthetic-message",
                    quote="unseen claim",
                )
            ],
        )
    )
    settings = Settings(
        _env_file=None,
        vertex_ai_enabled=True,
        vertex_ai_approved=True,
        vertex_ai_input_cost_per_million_usd=1,
        vertex_ai_output_cost_per_million_usd=1,
        vertex_ai_max_cost_per_audit_usd=1,
    )
    with pytest.raises(AuditExecutionError, match="did not match authorized source text"):
        asyncio.run(VertexAuditService(settings, provider).run(audit_input(), "vertex"))
    assert provider.calls == 1


def test_valid_vertex_divergence_is_recorded_with_verified_evidence():
    provider = FakeProvider(
        AuditDecision(
            classification="divergent",
            justification="A conversa documenta uma razão diferente.",
            evidence=[
                AuditEvidenceQuote(
                    message_id="synthetic-message",
                    quote="above the agreed limit",
                )
            ],
            alternative_reason="Limite de orçamento",
            requires_human_review=False,
        )
    )
    settings = Settings(
        _env_file=None,
        vertex_ai_enabled=True,
        vertex_ai_approved=True,
        vertex_ai_input_cost_per_million_usd=1,
        vertex_ai_output_cost_per_million_usd=1,
        vertex_ai_max_cost_per_audit_usd=1,
    )
    outcome = asyncio.run(VertexAuditService(settings, provider).run(audit_input(), "vertex"))
    assert outcome.classification == "divergent"
    assert outcome.evidence[0].excerpt == "above the agreed limit"
    assert outcome.provider == "vertex-ai"
    assert outcome.model_version == settings.vertex_ai_model_version
    assert outcome.input_tokens == 120
    assert outcome.requires_human_review


def test_vertex_conclusion_without_citations_is_rejected():
    provider = FakeProvider(
        AuditDecision(
            classification="confirmed",
            justification="A conclusão sem citação deve ser rejeitada.",
            requires_human_review=False,
        )
    )
    settings = Settings(
        _env_file=None,
        vertex_ai_enabled=True,
        vertex_ai_approved=True,
        vertex_ai_input_cost_per_million_usd=1,
        vertex_ai_output_cost_per_million_usd=1,
        vertex_ai_max_cost_per_audit_usd=1,
    )
    with pytest.raises(AuditExecutionError, match="requires verified evidence"):
        asyncio.run(VertexAuditService(settings, provider).run(audit_input(), "vertex"))


def test_real_vertex_mode_is_blocked_by_default_without_provider_call():
    provider = FakeProvider(
        AuditDecision(
            classification="confirmed",
            justification="Unexpected call",
            evidence=[
                AuditEvidenceQuote(message_id="synthetic-message", quote="Budget")
            ],
        )
    )
    with pytest.raises(VertexAuditNotConfigured, match="explicit enablement and approval"):
        asyncio.run(
            VertexAuditService(Settings(_env_file=None), provider).run(audit_input(), "vertex")
        )
    assert provider.calls == 0


def test_cost_cap_and_context_limits_are_enforced_before_vertex_call():
    provider = FakeProvider(
        AuditDecision(classification="inconclusive", justification="No conclusion.")
    )
    capped = Settings(
        _env_file=None,
        vertex_ai_enabled=True,
        vertex_ai_approved=True,
        vertex_ai_input_cost_per_million_usd=100,
        vertex_ai_output_cost_per_million_usd=100,
        vertex_ai_max_cost_per_audit_usd=0.0001,
    )
    with pytest.raises(VertexAuditNotConfigured, match="cost ceiling"):
        asyncio.run(VertexAuditService(capped, provider).run(audit_input(), "vertex"))
    assert provider.calls == 0

    limited = Settings(_env_file=None, vertex_ai_max_context_characters=100)
    oversized_request = audit_input(
        messages=[AuditMessage(id="synthetic-large", body="x" * 101)]
    )
    with pytest.raises(ValueError, match="context exceeds"):
        asyncio.run(VertexAuditService(limited, provider).run(oversized_request))


def test_batch_size_limit_is_enforced():
    service = VertexAuditService(Settings(_env_file=None, audit_max_batch_size=1))
    requests = [audit_input(), audit_input()]
    with pytest.raises(ValueError, match="processing limit"):
        asyncio.run(service.run_batch(requests))


def test_vertex_rate_limit_is_enforced_before_second_provider_call():
    provider = FakeProvider(
        AuditDecision(classification="inconclusive", justification="Not enough evidence.")
    )
    settings = Settings(
        _env_file=None,
        vertex_ai_enabled=True,
        vertex_ai_approved=True,
        vertex_ai_input_cost_per_million_usd=1,
        vertex_ai_output_cost_per_million_usd=1,
        vertex_ai_max_cost_per_audit_usd=1,
        vertex_ai_max_requests_per_minute=1,
    )
    service = VertexAuditService(settings, provider)
    asyncio.run(service.run(audit_input(), "vertex"))
    with pytest.raises(VertexAuditNotConfigured, match="rate limit"):
        asyncio.run(service.run(audit_input(), "vertex"))
    assert provider.calls == 1


def test_vertex_provider_maps_timeout_without_network_request(monkeypatch):
    class FakeModels:
        async def generate_content(self, **kwargs):
            raise TimeoutError

    class FakeAsyncClient:
        models = FakeModels()

        async def aclose(self):
            return None

    client = SimpleNamespace(aio=FakeAsyncClient())
    monkeypatch.setattr(google.genai, "Client", lambda **kwargs: client)
    with pytest.raises(AuditExecutionError, match="timed out"):
        asyncio.run(VertexAuditProvider(Settings(_env_file=None)).generate("synthetic prompt"))


def test_vertex_batch_respects_configured_concurrency():
    class ConcurrentProvider:
        def __init__(self):
            self.active = 0
            self.peak = 0

        async def generate(self, prompt):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return (
                AuditDecision(
                    classification="inconclusive",
                    justification="Insufficient synthetic evidence.",
                ),
                100,
                50,
            )

    provider = ConcurrentProvider()
    settings = Settings(
        _env_file=None,
        vertex_ai_enabled=True,
        vertex_ai_approved=True,
        vertex_ai_input_cost_per_million_usd=1,
        vertex_ai_output_cost_per_million_usd=1,
        vertex_ai_max_cost_per_audit_usd=1,
        vertex_ai_max_concurrency=1,
    )
    outcomes = asyncio.run(
        VertexAuditService(settings, provider).run_batch(
            [audit_input(), audit_input()], mode="vertex"
        )
    )
    assert len(outcomes) == 2
    assert provider.peak == 1
