import { useEffect, useState } from "react";
import { AlertTriangle, Check, FileSpreadsheet, History, LoaderCircle, X } from "lucide-react";

import { listAudits } from "../api/audits";
import type { AuditHistoryEntry, AuditStatus } from "../api/contracts";
import "./history.css";

const HISTORY_LIMIT = 20;

const statusLabel: Record<AuditStatus, string> = {
  processing: "Em análise",
  completed: "Concluída",
  failed: "Interrompida",
};

const dateFormat = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

function plural(count: number, singular: string, pluralForm: string) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

// Auditorias anteriores do tenant, da mais recente para a mais antiga. Abrir uma
// delas substitui a conferência da tela; nada é apagado.
export function AuditHistory({ currentAuditId, openingAuditId, onOpen, onClose }: {
  currentAuditId: string | null;
  openingAuditId: string | null;
  onOpen: (auditId: string) => void;
  onClose: () => void;
}) {
  const [entries, setEntries] = useState<AuditHistoryEntry[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setEntries(null);
    setFailed(false);
    listAudits(HISTORY_LIMIT)
      .then((data) => { if (active) setEntries(data); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [attempt]);

  return <section className="history-panel" aria-labelledby="history-title" aria-busy={entries === null && !failed}>
    <div className="history-head">
      <h2 id="history-title"><History size={16} aria-hidden="true" /> Auditorias anteriores</h2>
      <small>As {HISTORY_LIMIT} mais recentes</small>
      <button type="button" className="button button-ghost button-icon history-close" onClick={onClose} aria-label="Fechar histórico" title="Fechar histórico">
        <X size={15} aria-hidden="true" />
      </button>
    </div>

    {failed ? <div className="history-message history-message-error" role="alert">
      <AlertTriangle size={16} aria-hidden="true" />
      <span>Não foi possível carregar o histórico.</span>
      <button type="button" className="button button-ghost" onClick={() => setAttempt((value) => value + 1)}>Tentar de novo</button>
    </div> : entries === null ? <ul className="history-list" aria-label="Carregando histórico">
      {[0, 1, 2].map((index) => <li key={index} className="history-item history-item-loading">
        <span className="skeleton" style={{ width: "40%" }} />
        <span className="skeleton" style={{ width: "25%" }} />
      </li>)}
    </ul> : !entries.length ? <p className="history-message">Nenhuma auditoria enviada ainda. A primeira aparece aqui assim que você enviar uma planilha.</p>
      : <ul className="history-list">
        {entries.map((entry) => {
          const current = entry.audit_id === currentAuditId;
          const opening = entry.audit_id === openingAuditId;
          return <li key={entry.audit_id} className={`history-item${current ? " history-item-current" : ""}`}>
            <FileSpreadsheet className="history-icon" size={17} aria-hidden="true" />
            <div className="history-main">
              <strong title={entry.arquivo}>{entry.arquivo}</strong>
              <span className="history-meta">
                <time dateTime={entry.criada_em}>{dateFormat.format(new Date(entry.criada_em))}</time>
                {" · "}{plural(entry.total_produtos, "produto", "produtos")}
              </span>
            </div>
            <div className="history-counts">
              {entry.status === "processing" ? <span>Análise em andamento</span>
                : entry.status === "failed" ? <span>Sem resultados</span>
                : <>
                  {entry.pendentes
                    ? <span className="history-count-pending"><strong>{entry.pendentes}</strong> {entry.pendentes === 1 ? "pendente" : "pendentes"}</span>
                    : <span className="history-count-done"><Check size={13} aria-hidden="true" /> Nada pendente</span>}
                  <span><strong>{entry.aprovados}</strong> {entry.aprovados === 1 ? "aprovado" : "aprovados"}</span>
                  <span><strong>{entry.rejeitados}</strong> {entry.rejeitados === 1 ? "rejeitado" : "rejeitados"}</span>
                </>}
            </div>
            <span className={`badge badge-${entry.status}`}>{statusLabel[entry.status]}</span>
            <div className="history-action">
              {current
                ? <span className="history-current">Aberta agora</span>
                : <button type="button" className="button button-ghost" onClick={() => onOpen(entry.audit_id)} disabled={openingAuditId !== null} aria-label={`Abrir ${entry.arquivo}`}>
                  {opening ? <><LoaderCircle className="spin" size={14} aria-hidden="true" /> Abrindo</> : "Abrir"}
                </button>}
            </div>
          </li>;
        })}
      </ul>}
  </section>;
}
