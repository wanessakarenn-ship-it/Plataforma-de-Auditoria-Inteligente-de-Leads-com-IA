"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { fetchWithFirebaseToken } from "../lib/firebase";

type KnowledgeCategory =
  | "text"
  | "faq"
  | "policy"
  | "product"
  | "service"
  | "objection"
  | "approved_answer"
  | "document";

type KnowledgeStatus = "draft" | "approved" | "archived";

type KnowledgeDraft = {
  title: string;
  category: KnowledgeCategory;
  body: string;
  origin: string;
  valid_from: string;
  valid_until: string;
  agent_ids: string[];
};

type KnowledgeContent = Omit<KnowledgeDraft, "valid_from" | "valid_until"> & {
  id: string;
  valid_from: string | null;
  valid_until: string | null;
  source_type: string;
  source_name: string | null;
  source_sha256: string | null;
  status: KnowledgeStatus;
  current_version: number;
  created_by_uid: string;
  approved_by_uid: string | null;
  approved_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  score: number | null;
  excerpt: string | null;
};

type Agent = {
  id: string;
  name: string;
  knowledge_requires_approval: boolean;
};

type ContentVersion = {
  version_number: number;
  snapshot: {
    title: string;
    category: KnowledgeCategory;
    status: KnowledgeStatus;
    origin: string;
    agent_ids: string[];
  };
  created_by_uid: string;
  created_at: string;
};

type Retrieval = {
  mode: string;
  query: string;
  notice: string;
  context: string;
  references: Array<{
    content_id: string;
    title: string;
    category: KnowledgeCategory;
    status: KnowledgeStatus;
    version: number;
    origin: string;
    source_name: string | null;
    excerpt: string;
    score: number;
  }>;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ?? "";
const categories: Array<{ value: KnowledgeCategory; label: string }> = [
  { value: "text", label: "Texto" },
  { value: "faq", label: "Pergunta frequente" },
  { value: "policy", label: "Política" },
  { value: "product", label: "Produto" },
  { value: "service", label: "Serviço" },
  { value: "objection", label: "Objeção" },
  { value: "approved_answer", label: "Resposta aprovada" },
  { value: "document", label: "Documento" },
];

function blankContent(): KnowledgeDraft {
  return {
    title: "",
    category: "text",
    body: "",
    origin: "Cadastro manual",
    valid_from: "",
    valid_until: "",
    agent_ids: [],
  };
}

function authorLabel(uid: string) {
  return `${uid.slice(0, 8)}…`;
}

function blankUpload() {
  return {
    title: "",
    category: "document" as KnowledgeCategory,
    origin: "Documento autorizado",
    agent_ids: [] as string[],
  };
}

function toLocalDateTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

async function readResponse(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? "Não foi possível concluir a operação.");
  return body;
}

function contentPayload(draft: KnowledgeDraft) {
  return {
    ...draft,
    valid_from: draft.valid_from ? new Date(draft.valid_from).toISOString() : null,
    valid_until: draft.valid_until ? new Date(draft.valid_until).toISOString() : null,
  };
}

export default function KnowledgeBase() {
  const [contents, setContents] = useState<KnowledgeContent[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [draft, setDraft] = useState<KnowledgeDraft>(blankContent);
  const [uploadDraft, setUploadDraft] = useState(blankUpload);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, ContentVersion[]>>({});
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [retrievalQuery, setRetrievalQuery] = useState("");
  const [retrievalAgentId, setRetrievalAgentId] = useState("");
  const [retrieval, setRetrieval] = useState<Retrieval | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function loadLibrary() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (categoryFilter) params.set("category", categoryFilter);
      if (statusFilter) params.set("status", statusFilter);
      if (agentFilter) params.set("agent_id", agentFilter);
      const [contentsResponse, agentsResponse] = await Promise.all([
        fetchWithFirebaseToken(`${API_URL}/knowledge/contents?${params}`, { cache: "no-store" }),
        fetchWithFirebaseToken(`${API_URL}/studio/agents`, { cache: "no-store" }),
      ]);
      const [contentData, agentData] = await Promise.all([
        readResponse(contentsResponse),
        readResponse(agentsResponse),
      ]);
      setContents(contentData);
      setAgents(agentData);
      setLoadFailed(false);
    } catch (loadError) {
      setLoadFailed(true);
      setError(loadError instanceof Error ? loadError.message : "Falha ao carregar a biblioteca.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadLibrary();
  }, []);

  function toggleAgent(agentId: string) {
    setDraft((current) => ({
      ...current,
      agent_ids: current.agent_ids.includes(agentId)
        ? current.agent_ids.filter((id) => id !== agentId)
        : [...current.agent_ids, agentId],
    }));
  }

  function toggleUploadAgent(agentId: string) {
    setUploadDraft((current) => ({
      ...current,
      agent_ids: current.agent_ids.includes(agentId)
        ? current.agent_ids.filter((id) => id !== agentId)
        : [...current.agent_ids, agentId],
    }));
  }

  async function saveContent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetchWithFirebaseToken(
        editingId
          ? `${API_URL}/knowledge/contents/${editingId}`
          : `${API_URL}/knowledge/contents`,
        {
          method: editingId ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(contentPayload(draft)),
        },
      );
      await readResponse(response);
      setNotice(editingId ? "Nova versão salva como rascunho." : "Conteúdo salvo como rascunho.");
      setDraft(blankContent());
      setEditingId(null);
      await loadLibrary();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Falha ao salvar o conteúdo.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Selecione um arquivo PDF, DOCX ou TXT.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("category", uploadDraft.category);
      form.append("origin", uploadDraft.origin);
      form.append("title", uploadDraft.title || file.name);
      form.append("agent_ids", JSON.stringify(uploadDraft.agent_ids));
      const response = await fetchWithFirebaseToken(`${API_URL}/knowledge/files`, {
        method: "POST",
        body: form,
      });
      await readResponse(response);
      setFile(null);
      setUploadDraft(blankUpload());
      setNotice("Texto extraído e salvo como rascunho; o arquivo original não é retido.");
      await loadLibrary();
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Falha ao processar o documento.");
    } finally {
      setBusy(false);
    }
  }

  async function updateState(content: KnowledgeContent, action: "approve" | "archive" | "restore") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetchWithFirebaseToken(
        `${API_URL}/knowledge/contents/${content.id}/state`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action }),
        },
      );
      await readResponse(response);
      setNotice(
        action === "approve"
          ? "Aprovação registrada com autoria e data."
          : action === "archive"
            ? "Conteúdo arquivado."
            : "Conteúdo restaurado como rascunho.",
      );
      await loadLibrary();
    } catch (stateError) {
      setError(stateError instanceof Error ? stateError.message : "Falha ao atualizar o estado.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleVersions(contentId: string) {
    setError("");
    try {
      if (versions[contentId]) {
        setVersions((current) => {
          const next = { ...current };
          delete next[contentId];
          return next;
        });
        return;
      }
      const response = await fetchWithFirebaseToken(
        `${API_URL}/knowledge/contents/${contentId}/versions`,
        { cache: "no-store" },
      );
      const result = await readResponse(response);
      setVersions((current) => ({ ...current, [contentId]: result }));
    } catch (versionError) {
      setError(versionError instanceof Error ? versionError.message : "Falha ao carregar versões.");
    }
  }

  function editContent(content: KnowledgeContent) {
    setEditingId(content.id);
    setDraft({
      title: content.title,
      category: content.category,
      body: content.body,
      origin: content.origin,
      valid_from: toLocalDateTime(content.valid_from),
      valid_until: toLocalDateTime(content.valid_until),
      agent_ids: content.agent_ids,
    });
    setFile(null);
    setError("");
    setNotice("");
  }

  async function retrieveContext(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setRetrieval(null);
    try {
      const response = await fetchWithFirebaseToken(`${API_URL}/knowledge/retrieve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: retrievalQuery,
          agent_id: retrievalAgentId || null,
          top_k: 5,
        }),
      });
      setRetrieval(await readResponse(response));
    } catch (retrievalError) {
      setError(retrievalError instanceof Error ? retrievalError.message : "Falha na pesquisa contextual.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="knowledge-layout">
      {(error || notice) && (
        <div className={`alert ${error ? "alert-error" : "alert-success"}`} role={error ? "alert" : "status"}>
          <span>{error ? "!" : "✓"}</span><div>{error || notice}</div>
          <button onClick={() => { setError(""); setNotice(""); }} aria-label="Fechar">×</button>
        </div>
      )}

      <section className="panel knowledge-safety">
        <div>
          <strong>Recuperação local determinística</strong>
          <p>Busca lexical sem embeddings ou chamadas externas. Referências são dados não confiáveis, nunca instruções.</p>
        </div>
        <span className="badge badge-amber">Conteúdo requer aprovação para agentes configurados</span>
      </section>

      <section className="panel knowledge-retrieval">
        <div className="panel-header">
          <div><h2>Pesquisa contextual</h2><p>Prévia de trechos e fontes que seriam associados à consulta.</p></div>
        </div>
        <form className="knowledge-search-form" onSubmit={(event) => void retrieveContext(event)}>
          <label>Consulta<input required maxLength={1000} value={retrievalQuery} onChange={(event) => setRetrievalQuery(event.target.value)} placeholder="Ex.: política de cancelamento" /></label>
          <label>Agente
            <select value={retrievalAgentId} onChange={(event) => setRetrievalAgentId(event.target.value)}>
              <option value="">Conteúdo aprovado do tenant</option>
              {agents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}
            </select>
          </label>
          <button className="primary-button" disabled={busy} type="submit">Pesquisar fontes</button>
        </form>
        {retrieval && (
          <div className="knowledge-results">
            <p className="knowledge-notice">{retrieval.notice} · modo {retrieval.mode}</p>
            {retrieval.references.length === 0 ? (
              <div className="empty-state compact">Nenhuma fonte aplicável encontrada.</div>
            ) : retrieval.references.map((reference) => (
              <article className="knowledge-reference" key={reference.content_id}>
                <div><strong>{reference.title}</strong><span>v{reference.version} · {reference.category} · {reference.status} · relevância {reference.score.toFixed(2)}</span></div>
                <p>{reference.excerpt}</p>
                <small>{reference.origin}{reference.source_name ? ` · ${reference.source_name}` : ""}</small>
              </article>
            ))}
            <details className="knowledge-context">
              <summary>Ver contexto seguro serializado</summary>
              <pre>{retrieval.context}</pre>
            </details>
          </div>
        )}
      </section>

      <div className="knowledge-columns">
        <section className="panel knowledge-library">
          <div className="panel-header">
            <div><h2>Biblioteca de conteúdos</h2><p>Origem, categoria, estado e versões por organização.</p></div>
          </div>
          <form className="knowledge-filters" onSubmit={(event) => { event.preventDefault(); void loadLibrary(); }}>
            <input aria-label="Pesquisar biblioteca" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar por conteúdo ou título" />
            <select aria-label="Filtrar categoria" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
              <option value="">Todas as categorias</option>
              {categories.map((category) => <option value={category.value} key={category.value}>{category.label}</option>)}
            </select>
            <select aria-label="Filtrar estado" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">Todos os estados</option>
              <option value="draft">Rascunhos</option>
              <option value="approved">Aprovados</option>
              <option value="archived">Arquivados</option>
            </select>
            <select aria-label="Filtrar agente" value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}>
              <option value="">Todos os agentes</option>
              {agents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}
            </select>
            <button className="secondary-button" type="submit">Filtrar</button>
          </form>
          {loading ? <div className="empty-state">Carregando conteúdo autorizado…</div> : loadFailed ? (
            <div className="empty-state">Falha ao carregar a biblioteca. <button className="secondary-button" onClick={() => void loadLibrary()}>Tentar novamente</button></div>
          ) : contents.length === 0 ? <div className="empty-state">Nenhum conteúdo corresponde aos filtros.</div> : (
            <div className="knowledge-content-list">
              {contents.map((content) => (
                <article className="knowledge-content-card" key={content.id}>
                  <div className="knowledge-content-heading">
                    <div><strong>{content.title}</strong><span>{content.category} · v{content.current_version} · {content.origin}</span></div>
                    <span className={`badge ${content.status === "approved" ? "badge-green" : content.status === "archived" ? "badge-red" : "badge-amber"}`}>{content.status}</span>
                  </div>
                  <p>{content.excerpt ?? content.body.slice(0, 220)}{content.body.length > 220 && !content.excerpt ? "…" : ""}</p>
                  <div className="knowledge-content-meta">
                    <span>{content.source_name ?? "Texto manual"}{content.source_sha256 ? ` · SHA-256 ${content.source_sha256.slice(0, 12)}…` : ""}</span>
                    <span>Criado por {authorLabel(content.created_by_uid)} · {new Date(content.created_at).toLocaleDateString("pt-BR")}</span>
                    <span>Agentes associados: {content.agent_ids.length}</span>
                    {content.approved_at && <span>Aprovado em {new Date(content.approved_at).toLocaleDateString("pt-BR")}</span>}
                  </div>
                  <div className="knowledge-actions">
                    {content.status !== "archived" && <button className="secondary-button" type="button" onClick={() => editContent(content)}>Editar</button>}
                    <button className="secondary-button" type="button" onClick={() => void toggleVersions(content.id)}>{versions[content.id] ? "Ocultar versões" : "Versões"}</button>
                    {content.status === "draft" && <button className="secondary-button" type="button" disabled={busy} onClick={() => void updateState(content, "approve")}>Aprovar</button>}
                    {content.status !== "archived" ? (
                      <button className="secondary-button" type="button" disabled={busy} onClick={() => void updateState(content, "archive")}>Arquivar</button>
                    ) : (
                      <button className="secondary-button" type="button" disabled={busy} onClick={() => void updateState(content, "restore")}>Restaurar</button>
                    )}
                  </div>
                  {versions[content.id] && (
                    <ol className="knowledge-version-list">
                      {versions[content.id].map((version) => (
                        <li key={version.version_number}><strong>v{version.version_number} · {version.snapshot.status}</strong><span>{new Date(version.created_at).toLocaleString("pt-BR")} · {authorLabel(version.created_by_uid)}</span></li>
                      ))}
                    </ol>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="knowledge-editors">
          <form className="panel knowledge-form" onSubmit={(event) => void saveContent(event)}>
            <div className="panel-header"><div><h2>{editingId ? "Editar conhecimento" : "Novo conteúdo"}</h2><p>Salvar edições cria versão e remove aprovação anterior.</p></div></div>
            <div className="knowledge-form-fields">
              <label>Título<input required maxLength={200} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
              <label>Categoria<select value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value as KnowledgeCategory })}>{categories.map((category) => <option key={category.value} value={category.value}>{category.label}</option>)}</select></label>
              <label>Origem / autoria<input required maxLength={300} value={draft.origin} onChange={(event) => setDraft({ ...draft, origin: event.target.value })} /></label>
              <label>Conteúdo<textarea required rows={7} maxLength={500000} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} /></label>
              <div className="knowledge-validity">
                <label>Válido a partir de<input type="datetime-local" value={draft.valid_from} onChange={(event) => setDraft({ ...draft, valid_from: event.target.value })} /></label>
                <label>Válido até<input type="datetime-local" value={draft.valid_until} onChange={(event) => setDraft({ ...draft, valid_until: event.target.value })} /></label>
              </div>
              <fieldset className="knowledge-agent-options">
                <legend>Associar a agentes</legend>
                {agents.length === 0 ? <p>Cadastre agentes no Estúdio de IA antes de associar fontes.</p> : agents.map((agent) => (
                  <label key={agent.id}><input type="checkbox" checked={draft.agent_ids.includes(agent.id)} onChange={() => toggleAgent(agent.id)} />{agent.name} {agent.knowledge_requires_approval ? "(exige aprovação)" : ""}</label>
                ))}
              </fieldset>
              <div className="knowledge-form-actions">
                <button className="primary-button" type="submit" disabled={busy}>{busy ? "Salvando…" : editingId ? "Salvar nova versão" : "Salvar rascunho"}</button>
                {editingId && <button className="secondary-button" type="button" onClick={() => { setEditingId(null); setDraft(blankContent()); }}>Cancelar</button>}
              </div>
            </div>
          </form>

          <form className="panel knowledge-form" onSubmit={(event) => void uploadFile(event)}>
            <div className="panel-header"><div><h2>Importar documento</h2><p>PDF, DOCX ou TXT · limite configurado pela API (5 MB padrão).</p></div></div>
            <div className="knowledge-form-fields">
              <label>Arquivo<input type="file" accept=".pdf,.docx,.txt" onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0] ?? null)} /></label>
              <label>Título<input maxLength={200} value={uploadDraft.title} onChange={(event) => setUploadDraft({ ...uploadDraft, title: event.target.value })} placeholder={file?.name ?? "Opcional; usa o nome do arquivo"} /></label>
              <label>Categoria<select value={uploadDraft.category} onChange={(event) => setUploadDraft({ ...uploadDraft, category: event.target.value as KnowledgeCategory })}>{categories.map((category) => <option key={category.value} value={category.value}>{category.label}</option>)}</select></label>
              <label>Origem / autoria<input required maxLength={300} value={uploadDraft.origin} onChange={(event) => setUploadDraft({ ...uploadDraft, origin: event.target.value })} /></label>
              <fieldset className="knowledge-agent-options">
                <legend>Associar a agentes</legend>
                {agents.length === 0 ? <p>Cadastre agentes no Estúdio de IA antes de associar fontes.</p> : agents.map((agent) => (
                  <label key={agent.id}><input type="checkbox" checked={uploadDraft.agent_ids.includes(agent.id)} onChange={() => toggleUploadAgent(agent.id)} />{agent.name} {agent.knowledge_requires_approval ? "(exige aprovação)" : ""}</label>
                ))}
              </fieldset>
              <p className="knowledge-file-note">O arquivo é validado e convertido em texto localmente; somente o texto extraído, o nome e o hash são persistidos.</p>
              <button className="secondary-button" type="submit" disabled={busy || !file}>{busy ? "Processando…" : "Validar e importar"}</button>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}
