import unicodedata


STATES = {
    "eligibility_pending": "Elegibilidade pendente",
    "contact_approved": "Contato aprovado",
    "commercial_confirmation": "Confirmação da situação comercial",
    "interest_identified": "Interesse identificado",
    "qualification": "Qualificação",
    "proposal_preparation": "Proposta em preparação",
    "proposal_approved": "Proposta aprovada",
    "negotiation": "Negociação",
    "documentation_pending": "Documentação pendente",
    "contract_validation": "Contrato em validação",
    "awaiting_signature": "Aguardando assinatura",
    "contract_signed_simulated": "Contrato simulado assinado",
    "post_sale": "Pós-venda",
    "opt_out": "Opt-out",
    "no_interest": "Sem interesse",
    "blocked": "Bloqueado",
    "suspended": "Suspenso",
    "human_transfer": "Transferência humana",
}

SCENARIOS = {
    "no_interest": {
        "title": "Lead realmente sem interesse",
        "initial_state": "commercial_confirmation",
    },
    "incorrect_disqualification": {
        "title": "Lead desqualificado incorretamente",
        "initial_state": "eligibility_pending",
    },
    "resume_negotiation": {
        "title": "Lead interessado em retomar a negociação",
        "initial_state": "commercial_confirmation",
    },
    "proposal_questions": {
        "title": "Lead com dúvidas sobre a proposta",
        "initial_state": "proposal_approved",
    },
    "unauthorized_discount": {
        "title": "Lead solicitando desconto não autorizado",
        "initial_state": "negotiation",
    },
    "human_service": {
        "title": "Lead solicitando atendimento humano",
        "initial_state": "qualification",
    },
    "contact_refusal": {
        "title": "Lead recusando o contato",
        "initial_state": "contact_approved",
    },
    "accepts_proposal": {
        "title": "Lead aceitando uma proposta simulada",
        "initial_state": "proposal_preparation",
    },
    "awaiting_signature": {
        "title": "Lead aguardando assinatura",
        "initial_state": "awaiting_signature",
    },
    "contract_signed": {
        "title": "Lead com contrato simulado assinado",
        "initial_state": "contract_signed_simulated",
    },
}

TRANSITIONS = {
    "confirm_contact": {"eligibility_pending": "contact_approved"},
    "confirm_commercial_status": {"contact_approved": "commercial_confirmation"},
    "confirm_interest": {"commercial_confirmation": "interest_identified"},
    "start_qualification": {"interest_identified": "qualification"},
    "prepare_proposal": {"qualification": "proposal_preparation"},
    "approve_proposal": {"proposal_preparation": "proposal_approved"},
    "start_negotiation": {"proposal_approved": "negotiation"},
    "request_documents": {"negotiation": "documentation_pending"},
    "prepare_contract": {"documentation_pending": "contract_validation"},
    "create_contract_link": {"contract_validation": "awaiting_signature"},
    "confirm_contract_signed": {"awaiting_signature": "contract_signed_simulated"},
    "start_post_sale": {"contract_signed_simulated": "post_sale"},
}

ACTION_LABELS = {
    **{key: key.replace("_", " ").capitalize() for key in TRANSITIONS},
    "record_no_interest": "Registrar ausência de interesse",
    "transfer_human": "Transferir para atendimento humano",
    "opt_out": "Registrar opt-out",
    "block": "Bloquear jornada",
    "suspend": "Suspender jornada",
    "resume": "Retomar jornada",
}

SENSITIVE_ACTIONS = {
    "confirm_contact",
    "prepare_proposal",
    "approve_proposal",
    "prepare_contract",
    "create_contract_link",
    "confirm_contract_signed",
}

TERMINAL_STATES = {"opt_out", "no_interest", "blocked", "post_sale"}
ACTIVE_STATES = set(STATES) - TERMINAL_STATES - {"suspended", "human_transfer"}


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def available_actions(state: str) -> list[str]:
    actions = [action for action, origins in TRANSITIONS.items() if state in origins]
    if state in ACTIVE_STATES:
        actions.extend(
            ("record_no_interest", "transfer_human", "block", "suspend", "opt_out")
        )
    elif state == "suspended":
        actions.extend(("transfer_human", "block", "resume", "opt_out"))
    elif state == "human_transfer":
        actions.extend(("block", "opt_out"))
    elif state != "opt_out":
        actions.append("opt_out")
    return actions


def transition_target(state: str, action: str, previous_state: str | None = None) -> str:
    if state == "opt_out" and action != "opt_out":
        raise ValueError("Opt-out tem prioridade absoluta e impede qualquer avanço.")
    if action == "opt_out":
        return "opt_out"
    if action == "record_no_interest":
        if state not in ACTIVE_STATES:
            raise ValueError("A jornada não permite esta transição.")
        return "no_interest"
    if action == "transfer_human":
        if state in {"opt_out", "no_interest", "blocked", "post_sale"}:
            raise ValueError("A jornada não permite esta transição.")
        return "human_transfer"
    if action == "block":
        if state in TERMINAL_STATES:
            raise ValueError("A jornada não permite esta transição.")
        return "blocked"
    if action == "suspend":
        if state not in ACTIVE_STATES:
            raise ValueError("Somente jornadas ativas podem ser suspensas.")
        return "suspended"
    if action == "resume":
        if state != "suspended" or previous_state not in ACTIVE_STATES:
            raise ValueError("Não há uma etapa anterior válida para retomar.")
        return previous_state
    target = TRANSITIONS.get(action, {}).get(state)
    if target is None:
        raise ValueError("A transição não é permitida a partir do estado atual.")
    return target


def _draft_response_body(
    message: str, state: str, scenario_key: str, knowledge: list[dict]
) -> tuple[str, str | None]:
    normalized = normalize_text(message)
    opt_out_terms = (
        "nao quero receber",
        "nao me contate",
        "nao entre em contato",
        "nao quero contato",
        "nao quero mais contato",
        "pare de me contatar",
        "remova meu contato",
        "cancele o contato",
        "recuso o contato",
        "nao aceito contato",
        "opt out",
    )
    if any(term in normalized for term in opt_out_terms):
        return (
            "Entendi, e agradeço por me avisar. Seu pedido de não receber contato foi "
            "registrado nesta simulação. Nenhuma mensagem foi enviada.",
            "opt_out",
        )
    if any(
        term in normalized
        for term in ("atendente", "humano", "pessoa real", "falar com alguem")
    ):
        return (
            "Claro, vou encaminhar sua solicitação para uma pessoa da equipe. "
            "Nada será enviado ou alterado fora desta simulação.",
            "transfer_human",
        )
    if any(
        term in normalized
        for term in ("desconto", "abaixar o preco", "reduzir o preco", "menor valor")
    ):
        return (
            "Compreendo sua pergunta. Não posso confirmar descontos, preços ou condições "
            "sem aprovação comercial. Vou deixar isso para revisão humana.",
            None,
        )
    if scenario_key == "incorrect_disqualification" and any(
        term in normalized
        for term in (
            "desqualificado incorretamente",
            "classificacao incorreta",
            "fui desqualificado",
        )
    ):
        return (
            "Sinto muito pela possível classificação incorreta. Vou encaminhar o caso "
            "para uma pessoa revisar as evidências antes de qualquer contato comercial.",
            "transfer_human",
        )
    if scenario_key == "no_interest" and any(
        term in normalized
        for term in (
            "nao tenho interesse",
            "sem interesse",
            "nao quero seguir",
            "nao quero continuar",
        )
    ):
        return (
            "Obrigada por me contar. Vou respeitar sua decisão e registrar que não há "
            "interesse, sem insistir.",
            "record_no_interest",
        )
    if scenario_key == "resume_negotiation" and any(
        term in normalized for term in ("retomar", "quero negociar", "tenho interesse")
    ):
        return (
            "Que bom que deseja retomar. Vou registrar seu interesse e seguir apenas "
            "com informações aprovadas, sem presumir condições comerciais.",
            "confirm_interest" if state == "commercial_confirmation" else None,
        )
    if any(term in normalized for term in ("aceito a proposta", "aceito", "vamos fechar")):
        return (
            "Obrigada por confirmar. Vou registrar sua resposta para aprovação comercial "
            "humana; esta simulação não cria uma contratação.",
            None,
        )
    if any(
        term in normalized for term in ("proposta", "preco", "valor", "condicoes")
    ):
        if knowledge:
            titles = ", ".join(item["title"] for item in knowledge[:3])
            return (
                f"Com cuidado, encontrei conteúdo aprovado relacionado: {titles}. "
                "Uma pessoa da equipe pode confirmar os detalhes da proposta com você.",
                None,
            )
        return (
            "Entendo suas dúvidas. Não encontrei conteúdo aprovado suficiente para "
            "responder com segurança; vou solicitar revisão humana e não inventar valores.",
            "transfer_human",
        )
    if scenario_key == "awaiting_signature":
        return (
            "Estou acompanhando esta etapa simulada. A assinatura ainda precisa ser "
            "confirmada pelo fluxo autorizado; nenhum link real foi criado.",
            None,
        )
    if scenario_key == "contract_signed":
        return (
            "Registro apenas a confirmação fictícia deste cenário. Não existe contrato "
            "juridicamente válido nem contratação real nesta simulação.",
            None,
        )
    return (
        "Obrigada por compartilhar. Sou a Karen, assistente virtual, e vou seguir com "
        "calma usando apenas informações aprovadas. Se preferir, posso encaminhar "
        "a conversa para uma pessoa.",
        None,
    )


def draft_response(
    message: str, state: str, scenario_key: str, knowledge: list[dict]
) -> tuple[str, str | None]:
    response, suggested_action = _draft_response_body(message, state, scenario_key, knowledge)
    if "assistente virtual" not in normalize_text(response):
        response = f"Sou Karen, assistente virtual. {response}"
    return response, suggested_action


def evaluate_response(response: str, knowledge: list[dict]) -> dict:
    normalized = normalize_text(response)
    transparent = "assistente virtual" in normalized
    no_unsupported_terms = not any(
        phrase in normalized for phrase in ("desconto de", "preco garantido", "contrato valido")
    )
    return {
        "method": "deterministic_safety_checks",
        "kindness": (
            5
            if any(term in normalized for term in ("obrigada", "entendo", "com cuidado"))
            else 4
        ),
        "compliance": 5 if transparent and no_unsupported_terms else 2,
        "accuracy": (
            5
            if no_unsupported_terms
            and (knowledge or "nao encontrei" in normalized or "simulacao" in normalized)
            else 4
        ),
        "notes": [
            "Execução local determinística; não é avaliação por modelo.",
            "Nenhuma mensagem externa foi enviada.",
        ],
    }
