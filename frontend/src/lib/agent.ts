// The in-app agent (ADR 0017) — mirrors backend/app/schemas.py's Agent*
// models. Money stays a string here too, like everywhere in lib/api.ts.

import { api } from "./api";

export interface AgentStatus {
  configured: boolean;
  model: string;
}

export interface PreviewTxn {
  id: number | null;
  external_id: string;
  date: string;
  type: string;
  account_id: number;
  instrument_id: number | null;
  quantity: string | null;
  price: string | null;
  currency: string;
  fees: string;
  tax: string;
  amount_eur: string;
  provisional: boolean;
  note: string | null;
}

export interface PreviewRow {
  action: "create" | "update" | "delete";
  before?: PreviewTxn;
  after?: PreviewTxn;
  reason?: string;
  account_name: string | null;
  instrument_name: string | null;
}

export interface AgentProposal {
  id: number;
  summary: string;
  status: "pending" | "applied" | "rejected";
  preview: PreviewRow[];
  error: { code: string; params: Record<string, unknown> } | null;
  import_batch_id: number | null;
}

export interface TranscriptItem {
  role: "user" | "assistant";
  text: string;
  image_count: number;
  proposal: AgentProposal | null;
}

export interface AgentConversation {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string | null;
  input_tokens: number;
  output_tokens: number;
  items: TranscriptItem[];
}

export interface OutgoingImage {
  media_type: string;
  data: string;
  /** Object URL for the thumbnail only — never sent. */
  preview: string;
}

export const agentApi = {
  status: () => api.get<AgentStatus>("/api/agent/status"),
  list: () => api.get<AgentConversation[]>("/api/agent/conversations"),
  get: (id: number) => api.get<AgentConversation>(`/api/agent/conversations/${id}`),
  create: () => api.post<AgentConversation>("/api/agent/conversations"),
  remove: (id: number) => api.delete<void>(`/api/agent/conversations/${id}`),
  send: (id: number, text: string, images: OutgoingImage[]) =>
    api.post<AgentConversation>(`/api/agent/conversations/${id}/messages`, {
      text,
      images: images.map(({ media_type, data }) => ({ media_type, data })),
    }),
  apply: (proposalId: number) =>
    api.post<AgentProposal>(`/api/agent/proposals/${proposalId}/apply`),
  reject: (proposalId: number) =>
    api.post<AgentProposal>(`/api/agent/proposals/${proposalId}/reject`),
};

// Long side cap for screenshots. Large enough that statement text stays
// legible, small enough that a phone photo doesn't become a 10 MB upload.
const MAX_SIDE = 2000;

/** Downscales a pasted/dropped image and returns it base64-encoded. */
export async function prepareImage(file: File): Promise<OutgoingImage> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();

  // PNG keeps screenshot text crisp; fall back to JPEG when PNG would be big
  // (photos), staying well under the API's 5 MB per image.
  let type = "image/png";
  let blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, type));
  if (!blob || blob.size > 3_500_000) {
    type = "image/jpeg";
    blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, type, 0.9));
  }
  if (!blob) throw new Error("image_encoding_failed");

  const data = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob!);
  });
  return { media_type: type, data, preview: URL.createObjectURL(blob) };
}
