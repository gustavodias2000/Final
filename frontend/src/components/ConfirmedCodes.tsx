import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { AlertTriangle, BadgeCheck, Download, FileUp, LoaderCircle, Search, Trash2, X } from "lucide-react";

import { deleteConfirmedCode, importConfirmedCodes, listConfirmedCodes } from "../api/confirmedCodes";
import type { ConfirmedCode, ConfirmedCodeImportResult } from "../api/contracts";
import type { ConfirmFn } from "./ConfirmDialog";
import "./history.css";
import "./confirmed.css";

const LIST_LIMIT = 50;
const dateFormat = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short" });

function formatNcm(code: string) {
  return code.length === 8 ? `${code.slice(0, 4)}.${code.slice(4, 6)}.${code.slice(6)}` : code;
}

function apiMessage(error: unknown, fallback: string) {
  if (!axios.isAxiosError(error)) return fallback;
  const payload = error.response?.data as { detail?: unknown; details?: unknown } | undefined;
  if (Array.isArray(payload?.details) && payload.details.every((detail) => typeof detail === "string")) return payload.details.join(" ");
  if (typeof payload?.detail === "string") return payload.detail;
  return fallback;
}

// Códigos NCM que a empresa já confirmou. Na análise valem como a evidência mais forte:
// primeiro pelo código do produto (ou EAN), depois por descrição praticamente idêntica.
export function ConfirmedCodes({ confirm, onClose }: { confirm: ConfirmFn; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [codes, setCodes] = useState<ConfirmedCode[] | null>(null);
  const [total, setTotal] = useState(0);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ConfirmedCodeImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let active = true;
    setFailed(false);
    listConfirmedCodes(debouncedQuery, LIST_LIMIT)
      .then((result) => {
        if (!active) return;
        setCodes(result.data);
        setTotal(result.total);
      })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [debouncedQuery, reload]);

  async function handleImport(file: File | undefined) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setImportError("Envie uma planilha no formato .xlsx.");
      return;
    }
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    try {
      setImportResult(await importConfirmedCodes(file));
      setReload((value) => value + 1);
    } catch (error) {
      setImportError(apiMessage(error, "Não foi possível importar a planilha. Tente novamente."));
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function handleRemove(code: ConfirmedCode) {
    const ok = await confirm({
      title: "Remover este código confirmado?",
      message: `"${code.descricao}" deixa de usar o NCM ${formatNcm(code.ncm)} como referência nas próximas auditorias. Auditorias já feitas não mudam.`,
      confirmLabel: "Remover código",
      tone: "danger",
    });
    if (!ok) return;
    setRemovingId(code.id);
    try {
      await deleteConfirmedCode(code.id);
      setReload((value) => value + 1);
    } catch {
      setImportError("Não foi possível remover o código. Tente novamente.");
    } finally {
      setRemovingId(null);
    }
  }

  function downloadTemplate() {
    const link = document.createElement("a");
    link.href = `${import.meta.env.BASE_URL}modelo-auditoria-ncm-cest.xlsx`;
    link.download = "modelo-auditoria-ncm-cest.xlsx";
    link.click();
  }

  return <section className="history-panel confirmed-panel" aria-labelledby="confirmed-title">
    <div className="history-head">
      <h2 id="confirmed-title"><BadgeCheck size={16} aria-hidden="true" /> Códigos confirmados</h2>
      <small>{total.toLocaleString("pt-BR")} {total === 1 ? "código" : "códigos"}</small>
      <button type="button" className="button button-ghost button-icon history-close" onClick={onClose} aria-label="Fechar códigos confirmados" title="Fechar">
        <X size={15} aria-hidden="true" />
      </button>
    </div>

    <div className="confirmed-intro">
      <p>
        NCMs que a sua empresa já confirmou. Nas próximas auditorias eles valem como a evidência mais forte:
        primeiro pelo código do produto ou EAN, depois por descrição praticamente idêntica.
        Itens aprovados na revisão entram aqui sozinhos.
      </p>
      <div className="confirmed-import">
        <input ref={fileInput} type="file" accept=".xlsx" hidden onChange={(event) => void handleImport(event.target.files?.[0])} />
        <button type="button" className="button button-ghost" onClick={() => fileInput.current?.click()} disabled={importing}>
          {importing ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <FileUp size={15} aria-hidden="true" />}
          {importing ? "Importando" : "Importar planilha"}
        </button>
        <span>
          Mesmo modelo da auditoria; o NCM e o CEST de cada linha são tratados como corretos.{" "}
          <button type="button" className="template-download" onClick={downloadTemplate}><Download size={13} aria-hidden="true" /> Baixar modelo</button>
        </span>
      </div>
      {importResult ? <div className="notice notice-info" role="status">
        <BadgeCheck size={16} aria-hidden="true" />
        <span>
          {importResult.importados} {importResult.importados === 1 ? "código novo" : "códigos novos"}, {importResult.atualizados} {importResult.atualizados === 1 ? "atualizado" : "atualizados"}
          {importResult.ignorados ? `, ${importResult.ignorados} ${importResult.ignorados === 1 ? "linha ignorada" : "linhas ignoradas"}` : ""}.
          {importResult.motivos_ignorados.length ? <details className="confirmed-skipped">
            <summary>Ver linhas ignoradas</summary>
            <ul>{importResult.motivos_ignorados.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          </details> : null}
        </span>
      </div> : null}
      {importError ? <div className="notice notice-error" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>{importError}</span></div> : null}
    </div>

    <div className="confirmed-search">
      <label className="search-field">
        <Search size={15} aria-hidden="true" />
        <span className="sr-only">Buscar código confirmado</span>
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar por descrição, código ou NCM" />
      </label>
    </div>

    {failed ? <div className="history-message history-message-error" role="alert">
      <AlertTriangle size={16} aria-hidden="true" />
      <span>Não foi possível carregar os códigos confirmados.</span>
      <button type="button" className="button button-ghost" onClick={() => setReload((value) => value + 1)}>Tentar de novo</button>
    </div> : codes === null ? <ul className="history-list" aria-label="Carregando códigos confirmados">
      {[0, 1, 2].map((index) => <li key={index} className="history-item history-item-loading">
        <span className="skeleton" style={{ width: "45%" }} />
        <span className="skeleton" style={{ width: "20%" }} />
      </li>)}
    </ul> : !codes.length ? <p className="history-message">
      {debouncedQuery ? "Nenhum código confirmado encontrado para essa busca." : "Nenhum código confirmado ainda. Aprove itens na revisão ou importe uma planilha."}
    </p> : <>
      <ul className="history-list confirmed-list">
        {codes.map((code) => <li key={code.id} className="confirmed-item">
          <div className="history-main">
            <strong title={code.descricao}>{code.descricao}</strong>
            <span className="history-meta">
              {code.codigo_produto ? `Cód. ${code.codigo_produto} · ` : ""}
              {code.origem === "aprovacao" ? "aprovado na revisão" : "importado"} em {dateFormat.format(new Date(code.atualizado_em))}
            </span>
          </div>
          <span className="confirmed-code"><small>NCM</small>{formatNcm(code.ncm)}</span>
          <span className="confirmed-code"><small>CEST</small>{code.cest ?? "—"}</span>
          <button type="button" className="button button-ghost button-icon" onClick={() => void handleRemove(code)} disabled={removingId !== null}
            aria-label={`Remover ${code.descricao}`} title="Remover">
            {removingId === code.id ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <Trash2 size={15} aria-hidden="true" />}
          </button>
        </li>)}
      </ul>
      {codes.length < total && !debouncedQuery ? <p className="confirmed-more">Mostrando os {codes.length} mais recentes. Use a busca para achar os outros.</p> : null}
    </>}
  </section>;
}
