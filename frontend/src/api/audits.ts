import api from "./client";
import type { AuditHistoryEntry, AuditItem, AuditUploadResponse, ReviewDecision } from "./contracts";

export async function uploadAudit(file: File, onProgress?: (percent: number) => void): Promise<AuditUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await api.post<AuditUploadResponse>(
    "/api/v1/audits/upload",
    formData,
    {
      onUploadProgress: (event) => {
        if (onProgress && event.total) onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      },
    },
  );

  return data;
}

export async function getAudit(auditId: string): Promise<AuditUploadResponse> {
  const { data } = await api.get<AuditUploadResponse>(`/api/v1/audits/${auditId}`);
  return data;
}

export async function listAudits(limit = 20): Promise<AuditHistoryEntry[]> {
  const { data } = await api.get<AuditHistoryEntry[]>("/api/v1/audits", { params: { limit } });
  return data;
}

export async function getLatestAudit(): Promise<AuditUploadResponse> {
  const { data } = await api.get<AuditUploadResponse>("/api/v1/audits/latest");
  return data;
}

export async function reviewAuditItem(
  auditId: string,
  itemId: string,
  decision: ReviewDecision,
  cestEscolhido?: string,
  ncmEscolhido?: string,
): Promise<AuditItem> {
  const { data } = await api.post<AuditItem>(
    `/api/v1/audits/${auditId}/items/${itemId}/review`,
    {
      decision,
      ...(cestEscolhido ? { cest_escolhido: cestEscolhido } : {}),
      ...(ncmEscolhido ? { ncm_escolhido: ncmEscolhido } : {}),
    },
  );
  return data;
}
