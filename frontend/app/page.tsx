"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchWithFirebaseToken,
  isFirebaseConfigured,
  observeFirebaseUser,
  signInWithEmail,
  signInWithGoogle,
  signOutFromFirebase,
  type AppRole,
} from "../lib/firebase";
import AIStudio from "../components/ai-studio";
import KnowledgeBase from "../components/knowledge-base";

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

type AuditRecord = {
  id: string;
  lead_id: string;
  execution_mode: "simulated" | "vertex";
  model: string | null;
  model_version: string | null;
  prompt_version: string | null;
  status: string;
  classification: string;
  original_reason: string;
  justification: string;
  limitations: string[];
  alternative_reason: string | null;
  requires_human_review: boolean;
  estimated_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  reprocess_of_id: string | null;
  review_status: string;
  review_notes: string | null;
  reviewed_at: string | null;
  created_at: string;
  finished_at: string | null;
  error_message: string | null;
  evidence: Array<{
    id: string;
    message_id: string | null;
    source_id: string | null;
    excerpt: string | null;
    referenced_at: string | null;
    verified: boolean;
  }>;
};

type AuditContext = {
  history_available: boolean;
  messages: Array<{
    id: string;
    sent_at: string | null;
    direction: string;
    message_type: string;
    body: string;
    capture_source: string | null;
  }>;
};

type Section =
  | "overview"
  | "imports"
  | "leads"
  | "audit"
  | "contact"
  | "loss"
  | "disqualification"
  | "ai-studio"
  | "knowledge";

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
  { id: "ai-studio", label: "Estúdio de IA", icon: "✳", group: "Administração" },
  { id: "knowledge", label: "Base de Conhecimento", icon: "▤", group: "Administração" },
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

const auditLabels: Record<string, string> = {
  confirmed: "Confirmado",
  divergent: "Divergente",
  inconclusive: "Inconclusivo",
  not_auditable: "Não auditável",
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
  const [authReady, setAuthReady] = useState(false);
  const [firebaseConfigured, setFirebaseConfigured] = useState(false);
  const [user, setUser] = useState<import("firebase/auth").User | null>(null);
  const [role, setRole] = useState<AppRole | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
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

  useEffect(() => {
    const configured = isFirebaseConfigured();
    setFirebaseConfigured(configured);
    if (!configured) {
      setAuthReady(true);
      return;
    }
    return observeFirebaseUser(
      (currentUser) => {
        setAuthReady(false);
        setUser(currentUser);
        setRole(null);
        setDashboard(null);
        setLeads([]);
        setAuditQueue([]);
        setContactQueue([]);
        setImports([]);
        setReasons({ loss: [], disqualification: [] });
        setSelectedLead(null);
        if (!currentUser) {
          setSection("overview");
          setAuthReady(true);
          return;
        }
        void currentUser.getIdTokenResult().then(
          ({ claims }) => {
            const claimRole = claims.role;
            const allowedRole =
              claimRole === "admin" || claimRole === "auditor" || claimRole === "gestor"
                ? claimRole
                : null;
            setRole(allowedRole);
            if (allowedRole === "admin") setSection("overview");
            else if (allowedRole === "gestor") setSection("overview");
            else if (allowedRole === "auditor") setSection("leads");
            setAuthReady(true);
          },
          (tokenError: Error) => {
            setAuthError(tokenError.message);
            setAuthReady(true);
          },
        );
      },
      (authListenerError) => {
        setAuthError(authListenerError.message);
        setAuthReady(true);
      },
    );
  }, []);

  async function handleEmailSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthBusy(true);
    setAuthError("");
    try {
      await signInWithEmail(email, password);
      setPassword("");
    } catch (signInError) {
      setAuthError(signInError instanceof Error ? signInError.message : "Falha na autenticação.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleGoogleSignIn() {
    setAuthBusy(true);
    setAuthError("");
    try {
      await signInWithGoogle();
    } catch (signInError) {
      setAuthError(signInError instanceof Error ? signInError.message : "Falha na autenticação.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleSignOut() {
    await signOutFromFirebase();
  }

  const loadData = useCallback(async () => {
    if (!role) return;
    setLoading(true);
    setError("");
    try {
      if (role === "admin") {
        const [dashboardResponse, importsResponse] = await Promise.all([
          fetchWithFirebaseToken(`${API_URL}/dashboard`, { cache: "no-store" }),
          fetchWithFirebaseToken(`${API_URL}/imports`, { cache: "no-store" }),
        ]);
        if (!dashboardResponse.ok || !importsResponse.ok) {
          throw new Error("Não foi possível carregar o painel administrativo.");
        }
        setDashboard(await dashboardResponse.json());
        setImports(await importsResponse.json());
      } else if (role === "gestor") {
        const response = await fetchWithFirebaseToken(`${API_URL}/dashboard`, { cache: "no-store" });
        if (!response.ok) throw new Error("Não foi possível carregar os indicadores.");
        setDashboard(await response.json());
      } else {
        const [leadsResponse, auditResponse, contactResponse, reasonsResponse] = await Promise.all([
          fetchWithFirebaseToken(`${API_URL}/leads`, { cache: "no-store" }),
          fetchWithFirebaseToken(`${API_URL}/queues/audit`, { cache: "no-store" }),
          fetchWithFirebaseToken(`${API_URL}/queues/contact`, { cache: "no-store" }),
          fetchWithFirebaseToken(`${API_URL}/reasons`, { cache: "no-store" }),
        ]);
        if ([leadsResponse, auditResponse, contactResponse, reasonsResponse].some((response) => !response.ok)) {
          throw new Error("Não foi possível carregar os dados autorizados do auditor.");
        }
        setLeads(await leadsResponse.json());
        setAuditQueue(await auditResponse.json());
        setContactQueue(await contactResponse.json());
        setReasons(await reasonsResponse.json());
      }
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? `${loadError.message} Verifique se a API está em execução.`
          : "Falha ao carregar o painel.",
      );
    } finally {
      setLoading(false);
    }
  }, [role]);

  useEffect(() => {
    if (role) void loadData();
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
      const response = await fetchWithFirebaseToken(`${API_URL}/imports/preview`, { method: "POST", body: form });
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
      const response = await fetchWithFirebaseToken(`${API_URL}/imports/${preview.import_id}/confirm`, {
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
      const response = await fetchWithFirebaseToken(`${API_URL}/leads/${lead.id}/detail`, { cache: "no-store" });
      if (!response.ok) throw new Error("Não foi possível carregar os detalhes do lead.");
      setSelectedLead(await response.json());
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : "Falha ao carregar o lead.");
    }
  }

  const allowedSections =
    role === "admin"
      ? ["overview", "imports", "ai-studio", "knowledge"]
      : role === "gestor"
        ? ["overview"]
        : ["leads", "audit", "contact", "loss", "disqualification"];
  const visibleNavigation = navigation.filter((item) => allowedSections.includes(item.id));
  const roleLabels: Record<AppRole, string> = {
    admin: "Administrador",
    auditor: "Auditor",
    gestor: "Gestor",
  };
  const pageTitle = visibleNavigation.find((item) => item.id === section)?.label ?? "Visão geral";

  if (!authReady) {
    return <main className="app-shell"><section className="panel"><p>Verificando autenticação...</p></section></main>;
  }

  if (!firebaseConfigured) {
    return (
      <main className="auth-screen">
        <section className="panel auth-panel">
          <h1>Autenticação não configurada</h1>
          <p>Configure as variáveis públicas do Firebase Web em <code>frontend/.env.local</code> e reinicie o frontend.</p>
        </section>
      </main>
    );
  }

  if (!user || !role) {
    return (
      <main className="auth-screen">
        <section className="panel auth-panel">
          <div className="brand-name">Lead Intelligence AI</div>
          <h1>{user ? "Acesso não autorizado" : "Entrar na plataforma"}</h1>
          {user ? (
            <>
              <p>Sua conta não possui um perfil autorizado. Solicite a atribuição de um perfil ao administrador.</p>
              <button className="secondary-button" onClick={() => void handleSignOut()}>Sair</button>
            </>
          ) : (
            <>
              <p>Use uma conta autorizada pela organização. O acesso é validado pela API.</p>
              <form className="auth-form" onSubmit={(event) => void handleEmailSignIn(event)}>
                <label htmlFor="login-email">E-mail</label>
                <input id="login-email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} />
                <label htmlFor="login-password">Senha</label>
                <input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
                <button className="primary-button" type="submit" disabled={authBusy}>
                  {authBusy ? "Autenticando..." : "Entrar"}
                </button>
              </form>
              <button className="secondary-button auth-google-button" onClick={() => void handleGoogleSignIn()} disabled={authBusy}>
                Entrar com Google
              </button>
            </>
          )}
          {authError && <div className="alert alert-error" role="alert">{authError}</div>}
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">L</div>
          <div>
            <div className="brand-name">Lead Intelligence AI</div>
            <div className="brand-caption">LEAD OPERATIONS</div>
          </div>
        </div>
        <div className="workspace-switch">
          <div className="workspace-avatar">LI</div>
          <div className="workspace-copy">
            <strong>Organização</strong>
            <span>Workspace atual</span>
          </div>
          <span className="chevron">⌄</span>
        </div>
        <nav className="navigation" aria-label="Navegação principal">
          {(["Workspace", "Gestão comercial", "Inteligência", "Administração"] as const).map((group) => (
            <div className="nav-group" key={group}>
              <div className="nav-heading">{group}</div>
              {visibleNavigation
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
            <div className="user-avatar">LI</div>
            <div className="user-copy">
              <strong>{user.email ?? "Conta autenticada"}</strong>
              <span>{roleLabels[role]}</span>
            </div>
            <button className="more" onClick={() => void handleSignOut()} aria-label="Sair">Sair</button>
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Lead Intelligence AI</span>
            <span className="crumb-separator">/</span>
            <strong>{pageTitle}</strong>
          </div>
          <div className="topbar-actions">
            <span className="environment"><i /> Ambiente local</span>
            <button className="icon-button" aria-label="Atualizar dados" onClick={() => void loadData()}>
              ↻
            </button>
            <div className="top-avatar">LI</div>
          </div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                LEAD INTELLIGENCE · {section === "ai-studio" || section === "knowledge" ? "SPRINT 03" : "SPRINT 02"}
              </div>
              <h1>{section === "overview" ? "Visão geral" : pageTitle}</h1>
              <p>
                {section === "overview"
                  ? "Saúde da operação, qualidade dos dados e próximos passos."
                  : section === "imports"
                    ? "Importe uma exportação Salesforce, revise os dados e confirme quando estiver pronto."
                    : section === "ai-studio"
                      ? "Cadastre e versione agentes por organização; publicação exige aprovação humana."
                    : section === "knowledge"
                      ? "Gerencie fontes versionadas e pré-visualize referências recuperadas localmente."
                    : "Acompanhe e revise registros. Ações externas permanecem desativadas."}
              </p>
            </div>
            {role === "admin" && section === "overview" && (
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
                    <div><strong>Auditoria por evidências</strong><span>Modo simulado disponível; Vertex AI segue bloqueado por padrão.</span></div>
                  </div>
                </section>
              </div>

              {role !== "admin" && (
                <section className="panel table-panel">
                  <div className="panel-header">
                    <div><h2>Leads adicionados recentemente</h2><p>Últimos registros da base</p></div>
                    <button className="text-button" onClick={() => setSection("leads")}>Ver base completa ↗</button>
                  </div>
                  <LeadTable leads={leads.slice(0, 5)} onSelect={(lead) => void showLead(lead)} />
                </section>
              )}
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

          {section === "audit" && <AuditWorkPanel rows={auditQueue} />}
          {section === "contact" && <QueueTable title="Fila de contato em rascunho" subtitle="Elegibilidade e consentimento precisam de validação e aprovação manual" rows={contactQueue} contact />}
          {(section === "loss" || section === "disqualification") && (
            <section className="panel empty-section">
              <ReasonList
                title={section === "loss" ? "Motivos de perda" : "Motivos de desqualificação"}
                reasons={section === "loss" ? reasons.loss : reasons.disqualification}
              />
            </section>
          )}
          {section === "ai-studio" && role === "admin" && <AIStudio />}
          {section === "knowledge" && role === "admin" && <KnowledgeBase />}
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

function AuditWorkPanel({ rows }: { rows: QueueRow[] }) {
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [context, setContext] = useState<AuditContext | null>(null);
  const [audits, setAudits] = useState<AuditRecord[]>([]);
  const [selectedAuditId, setSelectedAuditId] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selectedAudit =
    audits.find((audit) => audit.id === selectedAuditId) ?? audits[0] ?? null;

  async function loadLead(lead: Lead) {
    setSelectedLead(lead);
    setContext(null);
    setAudits([]);
    setSelectedAuditId(null);
    setError("");
    setNotice("");
    try {
      const [contextResponse, auditsResponse] = await Promise.all([
        fetchWithFirebaseToken(`${API_URL}/leads/${lead.id}/audit-context`, { cache: "no-store" }),
        fetchWithFirebaseToken(`${API_URL}/leads/${lead.id}/audits`, { cache: "no-store" }),
      ]);
      if (!contextResponse.ok || !auditsResponse.ok) {
        throw new Error("Não foi possível carregar o histórico de auditoria.");
      }
      const [history, priorAudits] = await Promise.all([
        contextResponse.json() as Promise<AuditContext>,
        auditsResponse.json() as Promise<AuditRecord[]>,
      ]);
      setContext(history);
      setAudits(priorAudits);
      setSelectedAuditId(priorAudits[0]?.id ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Falha ao carregar auditoria.");
    }
  }

  async function runAudit(reprocess = false) {
    if (!selectedLead) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const endpoint =
        reprocess && selectedAudit
          ? `${API_URL}/audits/${selectedAudit.id}/reprocess`
          : `${API_URL}/leads/${selectedLead.id}/audits`;
      const response = await fetchWithFirebaseToken(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "simulated" }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Não foi possível executar a auditoria.");
      setAudits((current) => [result as AuditRecord, ...current]);
      setSelectedAuditId((result as AuditRecord).id);
      setNotice("Simulação concluída. Nenhuma chamada ao Vertex AI foi realizada.");
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Falha ao executar auditoria.");
    } finally {
      setBusy(false);
    }
  }

  async function saveReview(decision: string) {
    if (!selectedAudit) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetchWithFirebaseToken(`${API_URL}/audits/${selectedAudit.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, notes: reviewNotes || null }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Não foi possível salvar a revisão.");
      setAudits((current) =>
        current.map((item) => (item.id === (result as AuditRecord).id ? result : item)),
      );
      setNotice("Revisão humana registrada.");
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "Falha ao salvar revisão.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="audit-layout">
      <section className="panel audit-queue-panel">
        <div className="panel-header">
          <div>
            <h2>Fila de auditoria</h2>
            <p>Registros pendentes, sem ações de contato</p>
          </div>
          <Badge>{`${rows.length} pendentes`}</Badge>
        </div>
        {rows.length === 0 ? (
          <div className="empty-state">A fila de auditoria está vazia.</div>
        ) : (
          <div className="audit-lead-list">
            {rows.map(({ lead }) => (
              <button
                className={`audit-lead-row ${selectedLead?.id === lead.id ? "active" : ""}`}
                key={lead.id}
                onClick={() => void loadLead(lead)}
              >
                <span className="audit-lead-title">{fullName(lead)}</span>
                <span>{lead.loss_reason || lead.disqualification_reason || "Motivo ausente"}</span>
                <span>{[lead.status, lead.phase].filter(Boolean).join(" · ") || "Status não informado"}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="audit-detail-column">
        {(error || notice) && (
          <div className={`alert ${error ? "alert-error" : "alert-success"}`}>
            <span>{error ? "!" : "✓"}</span>
            <div>{error || notice}</div>
          </div>
        )}
        {!selectedLead ? (
          <section className="panel empty-state">Selecione um lead para ver o histórico e auditar evidências.</section>
        ) : (
          <>
            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2>{fullName(selectedLead)}</h2>
                  <p>{selectedLead.company || "Empresa não informada"}</p>
                </div>
                <Badge tone="blue">{classLabels[selectedLead.classification] ?? selectedLead.classification}</Badge>
              </div>
              <div className="audit-lead-summary">
                <div><span>Status / fase</span><strong>{[selectedLead.status, selectedLead.phase].filter(Boolean).join(" · ") || "Não informado"}</strong></div>
                <div><span>Motivo CRM</span><strong>{selectedLead.loss_reason || selectedLead.disqualification_reason || "Não informado"}</strong></div>
                <div><span>Histórico autorizado</span><strong>{context?.history_available ? `${context.messages.length} mensagem(ns) disponível(is)` : "Indisponível"}</strong></div>
              </div>
              <div className="audit-actions">
                <button className="primary-button" disabled={busy} onClick={() => void runAudit()}>
                  {busy ? "Processando..." : "Executar simulação"}
                </button>
                <span>Vertex AI real permanece bloqueado até configuração e aprovação explícitas.</span>
              </div>
              <div className="audit-history">
                <h3>Histórico autorizado</h3>
                {!context || context.messages.length === 0 ? (
                  <div className="empty-state compact">Nenhuma mensagem autorizada e dentro da retenção está disponível.</div>
                ) : context.messages.map((message) => (
                  <article className="audit-message" key={message.id}>
                    <div><Badge>{message.direction === "inbound" ? "Recebida" : "Enviada"}</Badge>
                      <span>{message.sent_at ? new Date(message.sent_at).toLocaleString("pt-BR") : "Data indisponível"}</span></div>
                    <p>{message.body}</p>
                    <small>{message.capture_source || "Origem não informada"}</small>
                  </article>
                ))}
              </div>
            </section>

            {audits.length > 0 && (
              <section className="panel">
                <div className="panel-header">
                  <div><h2>Resultado e reprocessamentos</h2><p>Histórico imutável de execuções; a revisão humana fica registrada separadamente.</p></div>
                  {selectedAudit && <button className="secondary-button" disabled={busy} onClick={() => void runAudit(true)}>Reprocessar</button>}
                </div>
                <div className="audit-run-list">
                  {audits.map((audit) => (
                    <button
                      className={`audit-run-row ${selectedAudit?.id === audit.id ? "active" : ""}`}
                      key={audit.id}
                      onClick={() => setSelectedAuditId(audit.id)}
                    >
                      <span>{new Date(audit.created_at).toLocaleString("pt-BR")}</span>
                      <Badge tone={audit.execution_mode === "simulated" ? "amber" : "blue"}>
                        {audit.execution_mode === "simulated" ? "Simulada" : "Vertex AI"}
                      </Badge>
                      <Badge>{audit.status === "completed" ? auditLabels[audit.classification] ?? audit.classification : audit.status}</Badge>
                    </button>
                  ))}
                </div>
                {selectedAudit && (
                  <div className="audit-result">
                    <div className="audit-result-heading">
                      <h3>Resultado: {auditLabels[selectedAudit.classification] ?? selectedAudit.classification}</h3>
                      <Badge tone={selectedAudit.execution_mode === "simulated" ? "amber" : "blue"}>
                        {selectedAudit.execution_mode === "simulated" ? "Modo simulado" : selectedAudit.model ?? "Vertex AI"}
                      </Badge>
                    </div>
                    <p>{selectedAudit.justification}</p>
                    {selectedAudit.error_message && <div className="audit-error">{selectedAudit.error_message}</div>}
                    <div><strong>Motivo original:</strong> {selectedAudit.original_reason || "Não informado"}</div>
                    {selectedAudit.alternative_reason && <div><strong>Possível alternativa:</strong> {selectedAudit.alternative_reason}</div>}
                    <div className="audit-evidence-list">
                      <strong>Evidências</strong>
                      {selectedAudit.evidence.length === 0 ? <span>Nenhuma evidência verificável vinculada.</span> : selectedAudit.evidence.map((evidence) => (
                        <blockquote key={evidence.id}>
                          {evidence.verified ? `“${evidence.excerpt}”` : "Conteúdo indisponível ou fora do prazo de retenção."}
                          <small>{evidence.referenced_at ? new Date(evidence.referenced_at).toLocaleString("pt-BR") : "Data indisponível"} · {evidence.verified ? "Verificada" : "Indisponível"}</small>
                        </blockquote>
                      ))}
                    </div>
                    {selectedAudit.limitations.length > 0 && (
                      <div className="audit-limitations"><strong>Limitações</strong><ul>{selectedAudit.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul></div>
                    )}
                    <div className="audit-review">
                      <strong>Revisão humana: {auditLabels[selectedAudit.review_status] ?? (selectedAudit.review_status === "pending" ? "Pendente" : selectedAudit.review_status)}</strong>
                      <input value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} placeholder="Notas da revisão (opcional)" maxLength={4000} />
                      <div>
                        {Object.entries(auditLabels).map(([decision, label]) => (
                          <button className="text-button" key={decision} disabled={busy} onClick={() => void saveReview(decision)}>{label}</button>
                        ))}
                      </div>
                      {selectedAudit.review_notes && <p>{selectedAudit.review_notes}</p>}
                    </div>
                  </div>
                )}
              </section>
            )}
          </>
        )}
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
