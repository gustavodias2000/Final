import api from "./client";
import type { AuditItem, AuditUploadResponse, ReviewDecision } from "./contracts";

export async function uploadAudit(file: File): Promise<AuditUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await api.post<AuditUploadResponse>(
    "/api/v1/audits/upload",
    formData,
  );

  return data;
}

export async function getAudit(auditId: string): Promise<AuditUploadResponse> {
  const { data } = await api.get<AuditUploadResponse>(`/api/v1/audits/${auditId}`);
  return data;
}

export async function reviewAuditItem(
  auditId: string,
  itemId: string,
  decision: ReviewDecision,
): Promise<AuditItem> {
  const { data } = await api.post<AuditItem>(
    `/api/v1/audits/${auditId}/items/${itemId}/review`,
    { decision },
  );
  return data;
}
