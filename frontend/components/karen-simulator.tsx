"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { fetchWithFirebaseToken, getBackendUnavailableReason } from "../lib/firebase";

type Scenario = { key: string; title: string };
type AgentConfig = {
  id: string;
  name: string;
  current_version: number;
  publication_state: string;
  is_active: boolean;
  execution_enabled: false;
};
type SimEvent = {
  id: string;
  event_type: string;
  from_state: string | null;
  to_state: string | null;
  message: string | null;
  decision: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  evaluation: Record<string, unknown>;
  actor_uid: string;
  created_at: string;
};
type Simulation = {
  id: string;
  scenario_key: string;
  scenario_title: string;
  state: string;
  state_label: string;
  available_actions: string[];
  agent_id: string;
  created_at: string;
  updated_at: string;
  synthetic_data_only: true;
  outbound_enabled: false;
  events: SimEvent[] | null;
};
type Config = {
  configured: boolean;
  agent: AgentConfig | null;
  scenarios: Scenario[];
  states: Array<{ key: string; label: string }>;
  sensitive_actions: string[];
  action_labels: Record<string, string>;
  outbound_enabled: false;
  contract_integration: {
    status: string;
    provider: string | null;
    document_generation: string;
  };
};

const API_URL = process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ?? "";
const previewScenarios = [
  "Lead realmente sem interesse",
  "Lead desqualificado incorretamente",
  "Lead interessado em retomar a negociação",
  "Lead com dúvidas sobre a proposta",
  "Lead solicitando desconto não autorizado",
  "Lead solicitando atendimento humano",
  "Lead recusando o contato",
  "Lead aceitando uma proposta simulada",
  "Lead aguardando assinatura",
  "Lead com contrato simulado assinado",
];

async function readResponse<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? "Não foi possível concluir a operação.");
  return body as T;
}

export default function KarenSimulator({
  onOpenStudio,
}: {
  onOpenStudio?: () => void;
}) {
  const [config, setConfig] = useState<Config | null>(null);
  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [selected, setSelected] = useState<Simulation | null>(null);
  const [scenarioKey, setScenarioKey] = useState("");
  const [message, setMessage] = useState("");
  const [approvalAction, setApprovalAction] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    const unavailableReason = getBackendUnavailableReason();
    if (unavailableReason) {
      setLoading(false);
      setError(unavailableReason);
      return;
    }
    try {
      const [configResponse, simulationsResponse] = await Promise.all([
        fetchWithFirebaseToken(`${API_URL}/karen/config`, { cache: "no-store" }),
        fetchWithFirebaseToken(`${API_URL}/karen/simulations`, { cache: "no-store" }),
      ]);
      const [nextConfig, nextSimulations] = await Promise.all([
        readResponse<Config>(configResponse),
        readResponse<Simulation[]>(simulationsResponse),
      ]);
      setConfig(nextConfig);
      setSimulations(nextSimulations);
      setScenarioKey((current) => current || nextConfig.scenarios[0]?.key || "");
      if (selected) {
        const current = nextSimulations.find((item) => item.id === selected.id);
        if (current) await loadSimulation(current.id);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Falha ao carregar o simulador.");
    } finally {
      setLoading(false);
    }
  }

  async function loadSimulation(id: string) {
    const response = await fetchWithFirebaseToken(
      `${API_URL}/karen/simulations/${id}`,
      { cache: "no-store" },
    );
    setSelected(await readResponse<Simulation>(response));
  }

  useEffect(() => {
    void load();
  }, []);

  const availableApprovals = useMemo(
    () =>
      (config?.sensitive_actions ?? []).filter((action) =>
        selected?.available_actions.includes(action),
      ),
    [config, selected],
  );

  const backendUnavailableReason = getBackendUnavailableReason();
  if (backendUnavailableReason) {
    return (
      <div className="karen-layout">
        <div className="alert alert-error" role="status">{backendUnavailableReason}</div>
        <section className="panel karen-scenarios">
          <div className="panel-header">
            <div>
              <h2>Cenários disponíveis para visualização</h2>
              <p>Somente exemplos sintéticos; iniciar ou registrar simulações exige o backend.</p>
            </div>
          </div>
          <ol className="preview-scenarios">
            {previewScenarios.map((scenario) => <li key={scenario}>{scenario}</li>)}
          </ol>
        </section>
      </div>
    );
  }

  async function createSimulation() {
    if (!scenarioKey) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetchWithFirebaseToken(`${API_URL}/karen/simulations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_key: scenarioKey }),
      });
      const created = await readResponse<Simulation>(response);
      setSelected(created);
      await refreshList();
      setNotice("Cenário fictício iniciado. Nenhuma mensagem externa foi enviada.");
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Falha ao iniciar cenário.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshList() {
    const response = await fetchWithFirebaseToken(`${API_URL}/karen/simulations`, {
      cache: "no-store",
    });
    setSimulations(await readResponse<Simulation[]>(response));
  }

  async function runMutation(path: string, method: "POST", payload: object) {
    if (!selected) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetchWithFirebaseToken(`${API_URL}${path}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await readResponse<Simulation>(response);
      setSelected(result);
      await refreshList();
      return result;
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Falha na simulação.");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function submitTurn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !message.trim()) return;
    const result = await runMutation(
      `/karen/simulations/${selected.id}/turns`,
      "POST",
      { message: message.trim() },
    );
    if (result) {
      setMessage("");
      setNotice("Rascunho de resposta registrado no histórico; nenhum envio foi realizado.");
    }
  }

  async function recordApproval() {
    if (!selected || !approvalAction) return;
    const result = await runMutation(
      `/karen/simulations/${selected.id}/approvals`,
      "POST",
      { action: approvalAction },
    );
    if (result) {
      setApprovalAction("");
      setNotice("Aprovação humana registrada para esta etapa e ação.");
    }
  }

  if (loading) {
    return <section className="panel"><div className="empty-state">Carregando o simulador da Karen…</div></section>;
  }

  return (
    <div className="karen-layout">
      <section className="panel karen-safety">
        <div>
          <strong>Simulação local · sem integração ou envio</strong>
          <p>Use somente cenários e textos fictícios. Contato externo, CRM e contratos reais permanecem desativados.</p>
        </div>
        <span className="badge badge-amber">Dados sintéticos</span>
      </section>

      {(error || notice) && (
        <div className={`alert ${error ? "alert-error" : "alert-success"}`} role={error ? "alert" : "status"}>
          <span>{error ? "!" : "✓"}</span>
          <div>{error || notice}</div>
          <button onClick={() => { setError(""); setNotice(""); }} aria-label="Fechar">×</button>
        </div>
      )}

      {!config?.configured ? (
        <section className="panel empty-section">
          <div className="large-empty-icon">♡</div>
          <h2>Karen ainda não foi cadastrada</h2>
          <p>Crie o rascunho inativo no Estúdio de IA. O prompt é versionado e a publicação exige aprovação humana.</p>
          {onOpenStudio && (
            <button className="primary-button" type="button" onClick={onOpenStudio}>
              Abrir Estúdio de IA
            </button>
          )}
        </section>
      ) : (
        <>
          <section className="panel karen-agent-summary">
            <div>
              <strong>{config.agent?.name} · versão {config.agent?.current_version}</strong>
              <p>{config.agent?.publication_state === "draft" ? "Rascunho inativo" : config.agent?.publication_state} · execução externa desativada</p>
            </div>
            <span className="badge badge-green">Assistente virtual</span>
          </section>

          <div className="karen-workspace">
            <aside className="panel karen-scenarios">
              <div className="panel-header">
                <div><h2>Cenários fictícios</h2><p>Sem vínculo com leads reais</p></div>
              </div>
              <label className="karen-create-form">
                Novo cenário
                <select value={scenarioKey} onChange={(event) => setScenarioKey(event.target.value)}>
                  {config.scenarios.map((scenario) => (
                    <option key={scenario.key} value={scenario.key}>{scenario.title}</option>
                  ))}
                </select>
                <button className="primary-button" type="button" disabled={busy} onClick={() => void createSimulation()}>
                  Iniciar simulação
                </button>
              </label>
              <div className="karen-simulation-list">
                {!simulations.length ? (
                  <div className="empty-state compact">Ainda não há simulações nesta organização.</div>
                ) : simulations.map((simulation) => (
                  <button
                    className={`karen-simulation-row ${selected?.id === simulation.id ? "active" : ""}`}
                    key={simulation.id}
                    type="button"
                    onClick={() => void loadSimulation(simulation.id).catch((loadError: unknown) =>
                      setError(loadError instanceof Error ? loadError.message : "Falha ao abrir simulação."),
                    )}
                  >
                    <strong>{simulation.scenario_title}</strong>
                    <span>{simulation.state_label}</span>
                  </button>
                ))}
              </div>
            </aside>

            <div className="karen-detail">
              {!selected ? (
                <section className="panel empty-state">Inicie ou selecione um cenário para acompanhar a jornada.</section>
              ) : (
                <>
                  <section className="panel karen-state-card">
                    <div>
                      <span className="eyebrow">{selected.scenario_title}</span>
                      <h2>{selected.state_label}</h2>
                    </div>
                    <span className="badge badge-amber">Somente simulação</span>
                  </section>

                  <section className="panel karen-conversation">
                    <div className="panel-header">
                      <div><h2>Conversa e trilha de auditoria</h2><p>{selected.events?.length ?? 0} eventos preservados</p></div>
                    </div>
                    {!selected.events?.length ? (
                      <div className="empty-state compact">Nenhuma interação registrada.</div>
                    ) : (
                      <ol className="karen-event-list">
                        {selected.events.map((item) => (
                          <li key={item.id}>
                            <div className="karen-event-heading">
                              <strong>{eventLabel(item.event_type)}</strong>
                              <time>{new Date(item.created_at).toLocaleString("pt-BR")}</time>
                            </div>
                            {item.message && <p className="karen-transcript">{item.message}</p>}
                            {(item.from_state || item.to_state) && (
                              <p className="karen-transition">
                                {stateLabel(config, item.from_state)} → {stateLabel(config, item.to_state)}
                              </p>
                            )}
                            {typeof item.decision.simulated_link === "string" && (
                              <p className="karen-fake-link">Link fictício: <code>{item.decision.simulated_link}</code></p>
                            )}
                            {Object.keys(item.evaluation).length > 0 && (
                              <p className="karen-evaluation">
                                Gentileza {String(item.evaluation.kindness)}/5 · Conformidade {String(item.evaluation.compliance)}/5 · Precisão {String(item.evaluation.accuracy)}/5
                              </p>
                            )}
                            <details>
                              <summary>Evidências e decisão</summary>
                              <pre>{JSON.stringify({ decision: item.decision, evidence: item.evidence, evaluation: item.evaluation }, null, 2)}</pre>
                            </details>
                          </li>
                        ))}
                      </ol>
                    )}
                    {["opt_out", "no_interest", "blocked", "human_transfer"].includes(selected.state) ? (
                      <p className="karen-turn-closed">
                        {selected.state === "human_transfer"
                          ? "Conversa transferida: novos turnos de Karen estão bloqueados."
                          : "Jornada encerrada ou bloqueada: não é possível registrar novos turnos."}
                      </p>
                    ) : (
                      <form className="karen-turn-form" onSubmit={(event) => void submitTurn(event)}>
                        <label htmlFor="karen-message">Texto fictício do lead</label>
                        <textarea
                          id="karen-message"
                          maxLength={2000}
                          rows={3}
                          value={message}
                          onChange={(event) => setMessage(event.target.value)}
                          placeholder="Ex.: Tenho interesse em retomar a conversa."
                        />
                        <button className="primary-button" type="submit" disabled={busy || !message.trim()}>
                          Registrar turno simulado
                        </button>
                      </form>
                    )}
                  </section>

                  <section className="panel karen-actions">
                    <div className="panel-header">
                      <div><h2>Ações da jornada</h2><p>Transições registram novo evento e preservam o histórico.</p></div>
                    </div>
                    {availableApprovals.length > 0 && (
                      <div className="karen-approval-row">
                        <label>
                          Aprovação humana
                          <select value={approvalAction} onChange={(event) => setApprovalAction(event.target.value)}>
                            <option value="">Selecione ação comercial</option>
                            {availableApprovals.map((action) => (
                              <option key={action} value={action}>{config.action_labels[action]}</option>
                            ))}
                          </select>
                        </label>
                        <button className="secondary-button" type="button" disabled={busy || !approvalAction} onClick={() => void recordApproval()}>
                          Registrar aprovação
                        </button>
                      </div>
                    )}
                    <div className="karen-action-buttons">
                      {selected.available_actions.map((action) => (
                        <button
                          className={action === "opt_out" ? "secondary-button karen-optout" : "secondary-button"}
                          key={action}
                          type="button"
                          disabled={busy}
                          onClick={() => void runMutation(
                            `/karen/simulations/${selected.id}/actions`,
                            "POST",
                            { action },
                          )}
                        >
                          {config.action_labels[action] ?? action}
                          {config.sensitive_actions.includes(action) ? " · aprovação" : ""}
                        </button>
                      ))}
                    </div>
                    <div className="safety-banner">
                      <span>◈</span>
                      <div><strong>Contratos somente fictícios</strong><p>Preparação, link e confirmação de assinatura não criam documento válido nem contratação real.</p></div>
                    </div>
                  </section>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function eventLabel(eventType: string) {
  const labels: Record<string, string> = {
    scenario_started: "Cenário iniciado",
    conversation_turn: "Turno de conversa · não enviado",
    transition: "Transição de jornada",
    human_approval: "Aprovação humana",
    approval_consumed: "Aprovação consumida",
  };
  return labels[eventType] ?? eventType;
}

function stateLabel(config: Config, state: string | null) {
  return config.states.find((item) => item.key === state)?.label ?? state ?? "—";
}
