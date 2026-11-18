import re
import unicodedata


def normalize(value: str | None) -> str:
    if not value:
        return ""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


STATUS_RULES = {
    "disqualified": ("disqualified", "disqualificado", "desqualificado"),
    "lost": ("lost", "perdido", "perdida", "closed lost"),
    "won": ("won", "ganho", "ganha", "closed won"),
    "qualified_lost": ("qualified lost", "qualificado perdido", "qualificado perdida"),
    "hand_raised": ("hand raised", "levantada de mao", "levantou a mao", "mql"),
    "commercial_negotiation": (
        "negotiation",
        "negociacao",
        "proposal",
        "proposta",
        "contract",
        "contrato",
    ),
    "nurture": ("nurture", "nutricao", "nurturing"),
    "connecting": ("connected", "em conexao", "contacted", "contatado"),
    "research": ("research", "pesquisa", "new", "novo"),
}

PHASE_RULES = {
    "won": ("won", "ganho", "ganha", "closed won"),
    "lost": ("lost", "perdido", "perdida", "closed lost"),
    "disqualified": ("disqualified", "desqualificado", "desqualificada"),
    "commercial_negotiation": ("negotiation", "negociacao", "proposal", "proposta"),
    "hand_raised": ("hand raised", "levantada de mao", "levantou a mao"),
    "nurture": ("nurture", "nutricao"),
    "connecting": ("connection", "conexao", "contacted", "contato"),
    "research": ("research", "pesquisa", "qualification", "qualificacao"),
}


def classify(status: str | None, phase: str | None) -> str:
    normalized_status = normalize(status)
    normalized_phase = normalize(phase)
    if "qualif" in normalized_status and any(
        normalize(value) in normalized_phase for value in PHASE_RULES["lost"]
    ):
        return "qualified_lost"
    for category, values in STATUS_RULES.items():
        if any(normalize(value) in normalized_status for value in values):
            return category
    for category, values in PHASE_RULES.items():
        if any(normalize(value) in normalized_phase for value in values):
            return category
    return "unknown"


def audit_required(classification: str) -> bool:
    return classification != "won"


CONTACT_CANDIDATE_CLASSIFICATIONS = {
    "research",
    "connecting",
    "hand_raised",
    "nurture",
    "commercial_negotiation",
    "qualified_lost",
}


def contact_eligibility(
    classification: str,
    has_valid_contact: bool,
    consent_status: str | None,
    approved: bool,
    suppressed: bool,
) -> tuple[bool, str]:
    if classification not in CONTACT_CANDIDATE_CLASSIFICATIONS:
        return False, "not_a_contact_candidate"
    if not has_valid_contact:
        return False, "missing_valid_contact"
    if consent_status != "granted":
        return False, "permission_not_granted"
    if suppressed:
        return False, "suppressed"
    if not approved:
        return False, "approval_required"
    return True, "eligible_for_manual_review_only"
