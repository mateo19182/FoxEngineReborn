const TOKEN_KEY = "fox_jwt";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

export function logout() {
  setToken(null);
  window.location.href = "/login";
}

export function onUnauthorized(status: number, sentToken: boolean) {
  if (status === 401 && sentToken) logout();
}

export async function api<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const r = await fetch(`/api${path}`, { ...init, headers, body });
  const text = await r.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!r.ok) {
    const msg =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : text || r.statusText;
    onUnauthorized(r.status, Boolean(token));
    throw new Error(msg);
  }
  return data as T;
}

export type QueryView = "rows" | "related";

export type TagFamily = {
  id: string;
  code: string;
  created_at: string;
};

export type SavedView = {
  id: string;
  name: string;
  dsl: string;
  view: QueryView;
  created_at: string;
  updated_at: string;
};

export function listSavedViews() {
  return api<SavedView[]>("/saved-views");
}

export function createSavedView(payload: { name: string; dsl: string; view: QueryView }) {
  return api<SavedView>("/saved-views", { method: "POST", json: payload });
}

export function patchSavedView(
  savedViewId: string,
  payload: { name?: string; dsl?: string; view?: QueryView },
) {
  return api<SavedView>(`/saved-views/${savedViewId}`, { method: "PATCH", json: payload });
}

export function deleteSavedView(savedViewId: string) {
  return api<{ status: string }>(`/saved-views/${savedViewId}`, { method: "DELETE" });
}

export function listTagFamilies() {
  return api<TagFamily[]>("/tags/families");
}

export function createTagFamily(payload: { code: string }) {
  return api<TagFamily>("/tags/families", { method: "POST", json: payload });
}

export function patchTagFamily(familyId: string, payload: { code: string }) {
  return api<TagFamily>(`/tags/families/${familyId}`, { method: "PATCH", json: payload });
}

export function deleteTagFamily(familyId: string) {
  return api<{ status: string }>(`/tags/families/${familyId}`, { method: "DELETE" });
}

export type BatchAdmin = {
  id: string;
  name: string | null;
  source_filename: string | null;
  accepted_rows: number;
  rejected_rows: number;
  duplicate_rows: number;
  ingest_ts: string;
  source_sha256?: string | null;
  deleted_at?: string | null;
};

export type BatchDeletePreview = {
  batch: BatchAdmin;
  tag_names: string[];
  clickhouse_rows: Record<string, number>;
  already_deleted: boolean;
  reingest_warning: string | null;
};

export function listBatches(includeDeleted = false) {
  const q = includeDeleted ? "?include_deleted=true" : "";
  return api<BatchAdmin[]>(`/batches${q}`);
}

export function batchDeletePreview(batchId: string) {
  return api<BatchDeletePreview>(`/batches/${batchId}/delete-preview`);
}

export function softDeleteBatch(batchId: string) {
  return api<{ status: string }>(`/batches/${batchId}`, { method: "DELETE" });
}
