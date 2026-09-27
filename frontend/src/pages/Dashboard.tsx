import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Download,
  FileSpreadsheet,
  FileUp,
  RefreshCw,
  Search,
  ShieldCheck,
  Upload,
  XCircle,
} from "lucide-react";

import { getAudit, reviewAuditItem, uploadAudit } from "../api/audits";
import type { AuditItem, AuditItemStatus, AuditUploadResponse, ReviewDecision } from "../api/contracts";

type Filter = "all" | AuditItemStatus;

function uploadErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error)) {
    return "Não foi possível iniciar a auditoria. Tente novamente.";
  }

  const payload = error.response?.data as { message?: unknown; detail?: unknown; details?: unknown } | undefined;
  if (Array.isArray(payload?.details) && payload.details.every((detail) => typeof detail === "string")) {
    return payload.details.join(" ");
  }
  if (typeof payload?.message === "string") return payload.message;
  if (typeof payload?.detail === "string") return payload.detail;
  if (error.response?.status === 401) return "Sua sessão expirou. Entre novamente.";
  return "Não foi possível iniciar a auditoria. Tente novamente.";
}

const statusMeta: Record<AuditItemStatus, { label: string; tone: string }> = {
  suggested: { label: "Revisar", tone: "warning" },
  no_suggestion: { label: "Sem ação", tone: "neutral" },
  pending_review: { label: "Pendente", tone: "warning" },
  approved: { label: "Aprovado", tone: "success" },
  rejected: { label: "Rejeitado", tone: "danger" },
};

export default function Dashboard() {
  const [file, setFile] = useState<File | null>(null);
  const [audit, setAudit] = useState<AuditUploadResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  useEffect(() => {
    if (!audit || audit.status !== "processing") return;

    const timer = window.setInterval(async () => {
      try {
        setAudit(await getAudit(audit.audit_id));
      } catch {
        setError("Não foi possível atualizar o andamento da auditoria.");
      }
    }, 1500);

    return () => window.clearInterval(timer);
  }, [audit?.audit_id, audit?.status]);

  const filteredItems = useMemo(() => {
    if (!audit) return [];
    const normalizedQuery = query.trim().toLocaleLowerCase("pt-BR");
    return audit.data.filter((item) => {
      const statusMatches = filter === "all" || item.status === filter;
      const textMatches = !normalizedQuery || [item.codigo_produto, item.descricao, item.ncm_atual, item.ncm_sugerido]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase("pt-BR")
        .includes(normalizedQuery);
      return statusMatches && textMatches;
    });
  }, [audit, filter, query]);

  const progress = audit && audit.progresso.total > 0
    ? Math.round((audit.progresso.processados / audit.progresso.total) * 100)
    : 0;
  const reviewCount = audit?.data.filter((item) => item.status === "suggested" || item.status === "pending_review").length ?? 0;

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      setAudit(await uploadAudit(file));
      setFilter("all");
      setQuery("");
    } catch (error) {
      setError(uploadErrorMessage(error));
    } finally {
      setUploading(false);
    }
  }

  async function handleReview(item: AuditItem, decision: ReviewDecision) {
    if (!audit) return;
    setReviewingId(item.id);
    setError(null);
    try {
      const updated = await reviewAuditItem(audit.audit_id, item.id, decision);
      setAudit((current) => current ? {
        ...current,
        data: current.data.map((candidate) => candidate.id === item.id ? updated : candidate),
      } : current);
    } catch {
      setError("Não foi possível registrar a revisão deste item.");
    } finally {
      setReviewingId(null);
    }
  }

  function exportResults() {
    if (!audit?.data.length) return;
    const columns = ["Código", "Descrição", "NCM atual", "NCM sugerido", "CEST atual", "CEST sugerido", "Score", "Status", "Motivo", "Status CEST", "Fonte CEST", "Evidência CEST", "Tentativas de consulta", "Fonte NCM", "Versão NCM"];
    const rows = audit.data.map((item) => [
      item.codigo_produto,
      item.descricao,
      item.ncm_atual ?? "",
      item.ncm_sugerido ?? "",
      item.cest_atual ?? "",
      item.cest_sugerido ?? "",
      item.score.toString(),
      statusMeta[item.status].label,
      item.motivo,
      item.cest_status ?? "",
      item.cest_source_url ?? "",
      item.cest_evidence ?? "",
      attemptSummary(item),
      item.fonte_referencia ?? "",
      item.versao_referencia ?? "",
    ]);
    const csv = [columns, ...rows].map((row) => row.map(csvValue).join(";")).join("\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `auditoria-${audit.audit_id}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="audit-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark"><ShieldCheck size={20} aria-hidden="true" /></span>
          <div>
            <p className="eyebrow">CONFERÊNCIA FISCAL</p>
            <h1>Auditor NCM/CEST</h1>
          </div>
        </div>
        <div className="trust-note"><span className="pulse-dot" /> Recomendações exigem revisão humana</div>
      </header>

      <section className="workspace" aria-labelledby="page-title">
        <div className="page-intro">
          <div>
            <p className="eyebrow">NOVA AUDITORIA</p>
            <h2 id="page-title">Da planilha à decisão rastreável.</h2>
            <p>Envie o cadastro, acompanhe a análise e aprove apenas o que tiver evidência suficiente.</p>
          </div>
          {audit?.data.length ? <button className="button button-quiet" onClick={exportResults}><Download size={16} /> Exportar CSV</button> : null}
        </div>

        <section className="upload-panel" aria-label="Envio de planilha">
          <label className={`dropzone ${file ? "dropzone-ready" : ""}`}>
            <input type="file" accept=".xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            <span className="dropzone-icon"><FileUp size={23} /></span>
            <span className="dropzone-copy"><strong>{file ? file.name : "Selecione uma planilha Excel"}</strong><small>Modelo .xlsx com produto, descrição, NCM e CEST</small></span>
            <span className="dropzone-action">Procurar arquivo</span>
          </label>
          <button className="button button-primary" disabled={!file || uploading} onClick={handleUpload}>
            {uploading ? <RefreshCw className="spin" size={17} /> : <Upload size={17} />}
            {uploading ? "Preparando" : "Iniciar auditoria"}
          </button>
        </section>

        {error ? <div className="notice notice-error" role="alert"><AlertTriangle size={18} /> <span>{error}</span></div> : null}
        {audit?.errors.length ? <div className="notice notice-error" role="alert"><AlertTriangle size={18} /><span>{audit.errors.join(" ")}</span></div> : null}

        {audit ? <>
          <section className="audit-trail" aria-label="Andamento da auditoria">
            <div className="trail-title"><Clock3 size={17} /><span>{audit.status === "processing" ? "Auditoria em andamento" : audit.status === "completed" ? "Auditoria concluída" : "Auditoria interrompida"}</span></div>
            <div className="progress-track" aria-label={`${progress}% processado`}><span style={{ width: `${progress}%` }} /></div>
            <div className="trail-meta"><span>{audit.progresso.processados} de {audit.progresso.total} produtos analisados</span><strong>{progress}%</strong></div>
          </section>

          <section className="metrics" aria-label="Resumo da auditoria">
            <Metric label="Produtos" value={audit.resumo.total_produtos} note="na planilha" />
            <Metric label="Ação necessária" value={reviewCount} note="recomendações" tone="warning" />
            <Metric label="Concluídos" value={audit.progresso.processados} note="itens processados" tone="success" />
          </section>

          <section className="results-panel" aria-labelledby="results-title">
            <div className="results-head">
              <div><p className="eyebrow">RESULTADO</p><h3 id="results-title">Fila de conferência</h3></div>
              <div className="results-controls">
                <label className="search-field"><Search size={16} /><span className="sr-only">Buscar produto</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar produto ou NCM" /></label>
                <label className="filter-field"><span className="sr-only">Filtrar estado</span><select value={filter} onChange={(event) => setFilter(event.target.value as Filter)}><option value="all">Todos os estados</option><option value="suggested">Revisar</option><option value="approved">Aprovados</option><option value="rejected">Rejeitados</option><option value="no_suggestion">Sem ação</option></select></label>
              </div>
            </div>

            {!audit.data.length && audit.status === "processing" ? <EmptyState icon={<RefreshCw className="spin" size={22} />} title="Construindo a fila de conferência" text="Os resultados surgirão aqui assim que os produtos forem analisados." /> : null}
            {!audit.data.length && audit.status === "failed" ? <EmptyState icon={<AlertTriangle size={22} />} title="A auditoria não foi concluída" text="Revise a referência NCM e tente enviar a planilha novamente." /> : null}
            {audit.data.length ? <div className="table-wrap"><table><thead><tr><th>Produto</th><th>NCM atual</th><th>Recomendação</th><th>Confiança</th><th>Estado</th><th><span className="sr-only">Ações</span></th></tr></thead><tbody>{filteredItems.map((item) => <AuditRow key={item.id} item={item} busy={reviewingId === item.id} onReview={handleReview} />)}</tbody></table>{!filteredItems.length ? <EmptyState icon={<Search size={22} />} title="Nenhum item encontrado" text="Ajuste sua busca ou filtro para ver outros resultados." /> : null}</div> : null}
          </section>
        </> : <section className="empty-welcome"><FileSpreadsheet size={25} /><div><strong>Pronto para conferir.</strong><span>O resultado mostrará a origem da recomendação e manterá cada decisão rastreável.</span></div></section>}
      </section>
    </main>
  );
}

function AuditRow({ item, busy, onReview }: { item: AuditItem; busy: boolean; onReview: (item: AuditItem, decision: ReviewDecision) => void }) {
  const meta = statusMeta[item.status];
  const canReview = item.status === "suggested" || item.status === "pending_review";
  return <tr>
    <td><div className="product-cell"><strong>{item.descricao}</strong><span>{item.codigo_produto}</span></div></td>
    <td className="code">{item.ncm_atual ?? "—"}</td>
    <td><div className="recommendation"><span className="code">{item.ncm_sugerido ?? "Sem sugestão"}</span><small>{item.cest_sugerido ? `CEST ${item.cest_sugerido}` : item.motivo}</small></div><EvidencePanel item={item} /></td>
    <td><span className="score">{item.score.toFixed(1)}<small>%</small></span></td>
    <td><span className={`status-pill ${meta.tone}`}>{meta.label}</span></td>
    <td className="row-actions">{canReview ? <><button className="icon-action approve" disabled={busy} onClick={() => onReview(item, "approved")} title="Aprovar recomendação"><CheckCircle2 size={18} /><span className="sr-only">Aprovar</span></button><button className="icon-action reject" disabled={busy} onClick={() => onReview(item, "rejected")} title="Rejeitar recomendação"><XCircle size={18} /><span className="sr-only">Rejeitar</span></button></> : null}</td>
  </tr>;
}

function EvidencePanel({ item }: { item: AuditItem }) {
  const attempts = item.reference_attempts ?? [];
  const hasEvidence = Boolean(item.fonte_referencia || item.cest_status || item.cest_evidence || item.cest_source_url || attempts.length);
  if (!hasEvidence) return null;

  return <details className="evidence-details">
    <summary>Ver evidências</summary>
    <div className="evidence-content">
      {item.fonte_referencia ? <p><strong>Referência NCM:</strong> {item.fonte_referencia}{item.versao_referencia ? ` (${item.versao_referencia})` : ""}</p> : null}
      {item.cest_status ? <p><strong>Status CEST:</strong> {formatCestStatus(item.cest_status)}</p> : null}
      {item.cest_evidence ? <p><strong>Justificativa:</strong> {item.cest_evidence}</p> : null}
      {isExternalUrl(item.cest_source_url) ? <a href={item.cest_source_url ?? undefined} target="_blank" rel="noreferrer">Abrir fonte CEST</a> : null}
      {attempts.length ? <ul className="attempt-list">{attempts.map((attempt, index) => <li key={`${attempt.source}-${attempt.state}-${index}`}><strong>{attempt.source}:</strong> {attempt.state}{attempt.detail ? ` — ${attempt.detail}` : ""}</li>)}</ul> : null}
    </div>
  </details>;
}

function formatCestStatus(status: string) {
  const labels: Record<string, string> = {
    catalog_found: "Encontrado no catálogo local",
    catalog_ranked: "Selecionado por ranking de descrição",
    catalog_multiple: "Múltiplas opções para revisão",
    catalog_prefix_match: "Correspondência parcial; sem sugestão automática",
    catalog_not_found: "Não encontrado no catálogo",
    external_found: "Encontrado em fonte externa",
  };
  return labels[status] ?? status;
}

function isExternalUrl(value: string | null) {
  return Boolean(value && /^https?:\/\//i.test(value));
}

function attemptSummary(item: AuditItem) {
  return (item.reference_attempts ?? []).map((attempt) => `${attempt.source}: ${attempt.state}`).join(" | ");
}

function Metric({ label, value, note, tone = "default" }: { label: string; value: number; note: string; tone?: string }) {
  return <div className={`metric metric-${tone}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function EmptyState({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return <div className="empty-state"><span>{icon}</span><strong>{title}</strong><p>{text}</p></div>;
}

function csvValue(value: string) {
  return `"${value.replaceAll("\"", "\"\"")}"`;
}
