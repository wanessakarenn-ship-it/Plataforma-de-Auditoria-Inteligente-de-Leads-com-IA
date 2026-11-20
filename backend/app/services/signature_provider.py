from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


SignatureStatus = Literal["pending", "sent", "signed", "declined", "expired", "cancelled"]


@dataclass(frozen=True)
class SignatureEnvelopeRequest:
    tenant_id: str
    idempotency_key: str
    document_reference: str
    signer_references: tuple[str, ...]


@dataclass(frozen=True)
class SignatureEnvelope:
    provider_reference: str
    status: SignatureStatus
    signature_url: str | None
    updated_at: datetime


class ElectronicSignatureProvider(Protocol):
    async def create_envelope(self, request: SignatureEnvelopeRequest) -> SignatureEnvelope: ...

    async def get_envelope(self, provider_reference: str) -> SignatureEnvelope: ...
