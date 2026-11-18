"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";

type Lead = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  company: string | null;
  email: string | null;
  phone: string | null;
  status: string | null;
  phase: string | null;
  classification: string;
  loss_reason: string | null;
  disqualification_reason: string | null;
};

type QueueRow = {
  queue_id: string;
  status: string;
  eligible?: boolean;
  outbound_enabled?: false;
  lead: Lead;
};

type ImportPreview = {
  import_id: string;
  filename: string;
  mapping: Record<string, string>;
  total_rows: number;
  valid_rows: number;
  duplicate_rows: number;
  error_rows: number;
  warning_rows: number;
  preview: Array<{
    row_number: number;
    values: Lead;
    errors: string[];
    warnings: string[];
    duplicate_in_file: boolean;
    duplicate_in_database: boolean;
  }>;
};

type Dashboard = {
  total_leads: number;
  classifications: Record<string, number>;
  queues: { audit_pending: number; contact_drafts: number; contact_eligible: number };
  recent_imports: Array<{
    id: string;
    filename: string;
    status: string;
    total_rows: number;
    imported_rows: number;
    created_at: string;
  }>;
};

type Reasons = {
  loss: Array<{ id: string; name: string }>;
  disqualification: Array<{ id: string; name: string }>;
};

type LeadDetail = {
  lead: Lead;
  status_history: Array<{
    id: string;
    previous_status: string | null;
    current_status: string | null;
    previous_phase: string | null;
    current_phase: string | null;
    changed_at: string;
  }>;
  contact_permission: {
    channel: string;
    consent_status: string;
    suppression_reason: string | null;
  } | null;
};

type Section =
  | "overview"
  | "imports"
  | "leads"
  | "audit"
  | "contact"
  | "loss"
  | "disqualification";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

const navigation: Array<{ id: Section; label: string; icon: string; group: string }> = [
  { id: "overview", label: "Visão geral", icon: "◫", group: "Workspace" },
  { id: "imports", label: "Importação", icon: "⇧", group: "Workspace" },
  { id: "leads", label: "Base de leads", icon: "◎", group: "Gestão comercial" },
  { id: "audit", label: "Fila de auditoria", icon: "◉", group: "Gestão comercial" },
  { id: "contact", label: "Contato em rascunho", icon: "◇", group: "Gestão comercial" },
  { id: "loss", label: "Motivos de perda", icon: "↘", group: "Inteligência" },
  {
    id: "disqualification",
    label: "Desqualificação",
    icon: "⊘",
    group: "Inteligência",
  },
];

const classLabels: Record<string, string> = {
  disqualified: "Desqualificado",
  lost: "Perdido",
  qualified_lost: "Qualificado · perdido",
  research: "Pesquisa",
  connecting: "Em conexão",
  hand_raised: "Levantada de mão",
  nurture: "Nutrição",
  commercial_negotiation: "Negociação",
  won: "Ganho",
  unknown: "Revisão necessária",
};

function initials(lead: Lead) {
  return `${lead.first_name?.[0] ?? ""}${lead.last_name?.[0] ?? ""}`.toUpperCase() || "—";
}

function fullName(lead: Lead) {
  return [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "Lead sem nome";
}

function Badge({ children, tone = "neutral" }: { children: string; tone?: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function MetricCard({
  label,
  value,
  note,
  icon,
  tone,
}: {
  label: string;
  value: number;
  note: string;
  icon: string;
  tone: string;
}) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>{icon}</div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value.toLocaleString("pt-BR")}</div>
      <div className="metric-note">{note}</div>
    </article>
  );
}

export default function Home() {
  const [section, setSection] = useState<Section>("overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [auditQueue, setAuditQueue] = useState<QueueRow[]>([]);
  const [contactQueue, setContactQueue] = useState<QueueRow[]>([]);
  const [imports, setImports] = useState<Dashboard["recent_imports"]>([]);
  const [reasons, setReasons] = useState<Reasons>({ loss: [], disqualification: [] });
  const [selectedLead, setSelectedLead] = useState<LeadDetail | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [
        dashboardResponse,
        leadsResponse,
        auditResponse,
        contactResponse,
        importsResponse,
        reasonsResponse,
      ] = await Promise.all([
          fetch(`${API_URL}/dashboard`, { cache: "no-store" }),
          fetch(`${API_URL}/leads`, { cache: "no-store" }),
          fetch(`${API_URL}/queues/audit`, { cache: "no-store" }),
          fetch(`${API_URL}/queues/contact`, { cache: "no-store" }),
          fetch(`${API_URL}/imports`, { cache: "no-store" }),
          fetch(`${API_URL}/reasons`, { cache: "no-store" }),
        ]);
      for (const response of [
        dashboardResponse,
        leadsResponse,
        auditResponse,
        contactResponse,
        importsResponse,
        reasonsResponse,
      ]) {
        if (!response.ok) throw new Error("Não foi possível carregar os dados da API.");
      }
      setDashboard(await dashboardResponse.json());
      setLeads(await leadsResponse.json());
      setAuditQueue(await auditResponse.json());
      setContactQueue(await contactResponse.json());
      setImports(await importsResponse.json());
      setReasons(await reasonsResponse.json());
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? `${loadError.message} Verifique se a API está em execução.`
          : "Falha ao carregar o painel.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredLeads = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("pt-BR");
    if (!term) return leads;
    return leads.filter((lead) =>
      [fullName(lead), lead.company, lead.email, lead.status, lead.phase]
        .join(" ")
        .toLocaleLowerCase("pt-BR")
        .includes(term),
    );
  }, [leads, search]);

  async function handleFileSelect(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setPreview(null);
    setNotice("");
    setError("");
    if (!file) return;

    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(`${API_URL}/imports/preview`, { method: "POST", body: form });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Não foi possível pré-visualizar o arquivo.");
      setPreview(result);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Falha na importação.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmImport() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/imports/${preview.import_id}/confirm`, {
        method: "POST",
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Não foi possível confirmar a importação.");
      setNotice(
        `Importação concluída: ${result.imported_rows} leads adicionados e ${result.duplicate_rows} duplicados ignorados.`,
      );
      setPreview(null);
      setSelectedFile(null);
      await loadData();
    } catch (confirmError) {
      setError(confirmError instanceof Error ? confirmError.message : "Falha ao confirmar.");
    } finally {
      setBusy(false);
    }
  }

  async function showLead(lead: Lead) {
    setSelectedLead(null);
    setError("");
    try {
      const response = await fetch(`${API_URL}/leads/${lead.id}/detail`, { cache: "no-store" });
      if (!response.ok) throw new Error("Não foi possível carregar os detalhes do lead.");
      setSelectedLead(await response.json());
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : "Falha ao carregar o lead.");
    }
  }

  const pageTitle = navigation.find((item) => item.id === section)?.label ?? "Visão geral";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div>
            <div className="brand-name">BC Intelligence</div>
            <div className="brand-caption">LEAD OPERATIONS</div>
          </div>
        </div>
        <div className="workspace-switch">
          <div className="workspace-avatar">BC</div>
          <div className="workspace-copy">
            <strong>BC Energia</strong>
            <span>Workspace principal</span>
          </div>
          <span className="chevron">⌄</span>
        </div>
        <nav className="navigation" aria-label="Navegação principal">
          {(["Workspace", "Gestão comercial", "Inteligência"] as const).map((group) => (
            <div className="nav-group" key={group}>
              <div className="nav-heading">{group}</div>
              {navigation
                .filter((item) => item.group === group)
                .map((item) => (
                  <button
                    className={`nav-item ${section === item.id ? "active" : ""}`}
                    key={item.id}
                    onClick={() => setSection(item.id)}
                  >
                    <span className="nav-icon">{item.icon}</span>
                    <span>{item.label}</span>
                    {item.id === "audit" && auditQueue.length > 0 && (
                      <span className="nav-count">{auditQueue.length}</span>
                    )}
                  </button>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card">
            <span className="privacy-icon">◈</span>
            <div>
              <strong>Operação protegida</strong>
              <p>Contato externo desativado nesta sprint.</p>
            </div>
          </div>
          <div className="user-profile">
            <div className="user-avatar">BC</div>
            <div className="user-copy">
              <strong>Equipe BC</strong>
              <span>Administrador</span>
            </div>
            <span className="more">···</span>
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>BC Lead Intelligence</span>
            <span className="crumb-separator">/</span>
            <strong>{pageTitle}</strong>
          </div>
          <div className="topbar-actions">
            <span className="environment"><i /> Ambiente local</span>
            <button className="icon-button" aria-label="Atualizar dados" onClick={() => void loadData()}>
              ↻
            </button>
            <div className="top-avatar">BC</div>
          </div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">LEAD INTELLIGENCE · SPRINT 01</div>
              <h1>{section === "overview" ? "Visão geral" : pageTitle}</h1>
              <p>
                {section === "overview"
                  ? "Saúde da operação, qualidade dos dados e próximos passos."
                  : section === "imports"
                    ? "Importe uma exportação Salesforce, revise os dados e confirme quando estiver pronto."
                    : "Acompanhe e revise registros. Ações externas permanecem desativadas."}
              </p>
            </div>
            {section !== "imports" && (
              <button className="primary-button" onClick={() => setSection("imports")}>
                <span>＋</span> Importar leads
              </button>
            )}
          </div>

          {(error || notice) && (
            <div className={`alert ${error ? "alert-error" : "alert-success"}`}>
              <span>{error ? "!" : "✓"}</span>
              <div>{error || notice}</div>
              <button onClick={() => { setError(""); setNotice(""); }} aria-label="Fechar">
                ×
              </button>
            </div>
          )}

          {loading && <div className="loading-bar"><span /></div>}

          {section === "overview" && (
            <>
              <div className="metric-grid">
                <MetricCard label="Leads na base" value={dashboard?.total_leads ?? 0} note="Registros importados" icon="◎" tone="blue" />
                <MetricCard label="Na fila de auditoria" value={dashboard?.queues.audit_pending ?? 0} note="Aguardando análise" icon="◉" tone="violet" />
                <MetricCard label="Contato em rascunho" value={dashboard?.queues.contact_drafts ?? 0} note="Elegibilidade pendente" icon="◇" tone="amber" />
                <MetricCard label="Prontos para contato" value={dashboard?.queues.contact_eligible ?? 0} note="Exigem aprovação manual" icon="✓" tone="green" />
              </div>

              <div className="content-grid">
                <section className="panel classification-panel">
                  <div className="panel-header">
                    <div>
                      <h2>Distribuição por classificação</h2>
                      <p>Visão atual da base de leads</p>
                    </div>
                    <span className="panel-icon">⌗</span>
                  </div>
                  <div className="classification-list">
                    {Object.entries(classLabels).map(([key, label]) => {
                      const count = dashboard?.classifications[key] ?? 0;
                      const total = dashboard?.total_leads ?? 0;
                      return (
                        <div className="classification-row" key={key}>
                          <span className={`classification-dot dot-${key}`} />
                          <span className="classification-name">{label}</span>
                          <div className="bar-track"><span style={{ width: `${total ? (count / total) * 100 : 0}%` }} /></div>
                          <strong>{count}</strong>
                        </div>
                      );
                    })}
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-header">
                    <div>
                      <h2>Importações recentes</h2>
                      <p>Histórico de processamento</p>
                    </div>
                    <button className="text-button" onClick={() => setSection("imports")}>Ver todas ↗</button>
                  </div>
                  <div className="recent-list">
                    {(dashboard?.recent_imports ?? []).length === 0 && (
                      <div className="empty-state compact">Nenhuma importação ainda.</div>
                    )}
                    {(dashboard?.recent_imports ?? []).map((item) => (
                      <div className="recent-item" key={item.id}>
                        <div className="file-icon">▤</div>
                        <div className="recent-copy">
                          <strong>{item.filename}</strong>
                          <span>{new Date(item.created_at).toLocaleDateString("pt-BR")} · {item.total_rows} linhas</span>
                        </div>
                        <Badge tone={item.status === "completed" ? "green" : "amber"}>
                          {item.status === "completed" ? "Concluída" : "Prévia"}
                        </Badge>
                      </div>
                    ))}
                  </div>
                  <div className="sprint-note">
                    <div className="sprint-note-icon">✳</div>
                    <div><strong>Auditoria com IA, em breve</strong><span>Integração Vertex AI preparada, execução desativada.</span></div>
                  </div>
                </section>
              </div>

              <section className="panel table-panel">
                <div className="panel-header">
                  <div><h2>Leads adicionados recentemente</h2><p>Últimos registros da base</p></div>
                  <button className="text-button" onClick={() => setSection("leads")}>Ver base completa ↗</button>
                </div>
                <LeadTable leads={leads.slice(0, 5)} onSelect={(lead) => void showLead(lead)} />
              </section>
              <p className="footer-note"><span>◈</span> Fila de auditoria e fila de contato são independentes. Nenhuma mensagem é enviada.</p>
            </>
          )}

          {section === "imports" && (
            <div className="import-layout">
              <section className="panel upload-panel">
                <div className="panel-header">
                  <div><h2>Nova importação</h2><p>CSV ou Excel exportado do Salesforce</p></div>
                  <span className="panel-icon">⇧</span>
                </div>
                <label className="dropzone">
                  <input type="file" accept=".csv,.xlsx,.xlsm" onChange={handleFileSelect} />
                  <span className="upload-icon">⇧</span>
                  <strong>{selectedFile ? selectedFile.name : "Arraste seu arquivo ou clique para selecionar"}</strong>
                  <span>CSV, XLSX · até 20 MB</span>
                  <span className="secondary-button">{busy ? "Processando..." : "Selecionar arquivo"}</span>
                </label>
                <div className="import-guidance">
                  <span>ⓘ</span>
                  <p>O cabeçalho é detectado automaticamente. Confira o mapeamento e as validações antes de confirmar. Uma prévia não grava leads na base.</p>
                </div>
              </section>
              <section className="panel history-panel">
                <div className="panel-header"><div><h2>Histórico de importações</h2><p>Execuções recentes</p></div></div>
                {imports.length === 0 ? <div className="empty-state">Seus arquivos importados aparecerão aqui.</div> : (
                  <div className="recent-list">
                    {imports.map((item) => (
                      <div className="recent-item" key={item.id}>
                        <div className="file-icon">▤</div>
                        <div className="recent-copy"><strong>{item.filename}</strong><span>{item.imported_rows} adicionados · {item.total_rows} linhas</span></div>
                        <Badge tone={item.status === "completed" ? "green" : "amber"}>{item.status === "completed" ? "Concluída" : "Prévia"}</Badge>
                      </div>
                    ))}
                  </div>
                )}
              </section>
              {preview && (
                <section className="panel preview-panel">
                  <div className="panel-header">
                    <div><h2>Revisão antes da confirmação</h2><p>{preview.filename} · {preview.total_rows} registros detectados</p></div>
                    <button className="primary-button" disabled={busy || preview.valid_rows === 0} onClick={() => void confirmImport()}>
                      {busy ? "Confirmando..." : "Confirmar importação"}
                    </button>
                  </div>
                  <div className="preview-stats">
                    <span><strong>{preview.valid_rows}</strong> válidos</span>
                    <span><strong>{preview.duplicate_rows}</strong> duplicados</span>
                    <span><strong>{preview.error_rows}</strong> com erros</span>
                    <span><strong>{preview.warning_rows}</strong> avisos</span>
                  </div>
                  <div className="mapping-list">
                    {Object.entries(preview.mapping).map(([field, header]) => (
                      <span className="mapping-chip" key={field}>{field.replaceAll("_", " ")} <b>←</b> {header}</span>
                    ))}
                  </div>
                  <div className="table-scroll"><table><thead><tr><th>Linha</th><th>Nome</th><th>E-mail</th><th>Empresa</th><th>Status / fase</th><th>Classificação</th><th>Validação</th></tr></thead>
                    <tbody>{preview.preview.map((row) => (
                      <tr key={row.row_number}><td>{row.row_number}</td><td>{[row.values.first_name, row.values.last_name].filter(Boolean).join(" ") || "—"}</td><td>{row.values.email || "—"}</td><td>{row.values.company || "—"}</td><td>{row.values.status || row.values.phase || "—"}</td><td><Badge>{classLabels[row.values.classification] ?? row.values.classification}</Badge></td><td>{row.errors.length ? <Badge tone="red">{row.errors.join(" ")}</Badge> : row.warnings.length ? <Badge tone="amber">{row.warnings.join(" ")}</Badge> : row.duplicate_in_file || row.duplicate_in_database ? <Badge tone="amber">{row.duplicate_in_file ? "Duplicado no arquivo" : "Já está na base"}</Badge> : <Badge tone="green">OK</Badge>}</td></tr>
                    ))}</tbody></table></div>
                </section>
              )}
            </div>
          )}

          {section === "leads" && (
            <section className="panel table-panel">
              <div className="panel-header"><div><h2>Todos os leads</h2><p>{filteredLeads.length} registros encontrados</p></div>
                <input className="search-input" placeholder="Buscar por nome, e-mail ou empresa" value={search} onChange={(event) => setSearch(event.target.value)} />
              </div>
              {selectedLead && <LeadDetailPanel detail={selectedLead} onClose={() => setSelectedLead(null)} />}
              <LeadTable leads={filteredLeads} onSelect={(lead) => void showLead(lead)} />
            </section>
          )}

          {section === "audit" && <QueueTable title="Fila de auditoria" subtitle="Leads pendentes de análise, sem ações de contato" rows={auditQueue} />}
          {section === "contact" && <QueueTable title="Fila de contato em rascunho" subtitle="Elegibilidade e consentimento precisam de validação e aprovação manual" rows={contactQueue} contact />}
          {(section === "loss" || section === "disqualification") && (
            <section className="panel empty-section">
              <ReasonList
                title={section === "loss" ? "Motivos de perda" : "Motivos de desqualificação"}
                reasons={section === "loss" ? reasons.loss : reasons.disqualification}
              />
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

function LeadTable({ leads, onSelect }: { leads: Lead[]; onSelect?: (lead: Lead) => void }) {
  if (!leads.length) return <div className="empty-state">Ainda não há leads para exibir. Importe uma planilha para começar.</div>;
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>Lead</th><th>Empresa</th><th>Contato</th><th>Status</th><th>Fase</th><th>Classificação</th></tr></thead>
        <tbody>
          {leads.map((lead) => (
            <tr
              key={lead.id}
              className={onSelect ? "clickable-row" : ""}
              onClick={() => onSelect?.(lead)}
              onKeyDown={(event) => {
                if (onSelect && (event.key === "Enter" || event.key === " ")) onSelect(lead);
              }}
              tabIndex={onSelect ? 0 : undefined}
            >
              <td><div className="lead-cell"><div className="lead-avatar">{initials(lead)}</div><div><strong>{fullName(lead)}</strong><span>{lead.email || "Sem e-mail"}</span></div></div></td>
              <td>{lead.company || "—"}</td><td>{lead.phone || "—"}</td><td>{lead.status || "—"}</td><td>{lead.phase || "—"}</td>
              <td><Badge tone={lead.classification === "won" ? "green" : lead.classification === "lost" || lead.classification === "disqualified" ? "red" : "blue"}>{classLabels[lead.classification] ?? lead.classification}</Badge></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LeadDetailPanel({ detail, onClose }: { detail: LeadDetail; onClose: () => void }) {
  const lead = detail.lead;
  return (
    <div className="lead-detail">
      <div className="lead-detail-header">
        <div className="lead-cell">
          <div className="lead-avatar">{initials(lead)}</div>
          <div><strong>{fullName(lead)}</strong><span>{lead.company || "Empresa não informada"}</span></div>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Fechar detalhes">×</button>
      </div>
      <div className="lead-detail-grid">
        <div><span>E-mail</span><strong>{lead.email || "Não informado"}</strong></div>
        <div><span>Telefone</span><strong>{lead.phone || "Não informado"}</strong></div>
        <div><span>Status / fase</span><strong>{[lead.status, lead.phase].filter(Boolean).join(" · ") || "Não informado"}</strong></div>
        <div><span>Classificação</span><strong>{classLabels[lead.classification] ?? lead.classification}</strong></div>
        <div><span>Motivo da perda</span><strong>{lead.loss_reason || "Não informado"}</strong></div>
        <div><span>Desqualificação</span><strong>{lead.disqualification_reason || "Não informado"}</strong></div>
        <div><span>Permissão de contato</span><strong>{detail.contact_permission?.consent_status ?? "Desconhecida"}</strong></div>
        <div><span>Histórico registrado</span><strong>{detail.status_history.length} alteração(ões)</strong></div>
      </div>
      <div className="history-strip">
        <strong>Histórico de status</strong>
        {detail.status_history.length === 0 ? <span>Nenhuma alteração registrada.</span> : detail.status_history.map((item) => (
          <span key={item.id}>
            {item.previous_status || "Novo"} → {item.current_status || "—"}
            {item.current_phase ? ` · ${item.current_phase}` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function QueueTable({
  title,
  subtitle,
  rows,
  contact = false,
}: {
  title: string;
  subtitle: string;
  rows: QueueRow[];
  contact?: boolean;
}) {
  return (
    <section className="panel table-panel">
      <div className="panel-header"><div><h2>{title}</h2><p>{subtitle}</p></div><Badge tone="amber">{`${rows.length} pendentes`}</Badge></div>
      {!rows.length ? <div className="empty-state">Nenhum registro nesta fila.</div> : (
        <div className="table-scroll"><table><thead><tr><th>Lead</th><th>Empresa</th><th>Status</th><th>Classificação</th><th>{contact ? "Elegibilidade" : "Fila"}</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.queue_id}><td><div className="lead-cell"><div className="lead-avatar">{initials(row.lead)}</div><div><strong>{fullName(row.lead)}</strong><span>{row.lead.email || "Sem e-mail"}</span></div></div></td><td>{row.lead.company || "—"}</td><td>{row.lead.status || "—"}</td><td><Badge>{classLabels[row.lead.classification] ?? row.lead.classification}</Badge></td><td>{contact ? <Badge tone={row.eligible ? "green" : "amber"}>{row.eligible ? "Aguardando revisão" : "Consentimento / aprovação pendente"}</Badge> : <Badge tone="violet">Aguardando análise</Badge>}</td></tr>)}</tbody>
        </table></div>
      )}
      {contact && <div className="safety-banner"><span>◈</span><div><strong>Envio desabilitado</strong><p>Esta fila é apenas um rascunho. Não existe integração ou ação de envio nesta versão.</p></div></div>}
    </section>
  );
}

function ReasonList({
  title,
  reasons,
}: {
  title: string;
  reasons: Array<{ id: string; name: string }>;
}) {
  return (
    <>
      <div className="large-empty-icon">{title === "Motivos de perda" ? "↘" : "⊘"}</div>
      <h2>{title}</h2>
      <p>Catálogo derivado dos motivos presentes nas planilhas importadas. Nenhum motivo é pré-cadastrado.</p>
      {reasons.length ? (
        <div className="reason-list">
          {reasons.map((reason) => (
            <div className="reason-item" key={reason.id}>
              <span>{reason.name}</span>
              <Badge>{title === "Motivos de perda" ? "Perda" : "Desqualificação"}</Badge>
            </div>
          ))}
        </div>
      ) : (
        <div className="reason-callout">Nenhum motivo registrado. Importe uma planilha Salesforce para começar.</div>
      )}
    </>
  );
}
