import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { strToU8, zipSync } from "fflate";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronRight,
  Download,
  FileSpreadsheet,
  FileUp,
  ListChecks,
  LoaderCircle,
  LogOut,
  RotateCcw,
  Search,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";

import { getAudit, getLatestAudit, reviewAuditItem, uploadAudit } from "../api/audits";
import type { AuditItem, AuditItemStatus, AuditStatus, AuditUploadResponse, ReviewDecision } from "../api/contracts";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../theme";

type Filter = "all" | "review" | "cest_alert" | "approved" | "rejected" | "no_suggestion";

// A API recusa (409) uma segunda revisão do mesmo item; a decisão fica retida
// no navegador por alguns segundos para que um clique errado possa ser desfeito.
const UNDO_MS = 5000;
const POLL_MS = 1500;
const MAX_POLL_FAILURES = 5;
const LAST_AUDIT_ID_KEY = "last_audit_id";

const NCM_GROUPS = [4, 2, 2];
const CEST_GROUPS = [2, 3, 2];
const CEST_ALERT_STATUSES = new Set([
  "catalog_current_mismatch",
  "catalog_prefix_current_match",
  "catalog_prefix_current_mismatch",
  "catalog_external_confirmed_mismatch",
  "catalog_external_conflict",
  "catalog_no_cest_for_ncm",
  "catalog_multiple",
  "catalog_not_found",
]);

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

function reviewErrorMessage(error: unknown, item: AuditItem): string {
  if (axios.isAxiosError(error) && error.response?.status === 409) {
    const detail = (error.response.data as { detail?: unknown } | undefined)?.detail;
    return typeof detail === "string" ? detail : `"${item.descricao}" já foi revisado e não aceita nova decisão.`;
  }
  return `Não foi possível registrar a decisão sobre "${item.descricao}". Tente novamente.`;
}

const statusMeta: Record<AuditItemStatus, { label: string; tone: string }> = {
  suggested: { label: "Sugestão", tone: "warning" },
  pending_review: { label: "Pendente", tone: "warning" },
  no_suggestion: { label: "Sem sugestão", tone: "neutral" },
  approved: { label: "Aprovado", tone: "success" },
  rejected: { label: "Rejeitado", tone: "danger" },
};

const decisionMeta: Record<ReviewDecision, { label: string; tone: string; done: string }> = {
  approved: { label: "Aprovando", tone: "success", done: "aprovado" },
  rejected: { label: "Rejeitando", tone: "danger", done: "rejeitado" },
};

const runMeta: Record<AuditStatus, string> = {
  processing: "Em análise",
  completed: "Concluída",
  failed: "Interrompida",
};

const tiles: { key: Filter; label: string; tone: string }[] = [
  { key: "all", label: "Produtos", tone: "" },
  { key: "review", label: "Aguardando revisão", tone: "warning" },
  { key: "cest_alert", label: "Alertas de CEST", tone: "danger" },
  { key: "approved", label: "Aprovados", tone: "success" },
  { key: "rejected", label: "Rejeitados", tone: "danger" },
  { key: "no_suggestion", label: "Sem sugestão", tone: "neutral" },
];

function needsReview(item: AuditItem) {
  return item.status === "suggested" || item.status === "pending_review";
}

function hasCestAlert(item: AuditItem) {
  return CEST_ALERT_STATUSES.has(item.cest_status ?? "");
}

// A exportacao resumida representa a classificacao proposta. Ela entra quando
// ao menos um dos codigos mudou; uma sugestao pendente continua no relatorio
// para que a pessoa responsavel possa revisa-la fora do sistema, se necessario.
function hasSuggestedClassificationChange(item: AuditItem) {
  return (
    Boolean(item.ncm_sugerido && item.ncm_sugerido !== item.ncm_atual)
    || Boolean(item.cest_sugerido && item.cest_sugerido !== item.cest_atual)
  );
}

function proposedCode(current: string | null, suggested: string | null) {
  return suggested && suggested !== current ? suggested : current ?? "";
}

function matchesFilter(item: AuditItem, filter: Filter) {
  if (filter === "all") return true;
  if (filter === "review") return needsReview(item);
  if (filter === "cest_alert") return hasCestAlert(item);
  return item.status === filter;
}

// Pendências primeiro, e entre elas as de menor confiança, que pedem mais atenção.
function byUrgency(a: AuditItem, b: AuditItem) {
  const cestAlertA = hasCestAlert(a);
  const cestAlertB = hasCestAlert(b);
  if (cestAlertA !== cestAlertB) return cestAlertA ? -1 : 1;
  const pendingA = needsReview(a);
  const pendingB = needsReview(b);
  if (pendingA !== pendingB) return pendingA ? -1 : 1;
  return pendingA ? a.score - b.score : 0;
}

type ClassificationResult = { label: string; tone: "success" | "warning" | "danger" | "neutral" };

function ncmResult(item: AuditItem): ClassificationResult {
  return item.ncm_sugerido
    ? { label: "Alteração sugerida", tone: "warning" }
    : { label: "Sem alteração sugerida", tone: "neutral" };
}

function cestResult(item: AuditItem): ClassificationResult {
  switch (item.cest_status) {
    case "catalog_current_match":
      return { label: "Compatível", tone: "success" };
    case "catalog_current_mismatch":
      return { label: "Incompatível", tone: "danger" };
    case "catalog_prefix_current_match":
      return { label: "Regra parcial: revisar", tone: "warning" };
    case "catalog_prefix_current_mismatch":
      return { label: "Incompatível: revisar", tone: "danger" };
    case "catalog_external_confirmed_mismatch":
      return { label: "Incompatível confirmado", tone: "danger" };
    case "catalog_external_conflict":
      return { label: "Fontes divergentes: revisar", tone: "danger" };
    case "catalog_no_cest_for_ncm":
      return { label: "Sem CEST elegível: revisar", tone: "danger" };
    case "catalog_not_found":
      return { label: "Não verificado", tone: "warning" };
    case "catalog_multiple":
      return { label: "Múltiplas opções", tone: "warning" };
    case "catalog_ranked":
      return { label: "Sugestão disponível", tone: "warning" };
    case "catalog_found":
      return { label: "Referência encontrada", tone: "neutral" };
    default:
      return { label: "Não verificado", tone: "neutral" };
  }
}

function rowSelector(id: string) {
  return `tr[data-row="${CSS.escape(id)}"]`;
}

export default function Dashboard() {
  const { logout } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [audit, setAudit] = useState<AuditUploadResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState<Record<string, ReviewDecision>>({});
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [bulkDecision, setBulkDecision] = useState<ReviewDecision | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(true);
  const [announcement, setAnnouncement] = useState("");
  const auditRef = useRef(audit);
  const timers = useRef(new Map<string, { timer: number; item: AuditItem; decision: ReviewDecision }>());
  auditRef.current = audit;

  useEffect(() => {
    let cancelled = false;

    async function restoreLatestAudit() {
      const storedAuditId = localStorage.getItem(LAST_AUDIT_ID_KEY);
      try {
        const restored = storedAuditId ? await getAudit(storedAuditId) : await getLatestAudit();
        if (cancelled) return;
        setAudit(restored);
        setShowUpload(false);
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 404) {
          localStorage.removeItem(LAST_AUDIT_ID_KEY);
        }
      }
    }

    void restoreLatestAudit();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!audit || audit.status !== "processing") return;
    const auditId = audit.audit_id;
    let cancelled = false;
    let failures = 0;
    let timer: number;

    // Encadeia timeouts (em vez de setInterval) para nunca sobrepor requisições lentas.
    async function tick() {
      try {
        const next = await getAudit(auditId);
        if (cancelled) return;
        failures = 0;
        setPollError(null);
        setAudit(next);
        if (next.status === "processing") timer = window.setTimeout(tick, POLL_MS);
      } catch {
        if (cancelled) return;
        failures += 1;
        if (failures >= MAX_POLL_FAILURES) {
          setPollError("Perdemos a conexão com o servidor. Recarregue a página para retomar o acompanhamento.");
          return;
        }
        setPollError("Não foi possível atualizar o andamento. Tentando novamente.");
        timer = window.setTimeout(tick, POLL_MS * 2);
      }
    }

    timer = window.setTimeout(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [audit?.audit_id, audit?.status]);

  const hasPending = Object.keys(pending).length > 0;
  useEffect(() => {
    if (!hasPending) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasPending]);

  const counts = useMemo(() => {
    const items = audit?.data ?? [];
    return {
      all: items.length,
      review: items.filter(needsReview).length,
      cest_alert: items.filter(hasCestAlert).length,
      approved: items.filter((item) => item.status === "approved").length,
      rejected: items.filter((item) => item.status === "rejected").length,
      no_suggestion: items.filter((item) => item.status === "no_suggestion").length,
    } satisfies Record<Filter, number>;
  }, [audit]);

  const reviewableItems = useMemo(
    () => (audit?.data ?? []).filter(needsReview),
    [audit],
  );

  const filteredItems = useMemo(() => {
    if (!audit) return [];
    const normalizedQuery = query.trim().toLocaleLowerCase("pt-BR");
    const digitsQuery = normalizedQuery.replace(/\D/g, "");
    return audit.data.filter((item) => {
      if (!matchesFilter(item, filter)) return false;
      if (!normalizedQuery) return true;
      const text = [item.codigo_produto, item.descricao, item.ncm_atual, item.ncm_sugerido, item.cest_atual, item.cest_sugerido]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase("pt-BR");
      // Permite buscar NCM com ou sem pontuação ("2203.00.00" ou "22030000").
      return text.includes(normalizedQuery) || (digitsQuery.length >= 4 && text.includes(digitsQuery));
    }).sort(byUrgency);
  }, [audit, filter, query]);

  const progress = audit && audit.progresso.total > 0
    ? Math.round((audit.progresso.processados / audit.progresso.total) * 100)
    : 0;
  const analysing = audit?.status === "processing" && !audit.data.length;

  function chooseFile(candidate: File | null | undefined) {
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith(".xlsx")) {
      setError("Envie uma planilha no formato .xlsx.");
      return;
    }
    setError(null);
    setFile(candidate);
  }

  async function flushPending() {
    const queued = [...timers.current.values()];
    await Promise.all(queued.map(({ timer, item, decision }) => {
      window.clearTimeout(timer);
      return commitDecision(item, decision);
    }));
  }

  async function handleUpload() {
    if (!file) return;
    if (audit && counts.review > 0 && !window.confirm(`Esta auditoria ainda tem ${counts.review} ${counts.review === 1 ? "item aguardando" : "itens aguardando"} revisão. Iniciar uma nova mesmo assim?`)) return;
    await flushPending();
    setUploading(true);
    setError(null);
    try {
      const created = await uploadAudit(file);
      localStorage.setItem(LAST_AUDIT_ID_KEY, created.audit_id);
      setAudit(created);
      setFile(null);
      setShowUpload(false);
      setPollError(null);
      setFilter("all");
      setQuery("");
      setOpenId(null);
    } catch (error) {
      const timedOut = axios.isAxiosError(error) && error.code === "ECONNABORTED";
      setError(timedOut
        ? "O envio demorou mais que o esperado. Recarregue a página para retomar a última auditoria antes de tentar novamente."
        : uploadErrorMessage(error));
    } finally {
      setUploading(false);
    }
  }

  async function handleLogout() {
    await flushPending();
    logout();
  }

  function focusAfter(followingIds: string[]) {
    requestAnimationFrame(() => {
      for (const id of followingIds) {
        const next = document.querySelector<HTMLButtonElement>(`${rowSelector(id)} .review-btn.approve:not(:disabled)`);
        if (next) return next.focus();
      }
      document.getElementById("results-title")?.focus();
    });
  }

  async function commitDecision(item: AuditItem, decision: ReviewDecision) {
    const current = auditRef.current;
    if (!current) return;
    // Captura o foco antes de a linha mudar, para devolvê-lo à próxima pendência.
    const rowEl = document.querySelector(rowSelector(item.id));
    const hadFocus = Boolean(rowEl?.contains(document.activeElement));
    const followingIds: string[] = [];
    for (let sibling = rowEl?.nextElementSibling; sibling; sibling = sibling.nextElementSibling) {
      const id = sibling.getAttribute("data-row");
      if (id) followingIds.push(id);
    }

    timers.current.delete(item.id);
    setPending((value) => {
      const next = { ...value };
      delete next[item.id];
      return next;
    });
    setBusyIds((value) => new Set(value).add(item.id));
    try {
      const updated = await reviewAuditItem(current.audit_id, item.id, decision);
      setAudit((value) => value ? {
        ...value,
        data: value.data.map((candidate) => candidate.id === item.id ? updated : candidate),
      } : value);
      setAnnouncement(`${item.descricao}: ${decisionMeta[decision].done}.`);
      if (hadFocus) focusAfter(followingIds);
    } catch (error) {
      setError(reviewErrorMessage(error, item));
    } finally {
      setBusyIds((value) => {
        const next = new Set(value);
        next.delete(item.id);
        return next;
      });
    }
  }

  function decide(item: AuditItem, decision: ReviewDecision) {
    if (timers.current.has(item.id)) return;
    setError(null);
    const timer = window.setTimeout(() => commitDecision(item, decision), UNDO_MS);
    timers.current.set(item.id, { timer, item, decision });
    setPending((value) => ({ ...value, [item.id]: decision }));
    setAnnouncement(`${item.descricao} será ${decisionMeta[decision].done} em 5 segundos. Use Desfazer para cancelar.`);
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`${rowSelector(item.id)} .undo-btn`)?.focus());
  }

  function undo(item: AuditItem) {
    const queued = timers.current.get(item.id);
    if (!queued) return;
    window.clearTimeout(queued.timer);
    timers.current.delete(item.id);
    setPending((value) => {
      const next = { ...value };
      delete next[item.id];
      return next;
    });
    setAnnouncement(`Decisão sobre ${item.descricao} desfeita.`);
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`${rowSelector(item.id)} .review-btn.approve`)?.focus());
  }

  async function decideAll(decision: ReviewDecision) {
    const current = auditRef.current;
    if (!current || !reviewableItems.length || bulkDecision) return;
    if (hasPending) {
      setError("Aguarde a conclusão das decisões individuais ou use Desfazer antes de decidir em lote.");
      return;
    }
    const action = decision === "approved" ? "aprovar" : "rejeitar";
    const count = reviewableItems.length;
    if (!window.confirm(`Deseja ${action} os ${count} ${count === 1 ? "item pendente" : "itens pendentes"}? Esta ação não poderá ser desfeita.`)) return;

    setBulkDecision(decision);
    setError(null);
    setBusyIds(new Set(reviewableItems.map((item) => item.id)));
    let completed = 0;
    let failed = 0;
    for (const item of reviewableItems) {
      try {
        const updated = await reviewAuditItem(current.audit_id, item.id, decision);
        completed += 1;
        setAudit((value) => value ? {
          ...value,
          data: value.data.map((candidate) => candidate.id === item.id ? updated : candidate),
        } : value);
      } catch {
        failed += 1;
      } finally {
        setBusyIds((value) => {
          const next = new Set(value);
          next.delete(item.id);
          return next;
        });
      }
    }
    setBulkDecision(null);
    if (failed) {
      setError(`${completed} itens foram ${decision === "approved" ? "aprovados" : "rejeitados"}; ${failed} não puderam ser atualizados. Recarregue a página antes de tentar novamente.`);
      return;
    }
    setAnnouncement(`${completed} ${completed === 1 ? "item foi" : "itens foram"} ${decision === "approved" ? "aprovados" : "rejeitados"}.`);
  }

  function downloadCsv(columns: string[], rows: string[][], filename: string) {
    const csv = [columns, ...rows].map((row) => row.map(csvValue).join(";")).join("\n");
    const url = URL.createObjectURL(new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function exportDetailedResults() {
    if (!audit?.data.length) return;
    const columns = ["Código", "Descrição", "NCM atual", "NCM sugerido", "Resultado NCM", "CEST atual", "CEST sugerido", "Resultado CEST", "Score", "Decisão humana", "Motivo", "Status técnico CEST", "Fonte CEST", "Evidência CEST", "Tentativas de consulta", "Fonte NCM", "Versão NCM"];
    const rows = audit.data.map((item) => [
      item.codigo_produto,
      item.descricao,
      item.ncm_atual ?? "",
      item.ncm_sugerido ?? "",
      ncmResult(item).label,
      item.cest_atual ?? "",
      item.cest_sugerido ?? "",
      cestResult(item).label,
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
    downloadCsv(columns, rows, `auditoria-${audit.audit_id}.csv`);
  }

  function exportSummaryResults() {
    if (!audit?.data.length) return;
    const columns = ["codigo_produto", "descricao", "NCM", "CEST"];
    const rows = audit.data
      .filter(hasSuggestedClassificationChange)
      .map((item) => [
        item.codigo_produto,
        item.descricao,
        proposedCode(item.ncm_atual, item.ncm_sugerido),
        proposedCode(item.cest_atual, item.cest_sugerido),
      ]);
    downloadCsv(columns, rows, `auditoria-${audit.audit_id}-resumida.csv`);
  }

  function escapeXml(value: string) {
    return value.replace(/[<>&"']/g, (character) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[character] ?? character);
  }

  function excelColumn(column: number) {
    let result = "";
    let value = column;
    while (value > 0) {
      value -= 1;
      result = String.fromCharCode(65 + (value % 26)) + result;
      value = Math.floor(value / 26);
    }
    return result;
  }

  function inlineTextCell(reference: string, value: string, style: number) {
    return `<c r="${reference}" s="${style}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
  }

  function buildStyledWorkbook(title: string, subtitle: string, columns: string[], rows: string[][]) {
    const lastColumn = excelColumn(columns.length);
    const dateLine = `Auditoria: ${audit?.audit_id ?? ""} | Gerado em: ${new Date().toLocaleString("pt-BR")}`;
    const widthFor = (header: string) => header === "Descrição" || header === "Motivo" || header === "Evidência CEST" ? 38
      : header === "Tentativas de consulta" || header === "Fonte CEST" || header === "Fonte NCM" ? 28
        : header === "codigo_produto" || header === "Código" ? 18 : 17;
    const rowXml = (rowNumber: number, values: string[], style: number) => `<row r="${rowNumber}" ht="20" customHeight="1">${values.map((value, index) => inlineTextCell(`${excelColumn(index + 1)}${rowNumber}`, value, index === 1 || index >= 9 ? style + 2 : style)).join("")}</row>`;
    const sheetXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="5" topLeftCell="A6" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${columns.map((header, index) => `<col min="${index + 1}" max="${index + 1}" width="${widthFor(header)}" customWidth="1"/>`).join("")}</cols><sheetData>
<row r="1" ht="31" customHeight="1">${inlineTextCell("A1", title, 1)}</row><row r="2" ht="20" customHeight="1">${inlineTextCell("A2", subtitle, 2)}</row><row r="3" ht="18" customHeight="1">${inlineTextCell("A3", dateLine, 3)}</row><row r="5" ht="25" customHeight="1">${columns.map((header, index) => inlineTextCell(`${excelColumn(index + 1)}5`, header, 4)).join("")}</row>${rows.map((row, index) => rowXml(index + 6, row, index % 2 === 0 ? 5 : 6)).join("")}</sheetData><autoFilter ref="A5:${lastColumn}${Math.max(5, rows.length + 5)}"/><mergeCells count="3"><mergeCell ref="A1:${lastColumn}1"/><mergeCell ref="A2:${lastColumn}2"/><mergeCell ref="A3:${lastColumn}3"/></mergeCells><pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/></worksheet>`;
    const stylesXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="4"><font><sz val="10"/><name val="Aptos"/></font><font><b/><sz val="18"/><color rgb="FFFFFFFF"/><name val="Aptos Display"/></font><font><sz val="10"/><color rgb="FF49657B"/><name val="Aptos"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font></fonts><fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF123B5D"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0E7192"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF2F7F9"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="thin"><color rgb="FFD8E1E6"/></bottom><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="9"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="49" fontId="1" fillId="2" borderId="0" applyFont="1" applyFill="1"/><xf numFmtId="49" fontId="2" fillId="0" borderId="0" applyFont="1"/><xf numFmtId="49" fontId="2" fillId="0" borderId="0" applyFont="1"/><xf numFmtId="49" fontId="3" fillId="3" borderId="1" applyFont="1" applyFill="1" applyBorder="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf numFmtId="49" fontId="0" fillId="0" borderId="1" applyBorder="1"><alignment vertical="center"/></xf><xf numFmtId="49" fontId="0" fillId="4" borderId="1" applyFill="1" applyBorder="1"><alignment vertical="center"/></xf><xf numFmtId="49" fontId="0" fillId="0" borderId="1" applyBorder="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="49" fontId="0" fillId="4" borderId="1" applyFill="1" applyBorder="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs></styleSheet>`;
    const files = {
      "[Content_Types].xml": strToU8("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/><Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/><Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/></Types>"),
      "_rels/.rels": strToU8("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>"),
      "xl/workbook.xml": strToU8("<?xml version=\"1.0\" encoding=\"UTF-8\"?><workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"Relatorio\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>"),
      "xl/_rels/workbook.xml.rels": strToU8("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/><Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/></Relationships>"),
      "xl/worksheets/sheet1.xml": strToU8(sheetXml),
      "xl/styles.xml": strToU8(stylesXml),
    };
    return zipSync(files, { level: 6 });
  }

  function downloadWorkbook(content: Uint8Array, filename: string) {
    const url = URL.createObjectURL(new Blob([content], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function exportStyledDetailedResults() {
    if (!audit?.data.length) return;
    const columns = ["Código", "Descrição", "NCM atual", "NCM sugerido", "Resultado NCM", "CEST atual", "CEST sugerido", "Resultado CEST", "Score", "Decisão humana", "Motivo", "Status técnico CEST", "Fonte CEST", "Evidência CEST", "Tentativas de consulta", "Fonte NCM", "Versão NCM"];
    const rows = audit.data.map((item) => [item.codigo_produto, item.descricao, item.ncm_atual ?? "", item.ncm_sugerido ?? "", ncmResult(item).label, item.cest_atual ?? "", item.cest_sugerido ?? "", cestResult(item).label, item.score.toString(), statusMeta[item.status].label, item.motivo, item.cest_status ?? "", item.cest_source_url ?? "", item.cest_evidence ?? "", attemptSummary(item), item.fonte_referencia ?? "", item.versao_referencia ?? ""]);
    downloadWorkbook(buildStyledWorkbook("Relatório detalhado de auditoria", "Todas as classificações, evidências e decisões da auditoria.", columns, rows), `auditoria-${audit.audit_id}-detalhada.xlsx`);
  }

  function exportStyledSummaryResults() {
    if (!audit?.data.length) return;
    const columns = ["codigo_produto", "descricao", "NCM", "CEST"];
    const rows = audit.data.filter(hasSuggestedClassificationChange).map((item) => [item.codigo_produto, item.descricao, proposedCode(item.ncm_atual, item.ncm_sugerido), proposedCode(item.cest_atual, item.cest_sugerido)]);
    downloadWorkbook(buildStyledWorkbook("Relatório resumido de alterações", "Somente produtos com alteração sugerida de NCM ou CEST.", columns, rows), `auditoria-${audit.audit_id}-resumida.xlsx`);
  }

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><ShieldCheck size={17} strokeWidth={2} aria-hidden="true" /></span>
          Auditor NCM/CEST
        </div>
        <div className="topbar-meta">
          <span className="trust-note"><ListChecks size={15} aria-hidden="true" /> Recomendações exigem revisão humana</span>
          <ThemeToggle />
          <button className="button button-ghost" onClick={handleLogout}><LogOut size={15} aria-hidden="true" /> Sair</button>
        </div>
      </header>

      <main className="workspace" aria-labelledby="page-title">
        <div className="page-head">
          <div>
            <h1 id="page-title">{audit ? "Fila de conferência" : "Nova auditoria"}</h1>
            <p>{audit
              ? "Aprove apenas o que tiver evidência suficiente. Cada decisão fica registrada."
              : "Envie o cadastro de produtos, acompanhe a análise e decida item a item."}</p>
          </div>
          {audit ? <button className="button button-ghost" onClick={() => { setShowUpload((value) => !value); setFile(null); }} aria-expanded={showUpload}>
            {showUpload ? <><X size={15} aria-hidden="true" /> Cancelar</> : <><FileUp size={15} aria-hidden="true" /> Nova auditoria</>}
          </button> : null}
        </div>

        {!audit || showUpload ? <section className="upload-panel" aria-label="Envio de planilha">
          <label
            className={`dropzone ${dragging ? "dropzone-dragging" : file ? "dropzone-ready" : ""}`}
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }}
            onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files?.[0]); }}
          >
            <input type="file" accept=".xlsx" onChange={(event) => chooseFile(event.target.files?.[0])} />
            <span className="dropzone-icon" aria-hidden="true">{file ? <FileSpreadsheet size={20} /> : <FileUp size={20} />}</span>
            <span className="dropzone-copy">
              <strong>{file ? file.name : dragging ? "Solte a planilha aqui" : "Arraste a planilha ou clique para escolher"}</strong>
              <small>{file ? `${formatBytes(file.size)} · pronta para auditar` : "Arquivo .xlsx com código, descrição, NCM e CEST"}</small>
            </span>
            <span className="dropzone-hint" aria-hidden="true">{file ? "Trocar arquivo" : "Procurar"}</span>
          </label>
          <button className="button button-primary button-lg" disabled={!file || uploading} onClick={handleUpload}>
            {uploading ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : <Upload size={17} aria-hidden="true" />}
            {uploading ? "Enviando" : "Iniciar auditoria"}
          </button>
        </section> : null}

        {error ? <div className="notice notice-error" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{error}</span></div> : null}
        {pollError ? <div className="notice notice-error" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{pollError}</span></div> : null}
        {audit?.errors.length ? <div className="notice notice-error" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{audit.errors.join(" ")}</span></div> : null}
        <div className="sr-only" role="status" aria-live="polite">{announcement}</div>

        {audit ? <>
          <section className={`run-bar run-${audit.status}`} aria-label="Andamento da auditoria">
            <div className="run-file">
              <FileSpreadsheet size={17} aria-hidden="true" />
              <strong title={audit.arquivo}>{audit.arquivo}</strong>
              <span className={`badge badge-${audit.status}`}>
                {audit.status === "processing" ? <LoaderCircle className="spin" size={12} aria-hidden="true" /> : null}
                {runMeta[audit.status]}
              </span>
            </div>
            <div className="run-progress">
              <div className="run-progress-meta"><span>{audit.progresso.processados} de {audit.progresso.total} produtos analisados</span><strong>{progress}%</strong></div>
              <div className="meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label="Progresso da análise"><span style={{ transform: `scaleX(${progress / 100})` }} /></div>
            </div>
          </section>

          <section className="summary" aria-label="Filtrar por estado">
            {tiles.map((tile) => {
              const value = analysing ? null : counts[tile.key];
              return <button key={tile.key} type="button" className={`summary-tile ${tile.tone}`} data-zero={value === 0 || undefined} aria-pressed={filter === tile.key} disabled={analysing} onClick={() => setFilter(tile.key)}>
                <span>{tile.label}</span>
                <strong>{value ?? <span className="skeleton skeleton-num" aria-label="Em análise" />}</strong>
              </button>;
            })}
          </section>

          <section className="results" aria-labelledby="results-title">
            <div className="results-head">
              <h2 id="results-title" tabIndex={-1}>
                {tiles.find((tile) => tile.key === filter)?.label}
                <small>{analysing ? "Em análise" : `${filteredItems.length} ${filteredItems.length === 1 ? "item" : "itens"}`}</small>
              </h2>
              <div className="results-tools">
                <label className="search-field">
                  <Search size={15} aria-hidden="true" />
                  <span className="sr-only">Buscar produto</span>
                  <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar produto ou NCM" />
                </label>
                <div className="bulk-review-actions" aria-label="Decisões em lote">
                  <button className="review-btn approve" onClick={() => void decideAll("approved")} disabled={!reviewableItems.length || Boolean(bulkDecision) || hasPending} title="Aprovar todos os itens aguardando revisão">
                    {bulkDecision === "approved" ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : <Check size={14} aria-hidden="true" />} Aprovar todos ({reviewableItems.length})
                  </button>
                  <button className="review-btn reject" onClick={() => void decideAll("rejected")} disabled={!reviewableItems.length || Boolean(bulkDecision) || hasPending} title="Rejeitar todos os itens aguardando revisão">
                    {bulkDecision === "rejected" ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : <X size={14} aria-hidden="true" />} Rejeitar todos ({reviewableItems.length})
                  </button>
                </div>
                <button className="button button-ghost" onClick={() => void exportStyledDetailedResults()} disabled={!audit.data.length}><Download size={15} aria-hidden="true" /> Detalhada</button>
                <button className="button button-ghost" onClick={() => void exportStyledSummaryResults()} disabled={!audit.data.length}><Download size={15} aria-hidden="true" /> Resumida</button>
              </div>
            </div>

            {analysing ? <SkeletonTable /> : null}
            {!audit.data.length && audit.status === "failed" ? <EmptyState icon={<AlertTriangle size={20} />} title="A auditoria não foi concluída" text="Revise a referência NCM e envie a planilha novamente." /> : null}
            {!audit.data.length && audit.status === "completed" ? <EmptyState icon={<FileSpreadsheet size={20} />} title="Nenhum produto encontrado" text="A planilha não trouxe linhas válidas para auditar." /> : null}
            {audit.data.length ? <div className="table-wrap">
              <table>
                <thead><tr><th>Produto</th><th>Resultado NCM</th><th>Resultado CEST</th><th className="num">Confiança</th><th>Decisão</th><th className="actions-cell"><span className="sr-only">Decisão</span></th></tr></thead>
                <tbody>
                  {filteredItems.map((item) => <AuditRow
                    key={item.id}
                    item={item}
                    pending={pending[item.id]}
                    busy={busyIds.has(item.id)}
                    open={openId === item.id}
                    onToggle={() => setOpenId((current) => current === item.id ? null : item.id)}
                    onDecide={decide}
                    onUndo={undo}
                  />)}
                </tbody>
              </table>
              {!filteredItems.length ? <EmptyState
                icon={<Search size={20} />}
                title={filter === "review" && !query ? "Nada aguardando revisão" : "Nenhum item encontrado"}
                text={filter === "review" && !query ? "Todas as recomendações desta auditoria já foram decididas." : "Ajuste a busca ou escolha outro estado no resumo acima."}
                action={<button className="button button-ghost" onClick={() => { setQuery(""); setFilter("all"); }}>Ver todos os produtos</button>}
              /> : null}
            </div> : null}
          </section>
        </> : <ol className="how-it-works">
          <li><FileUp size={18} aria-hidden="true" /><strong>Envie o cadastro</strong><span>Uma planilha .xlsx com os produtos e a classificação atual.</span></li>
          <li><ListChecks size={18} aria-hidden="true" /><strong>Revise com evidência</strong><span>Cada sugestão mostra a fonte consultada e o motivo.</span></li>
          <li><Download size={18} aria-hidden="true" /><strong>Exporte as decisões</strong><span>Baixe o CSV com o que foi aprovado ou rejeitado.</span></li>
        </ol>}
      </main>
    </>
  );
}

function AuditRow({ item, pending, busy, open, onToggle, onDecide, onUndo }: {
  item: AuditItem;
  pending: ReviewDecision | undefined;
  busy: boolean;
  open: boolean;
  onToggle: () => void;
  onDecide: (item: AuditItem, decision: ReviewDecision) => void;
  onUndo: (item: AuditItem) => void;
}) {
  const meta = pending ? decisionMeta[pending] : statusMeta[item.status];
  const ncmClassification = ncmResult(item);
  const cestClassification = cestResult(item);
  const canReview = needsReview(item);
  const decided = item.status === "approved" || item.status === "rejected";
  const hasEvidence = Boolean(item.fonte_referencia || item.cest_status || item.cest_evidence || item.cest_source_url || item.reference_attempts?.length);
  const detailId = `evidence-${item.id}`;
  const rowClass = ["row", open && "row-open", decided && "row-decided", pending && `row-pending row-pending-${pending}`].filter(Boolean).join(" ");

  return <Fragment>
    <tr className={rowClass} data-row={item.id}>
      <td className="cell-product">
        <div className="product">
          <strong>{item.descricao}</strong>
          <span className="mono">{item.codigo_produto}</span>
          {hasEvidence ? <button type="button" className="evidence-toggle" aria-expanded={open} aria-controls={open ? detailId : undefined} onClick={onToggle}>
            <ChevronRight size={13} aria-hidden="true" /> {open ? "Ocultar evidências" : "Ver evidências"}
          </button> : null}
        </div>
      </td>
      <td className="cell-ncm" data-label="NCM">
        <div className="classification">
          <CodeChange label="NCM" current={item.ncm_atual} suggested={item.ncm_sugerido} groups={NCM_GROUPS} empty="Sem NCM informado" />
          <span className={`badge ${ncmClassification.tone}`}>NCM: {ncmClassification.label}</span>
        </div>
        <span className="reason">{item.motivo}</span>
      </td>
      <td className="cell-cest" data-label="CEST">
        <div className="classification">
          <CodeChange label="CEST" current={item.cest_atual} suggested={item.cest_sugerido} groups={CEST_GROUPS} empty={item.cest_status === "catalog_not_found" ? "Não encontrado" : "Sem CEST informado"} />
          <span className={`badge ${cestClassification.tone}`}>CEST: {cestClassification.label}</span>
        </div>
      </td>
      <td className="num cell-score" data-label="Confiança"><Confidence score={item.score} /></td>
      <td className="cell-status"><span className={`badge ${meta.tone}`}>{meta.label}</span></td>
      <td className="actions-cell">
        {pending ? <button className="review-btn undo-btn" onClick={() => onUndo(item)}>
          <RotateCcw size={14} aria-hidden="true" /> Desfazer
        </button> : canReview ? <div className="review-actions">
          <button className="review-btn approve" disabled={busy} onClick={() => onDecide(item, "approved")}>
            {busy ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : <Check size={14} aria-hidden="true" />} Aprovar
          </button>
          <button className="review-btn reject" disabled={busy} onClick={() => onDecide(item, "rejected")}>
            <X size={14} aria-hidden="true" /> Rejeitar
          </button>
        </div> : null}
      </td>
    </tr>
    {open && hasEvidence ? <tr className="evidence-row" id={detailId}>
      <td colSpan={6}><EvidencePanel item={item} /></td>
    </tr> : null}
  </Fragment>;
}

function CodeChange({ label, current, suggested, groups, empty }: {
  label: string;
  current: string | null;
  suggested: string | null;
  groups: number[];
  empty: string;
}) {
  if (!suggested || suggested === current) {
    return current ? <span className="code">{formatCode(current, groups)}</span> : <span className="code-empty">{empty}</span>;
  }
  return <div className="code-change">
    <span className="sr-only">{label} atual {current ? formatCode(current, groups) : "não informado"}, sugerido {formatCode(suggested, groups)}</span>
    <span className="code code-old" aria-hidden="true">{current ? formatCode(current, groups) : "vazio"}</span>
    <ArrowRight size={13} aria-hidden="true" />
    <span className="code code-new" aria-hidden="true">{diffDigits(current, suggested, groups)}</span>
  </div>;
}

function groupBreaks(groups: number[]) {
  const breaks = new Set<number>();
  groups.slice(0, -1).reduce((position, size) => {
    breaks.add(position + size);
    return position + size;
  }, 0);
  return breaks;
}

function formatCode(value: string, groups: number[]) {
  const digits = value.replace(/\D/g, "");
  const total = groups.reduce((sum, size) => sum + size, 0);
  if (digits.length !== total) return value;
  const breaks = groupBreaks(groups);
  return digits.split("").map((digit, index) => (breaks.has(index) ? "." : "") + digit).join("");
}

// Destaca os dígitos que mudam entre o código atual e o sugerido, preservando a pontuação.
function diffDigits(current: string | null, suggested: string, groups: number[]) {
  const oldDigits = (current ?? "").replace(/\D/g, "");
  const newDigits = suggested.replace(/\D/g, "");
  const total = groups.reduce((sum, size) => sum + size, 0);
  if (newDigits.length !== total) return suggested;
  const breaks = groupBreaks(groups);
  return newDigits.split("").map((digit, index) => <Fragment key={index}>
    {breaks.has(index) ? "." : ""}
    {digit !== oldDigits[index] ? <mark>{digit}</mark> : digit}
  </Fragment>);
}

function Confidence({ score }: { score: number }) {
  const level = score >= 85 ? 3 : score >= 60 ? 2 : 1;
  const label = level === 3 ? "alta" : level === 2 ? "média" : "baixa";
  return <span className={`confidence confidence-${label}`} title={`Confiança ${label}`}>
    {score.toFixed(1).replace(".", ",")}%
    <span className="signal" aria-hidden="true">{[1, 2, 3].map((bar) => <i key={bar} className={bar <= level ? "on" : ""} />)}</span>
    <span className="sr-only">, confiança {label}</span>
  </span>;
}

function EvidencePanel({ item }: { item: AuditItem }) {
  const attempts = item.reference_attempts ?? [];
  return <dl className="evidence">
    {item.fonte_referencia ? <div><dt>Referência NCM</dt><dd>{item.fonte_referencia}{item.versao_referencia ? ` (${item.versao_referencia})` : ""}</dd></div> : null}
    {item.cest_status ? <div><dt>Status CEST</dt><dd>{formatCestStatus(item.cest_status)}</dd></div> : null}
    {item.cest_evidence ? <div><dt>Justificativa CEST</dt><dd>{item.cest_evidence}</dd></div> : null}
    {isExternalUrl(item.cest_source_url) ? <div><dt>Fonte CEST</dt><dd><a href={item.cest_source_url ?? undefined} target="_blank" rel="noreferrer">Abrir fonte consultada</a></dd></div> : null}
    {attempts.length ? <div className="evidence-attempts"><dt>Consultas realizadas</dt><dd><ul>{attempts.map((attempt, index) => <li key={`${attempt.source}-${attempt.state}-${index}`}><strong>{attempt.source}</strong>: {attempt.state}{attempt.detail ? ` (${attempt.detail})` : ""}</li>)}</ul></dd></div> : null}
  </dl>;
}

function formatCestStatus(status: string) {
  const labels: Record<string, string> = {
    catalog_found: "Encontrado no catálogo local",
    catalog_current_match: "CEST atual compatível com o catálogo",
    catalog_current_mismatch: "CEST atual incompatível com o NCM",
    catalog_prefix_current_match: "CEST atual coberto por regra parcial; revisar",
    catalog_prefix_current_mismatch: "CEST atual incompatível com regra parcial; revisar",
    catalog_external_confirmed_mismatch: "CEST incompatível confirmado por fonte externa",
    catalog_external_conflict: "Catálogo local e fonte externa divergem; revisão necessária",
    catalog_no_cest_for_ncm: "CEST informado, mas sem CEST elegível para o NCM",
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

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

function SkeletonTable() {
  return <div className="table-wrap" role="status" aria-busy="true">
    <span className="sr-only">Carregando resultados</span>
    <table aria-hidden="true">
      <tbody>
        {[0, 1, 2, 3, 4].map((row) => <tr key={row} className="skeleton-row">
          <td style={{ width: "34%" }}><span className="skeleton" style={{ width: `${70 - row * 6}%` }} /><span className="skeleton" style={{ width: "28%" }} /></td>
          <td><span className="skeleton" style={{ width: "80%" }} /></td>
          <td><span className="skeleton" style={{ width: "50%" }} /></td>
          <td><span className="skeleton" style={{ width: "60%" }} /></td>
          <td><span className="skeleton" style={{ width: "70%" }} /></td>
        </tr>)}
      </tbody>
    </table>
  </div>;
}

function EmptyState({ icon, title, text, action }: { icon: React.ReactNode; title: string; text: string; action?: React.ReactNode }) {
  return <div className="empty-state"><span aria-hidden="true">{icon}</span><strong>{title}</strong><p>{text}</p>{action}</div>;
}

// Descrições vêm de planilhas enviadas e o CSV é aberto no Excel: neutraliza fórmulas.
function csvValue(value: string) {
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return `"${safe.replaceAll("\"", "\"\"")}"`;
}
