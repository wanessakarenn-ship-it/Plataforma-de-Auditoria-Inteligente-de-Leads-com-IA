from backend.app.classification import audit_required, classify, contact_eligibility


def test_classifies_requested_statuses_and_phases():
    cases = [
        ("Desqualificado", "", "disqualified"),
        ("Perdido", "", "lost"),
        ("Qualificado", "Perdido", "qualified_lost"),
        ("", "Pesquisa", "research"),
        ("", "Em Conexão", "connecting"),
        ("Levantada de Mão", "", "hand_raised"),
        ("Nutrição", "", "nurture"),
        ("", "Negociação", "commercial_negotiation"),
        ("Ganho", "", "won"),
        ("other", "other", "unknown"),
    ]
    for status, phase, expected in cases:
        assert classify(status, phase) == expected


def test_audit_and_contact_queues_are_separate_and_require_consent_and_approval():
    assert audit_required("lost")
    assert not audit_required("won")
    assert contact_eligibility("hand_raised", True, None, False, False) == (
        False,
        "permission_not_granted",
    )
    assert contact_eligibility("hand_raised", True, "granted", False, False) == (
        False,
        "approval_required",
    )
    assert contact_eligibility("hand_raised", True, "granted", True, False) == (
        True,
        "eligible_for_manual_review_only",
    )
    assert contact_eligibility("hand_raised", True, "granted", True, True) == (
        False,
        "suppressed",
    )
