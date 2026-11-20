"use client";

import { FormEvent, useEffect, useState } from "react";
import { fetchWithFirebaseToken } from "../lib/firebase";

type AgentDraft = {
  name: string;
  purpose: string;
  description: string;
  process_role: string;
  model_id: "local-simulated";
  instructions: string;
  system_prompt: string;
  decision_criteria: string;
  safety_rules: string;
  human_handoff: string;
  temperature: number;
  max_output_tokens: number;
  max_cost_usd: number;
  knowledge_requires_approval: boolean;
};

type Agent = AgentDraft & {
  id: string;
  publication_state: "draft" | "approved" | "published";
  is_active: boolean;
  execution_enabled: false;
  current_version: number;
};

type AgentVersion = {
  version_number: number;
  snapshot: Omit<AgentDraft, "max_cost_usd"> & { max_cost_usd: number | string };
  created_by_uid: string;
  created_at: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

function blankAgent(): AgentDraft {
  return {
    name: "",
    purpose: "",
    description: "",
    process_role: "",
    model_id: "local-simulated",
    instructions: "",
    system_prompt: "",
    decision_criteria: "",
    safety_rules: "",
    human_handoff: "",
    temperature: 0.2,
    max_output_tokens: 512,
    max_cost_usd: 0,
    knowledge_requires_approval: true,
  };
}

async function readResponse(response: Response) {
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail ?? "Não foi possível concluir a operação.");
  }
  return body;
}

export default function AIStudio() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [draft, setDraft] = useState<AgentDraft>(blankAgent);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, AgentVersion[]>>({});
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function loadAgents() {
    setLoading(true);
    setError("");
    try {
      const response = await fetchWithFirebaseToken(`${API_URL}/studio/agents`, {
        cache: "no-store",
      });
      setAgents(await readResponse(response));
      setLoadFailed(false);
    } catch (loadError) {
      setLoadFailed(true);
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Falha ao carregar o Estúdio de IA.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAgents();
  }, []);

  async function createInitialTemplates() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetchWithFirebaseToken(
        `${API_URL}/studio/agents/initial-templates`,
        { method: "POST" },
      );
      setAgents(await readResponse(response));
      setNotice("Modelos iniciais criados como rascunhos; nenhum agente executa inferência.");
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Falha ao criar modelos.");
    } finally {
      setBusy(false);
    }
  }

  async function saveAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const path = editingId
        ? `${API_URL}/studio/agents/${editingId}`
        : `${API_URL}/studio/agents`;
      const response = await fetchWithFirebaseToken(path, {
        method: editingId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      const saved = await readResponse(response);
      setNotice(`Versão ${saved.current_version} salva como rascunho.`);
      setEditingId(null);
      setDraft(blankAgent());
      await loadAgents();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Falha ao salvar o agente.");
    } finally {
      setBusy(false);
    }
  }

  async function updatePublication(agent: Agent, action: "approve" | "publish" | "unpublish") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetchWithFirebaseToken(
        `${API_URL}/studio/agents/${agent.id}/publication`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action }),
        },
      );
      await readResponse(response);
      setNotice(
        action === "approve"
          ? "Aprovação humana registrada."
          : action === "publish"
            ? "Configuração publicada; execução continua desativada."
            : "Publicação removida.",
      );
      await loadAgents();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Falha na publicação.");
    } finally {
      setBusy(false);
    }
  }

  async function updateActivation(agent: Agent, isActive: boolean) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetchWithFirebaseToken(
        `${API_URL}/studio/agents/${agent.id}/activation`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_active: isActive }),
        },
      );
      await readResponse(response);
      setNotice(
        isActive
          ? "Agente habilitado para o futuro ambiente de simulação. Execução real segue desativada."
          : "Agente desativado.",
      );
      await loadAgents();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Falha ao alterar o estado.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleVersions(agentId: string) {
    setError("");
    try {
      if (versions[agentId]) {
        setVersions((current) => {
          const next = { ...current };
          delete next[agentId];
          return next;
        });
        return;
      }
      const response = await fetchWithFirebaseToken(
        `${API_URL}/studio/agents/${agentId}/versions`,
        { cache: "no-store" },
      );
      const result = await readResponse(response);
      setVersions((current) => ({ ...current, [agentId]: result }));
    } catch (versionError) {
      setError(versionError instanceof Error ? versionError.message : "Falha ao carregar versões.");
    }
  }

  function editAgent(agent: Agent) {
    const {
      id: _id,
      publication_state: _publicationState,
      is_active: _isActive,
      execution_enabled: _executionEnabled,
      current_version: _currentVersion,
      ...agentDraft
    } = agent;
    setEditingId(agent.id);
    setDraft(agentDraft);
    setError("");
    setNotice("");
  }

  return (
    <div className="studio-layout">
      <section className="panel studio-safety">
        <div>
          <strong>Execução externa desativada</strong>
          <p>Este incremento salva configurações e versões; não chama modelos nem envia mensagens.</p>
        </div>
        <span className="badge badge-amber">Somente simulação local</span>
      </section>

      {(error || notice) && (
        <div className={`alert ${error ? "alert-error" : "alert-success"}`} role={error ? "alert" : "status"}>
          <span>{error ? "!" : "✓"}</span>
          <div>{error || notice}</div>
          <button onClick={() => { setError(""); setNotice(""); }} aria-label="Fechar">
            ×
          </button>
        </div>
      )}

      <div className="studio-toolbar">
        <div>
          <h2>Agentes por organização</h2>
          <p>Prompts são versionados; publicar exige aprovação humana.</p>
        </div>
        <div className="studio-toolbar-actions">
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={() => void createInitialTemplates()}
          >
            Criar modelos iniciais
          </button>
          <button
            className="primary-button"
            type="button"
            onClick={() => {
              setEditingId(null);
              setDraft(blankAgent());
              setError("");
              setNotice("");
            }}
          >
            Novo agente
          </button>
        </div>
      </div>

      {loading ? (
        <section className="panel"><div className="empty-state">Carregando agentes autorizados…</div></section>
      ) : (
        <div className="studio-grid">
          <section className="studio-agent-list">
            {loadFailed ? (
              <section className="panel">
                <div className="empty-state">
                  Não foi possível consultar os agentes deste tenant. Verifique a API e tente novamente.
                  <div><button className="secondary-button" type="button" onClick={() => void loadAgents()}>Tentar novamente</button></div>
                </div>
              </section>
            ) : agents.length === 0 ? (
              <section className="panel">
                <div className="empty-state">
                  Nenhum agente cadastrado neste tenant. Crie os dois modelos iniciais ou comece um rascunho.
                </div>
              </section>
            ) : agents.map((agent) => (
              <article className="panel studio-agent-card" key={agent.id}>
                <div className="studio-agent-heading">
                  <div>
                    <h3>{agent.name}</h3>
                    <p>{agent.purpose}</p>
                  </div>
                  <span className={`badge ${agent.publication_state === "published" ? "badge-green" : "badge-amber"}`}>
                    {agent.publication_state === "draft"
                      ? "Rascunho"
                      : agent.publication_state === "approved"
                        ? "Aprovado"
                        : "Publicado"}
                  </span>
                </div>
                <div className="studio-agent-meta">
                  <span>v{agent.current_version}</span>
                  <span>{agent.model_id}</span>
                  <span>{agent.is_active ? "Ativo para simulação" : "Inativo"}</span>
                  <span>Execução real: desativada</span>
                </div>
                <div className="studio-actions">
                  <button className="secondary-button" type="button" onClick={() => editAgent(agent)}>
                    Editar
                  </button>
                  <button className="secondary-button" type="button" onClick={() => void toggleVersions(agent.id)}>
                    {versions[agent.id] ? "Ocultar versões" : "Versões"}
                  </button>
                  {agent.publication_state === "draft" && (
                    <button className="secondary-button" type="button" disabled={busy} onClick={() => void updatePublication(agent, "approve")}>
                      Aprovar
                    </button>
                  )}
                  {agent.publication_state === "approved" && (
                    <button className="secondary-button" type="button" disabled={busy} onClick={() => void updatePublication(agent, "publish")}>
                      Publicar
                    </button>
                  )}
                  {agent.publication_state === "published" && (
                    <>
                      <button className="secondary-button" type="button" disabled={busy} onClick={() => void updatePublication(agent, "unpublish")}>
                        Despublicar
                      </button>
                      <button className="secondary-button" type="button" disabled={busy} onClick={() => void updateActivation(agent, !agent.is_active)}>
                        {agent.is_active ? "Desativar" : "Ativar"}
                      </button>
                    </>
                  )}
                </div>
                {versions[agent.id] && (
                  <ol className="studio-version-list">
                    {versions[agent.id].map((version) => (
                      <li key={version.version_number}>
                        <strong>Versão {version.version_number}</strong>
                        <span>{new Date(version.created_at).toLocaleString("pt-BR")}</span>
                        <p>{version.snapshot.name} · {version.snapshot.model_id}</p>
                      </li>
                    ))}
                  </ol>
                )}
              </article>
            ))}
          </section>

          <form className="panel studio-form" onSubmit={(event) => void saveAgent(event)}>
            <div className="panel-header">
              <div>
                <h2>{editingId ? "Editar agente" : "Configurar agente"}</h2>
                <p>{editingId ? "Salvar cria uma nova versão e exige nova aprovação." : "Novos agentes começam como rascunho inativo."}</p>
              </div>
            </div>
            <div className="studio-form-fields">
              <label>Nome<input required maxLength={120} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
              <label>Finalidade<input required maxLength={1000} value={draft.purpose} onChange={(event) => setDraft({ ...draft, purpose: event.target.value })} /></label>
              <label>Descrição<textarea maxLength={3000} rows={2} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
              <label>Papel no processo comercial<input required maxLength={120} value={draft.process_role} onChange={(event) => setDraft({ ...draft, process_role: event.target.value })} /></label>
              <label>Modelo selecionado<select value={draft.model_id} onChange={() => setDraft({ ...draft, model_id: "local-simulated" })}><option value="local-simulated">Simulado local (sem chamadas externas)</option></select></label>
              <label>Instruções<textarea required maxLength={6000} rows={3} value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} /></label>
              <label>Prompt de sistema<textarea required maxLength={12000} rows={4} value={draft.system_prompt} onChange={(event) => setDraft({ ...draft, system_prompt: event.target.value })} /></label>
              <label>Critérios de decisão<textarea required maxLength={6000} rows={3} value={draft.decision_criteria} onChange={(event) => setDraft({ ...draft, decision_criteria: event.target.value })} /></label>
              <label>Regras de segurança<textarea required maxLength={6000} rows={3} value={draft.safety_rules} onChange={(event) => setDraft({ ...draft, safety_rules: event.target.value })} /></label>
              <label>Condições de transferência humana<textarea required maxLength={3000} rows={2} value={draft.human_handoff} onChange={(event) => setDraft({ ...draft, human_handoff: event.target.value })} /></label>
              <div className="studio-parameter-grid">
                <label>Temperatura<input type="number" min="0" max="1.5" step="0.1" value={draft.temperature} onChange={(event) => setDraft({ ...draft, temperature: Number(event.target.value) })} /></label>
                <label>Limite de tokens<input type="number" min="1" max="4096" step="1" value={draft.max_output_tokens} onChange={(event) => setDraft({ ...draft, max_output_tokens: Number(event.target.value) })} /></label>
                <label>Limite de custo (USD)<input type="number" min="0" max="10" step="0.0001" value={draft.max_cost_usd} onChange={(event) => setDraft({ ...draft, max_cost_usd: Number(event.target.value) })} /></label>
              </div>
              <label className="studio-checkbox">
                <input
                  type="checkbox"
                  checked={draft.knowledge_requires_approval}
                  onChange={(event) => setDraft({
                    ...draft,
                    knowledge_requires_approval: event.target.checked,
                  })}
                />
                Exigir aprovação do conteúdo associado antes de publicar
              </label>
              <div className="studio-form-actions">
                <button className="primary-button" type="submit" disabled={busy}>
                  {busy ? "Salvando…" : editingId ? "Salvar nova versão" : "Criar rascunho"}
                </button>
                {editingId && (
                  <button className="secondary-button" type="button" onClick={() => { setEditingId(null); setDraft(blankAgent()); }}>
                    Cancelar edição
                  </button>
                )}
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
