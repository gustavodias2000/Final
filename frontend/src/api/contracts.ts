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

export interface NcmOption {
  ncm: string;
  descricao: string | null;
}

// NCM confirmado pela empresa: aprovado numa revisão ou importado por planilha.
export interface ConfirmedCode {
  id: string;
  codigo_produto: string | null;
  descricao: string;
  ncm: string;
  cest: string | null;
  origem: "aprovacao" | "importacao";
  atualizado_em: string;
}

export interface ConfirmedCodeList {
  total: number;
  data: ConfirmedCode[];
}

export interface ConfirmedCodeImportResult {
  importados: number;
  atualizados: number;
  ignorados: number;
  motivos_ignorados: string[];
}

// Produto parecido do mesmo cadastro, usado como evidência da sugestão de NCM.
export interface CatalogNeighbor {
  codigo_produto: string;
  descricao: string;
  ncm: string;
  score: number;
}

export interface CestCandidate {
  cest: string;
  descricao: string | null;
  score: number | null;
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
  cest_candidates: CestCandidate[];
  cest_escolhido: string | null;
  // Se o NCM informado existe na tabela vigente; vazio em auditorias antigas.
  ncm_status?: "valid" | "invalid" | "missing" | null;
  // De onde veio a sugestão de NCM: produtos parecidos do cadastro ou tabela oficial.
  ncm_fonte?: "confirmado" | "correlacao" | "sinonimo" | "catalogo" | "familia" | "tabela" | null;
  ncm_vizinhos?: CatalogNeighbor[];
  // NCM extinto: códigos vigentes da mesma subposição, para escolha na revisão.
  ncm_opcoes?: NcmOption[];
  ncm_escolhido?: string | null;
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
  // Quando um worker começou a analisar; nulo enquanto a auditoria espera na fila.
  iniciada_em?: string | null;
  errors: string[];
}

export interface ApiError {
  code: string;
  message: string;
  details: string[];
}

// Uma auditoria anterior, sem os itens, para a lista de histórico.
export type AuditHistoryEntry = {
  audit_id: string;
  arquivo: string;
  status: AuditStatus;
  criada_em: string;
  concluida_em: string | null;
  total_produtos: number;
  pendentes: number;
  aprovados: number;
  rejeitados: number;
  sem_sugestao: number;
};
