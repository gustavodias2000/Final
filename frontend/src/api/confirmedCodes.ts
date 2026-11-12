import api from "./client";
import type { ConfirmedCodeImportResult, ConfirmedCodeList } from "./contracts";

export async function listConfirmedCodes(query = "", limit = 50): Promise<ConfirmedCodeList> {
  const { data } = await api.get<ConfirmedCodeList>("/api/v1/confirmed-codes", { params: { q: query, limit } });
  return data;
}

export async function importConfirmedCodes(file: File): Promise<ConfirmedCodeImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post<ConfirmedCodeImportResult>("/api/v1/confirmed-codes/import", formData);
  return data;
}

export async function deleteConfirmedCode(id: string): Promise<void> {
  await api.delete(`/api/v1/confirmed-codes/${id}`);
}
