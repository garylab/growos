import { useAppStore } from "@/store/app";

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const token = useAppStore.getState().token;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers["X-Auth-Token"] = token;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload, ...init });
  if (res.status === 401) {
    useAppStore.getState().setToken(null);
    throw new ApiError(401, "Unauthorized");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data);
    throw new ApiError(res.status, detail || res.statusText, data?.code);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T = void>(path: string) => request<T>("DELETE", path),
};

// ---- Types (subset of the API)
export interface Project { id: string; name: string; slug: string; brand_name: string; brand_aliases: string[]; description: string | null; default_language: string; default_country: string; settings: Record<string, unknown>; created_at: string }
export interface Domain { id: string; project_id: string; hostname: string; base_url: string; role: "primary" | "competitor"; competitor_id: string | null; gsc_property: string | null; ga4_property: string | null; bing_site_url: string | null; is_active: boolean; watch_urls: string[] }
export interface Competitor { id: string; name: string; aliases: string[]; notes: string | null }
export interface Keyword { id: string; text: string; language: string; country: string; importance: number; tags: string[]; is_target: boolean; source: string }
export interface Job { id: string; project_id: string | null; task_type: string; params: Record<string, unknown>; status: "queued" | "running" | "succeeded" | "failed" | "cancelled"; progress: number; progress_message: string | null; attempts: number; max_attempts: number; started_at: string | null; finished_at: string | null; error: string | null; result: Record<string, unknown> | null; created_at: string; triggered_by: string }
export interface JobLog { id: number; ts: string; level: string; message: string }
export interface Connection { id: string; project_id: string | null; provider_key: string; category: string; display_name: string; config: Record<string, unknown>; status: string; last_checked_at: string | null; last_error: string | null; is_enabled: boolean; credential_preview: Record<string, string> }
export interface ProviderMeta { key: string; category: string; display_name: string; description: string; docs_url: string; requires_connection: boolean; features: string[]; vendor: string; vendor_url: string; env_credentials: Record<string, string>; credential_fields: { key: string; label: string; secret: boolean; required: boolean; help: string }[]; config_fields: { key: string; label: string; type: string; default: unknown; options: string[]; help: string; show_if?: Record<string, unknown> }[] }
export interface Prompt { id: string; text: string; intent: string; topic: string | null; language: string; country: string; is_active: boolean; samples_per_run: number; tags: string[] }
export interface Opportunity { id: string; kind: string; module: string; title: string; description: string; why: string; evidence: Evidence[]; impact_score: number; confidence: number; effort: number; priority_score: number; score_breakdown: Record<string, unknown>; recommended_action: string; status: string; origin: string; target_urls: string[]; target_keywords: string[]; first_seen_at: string; last_seen_at: string; times_seen: number }
export interface Evidence { type: string; table: string; record_ids: string[]; summary: string; data: Record<string, unknown>; measurement_type: string }
export interface User { id: string; email: string; name: string | null; role: string; is_active: boolean; last_login_at: string | null; must_change_password: boolean; created_at: string }
export interface Member { user_id: string; email: string; name: string | null; role: string; user_role: string; effective_role: string; is_active: boolean; added_at: string }
export interface ContentDraft { id: string; plan_item_id: string | null; kind: string; channel: string; topic: string; title: string | null; body: string; assets: Record<string, any>; evidence: { summary: string }[]; provider_key: string | null; model: string | null; status: string; published_url: string | null; created_at: string }
export interface Writer { provider_key: string; display_name: string; status: string; model: string | null; local: boolean }
export interface Action { id: string; plan_item_id: string | null; title: string; description: string | null; status: string; owner: string | null; target_urls: string[]; target_keywords: string[]; target_prompt_ids: string[]; started_at: string | null; completed_at: string | null; notes: string | null; created_at: string; updated_at: string }
export interface Outcome { id: string; action_id: string; metric_key: string; source: string; measurement_type: string; baseline_period: { start: string; end: string }; comparison_period: { start: string; end: string }; baseline_value: number | null; current_value: number | null; delta: number | null; delta_pct: number | null; measured_at: string }
