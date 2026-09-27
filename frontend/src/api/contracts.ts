export type AuditStatus = "processing" | "completed" | "failed";

export type AuditItemStatus =
  | "suggested"
  | "no_suggestion"
  | "pending_review"
  | "approved"
  | "rejected";

export type ReviewDecision = "approved" | "rejected";

export interface ReferenceAttempt {
  source: string;
  state: string;
  source_url: string | null;
  detail: string | null;
}

export interface AuditItem {
  id: string;
  codigo_produto: string;
  descricao: string;
  ncm_atual: string | null;
  ncm_sugerido: string | null;
  cest_atual: string | null;
  cest_sugerido: string | null;
  score: number;
  status: AuditItemStatus;
  motivo: string;
  fonte_referencia: string | null;
  versao_referencia: string | null;
  cest_status: string | null;
  cest_source_url: string | null;
  cest_evidence: string | null;
  reference_attempts: ReferenceAttempt[];
}

export interface AuditSummary {
  total_produtos: number;
  itens_com_sugestao: number;
  itens_sem_sugestao: number;
}

export interface AuditProgress {
  processados: number;
  total: number;
}

export interface AuditUploadResponse {
  audit_id: string;
  status: AuditStatus;
  arquivo: string;
  resumo: AuditSummary;
  data: AuditItem[];
  progresso: AuditProgress;
  errors: string[];
}

export interface ApiError {
  code: string;
  message: string;
  details: string[];
}
