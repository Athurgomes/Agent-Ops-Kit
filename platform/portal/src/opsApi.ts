// Operator console API (/v1/ops). Separate from the organization portal: its own fetch wrapper and its own
// 401 handler, so an operator session and a portal session never clear each other. Metadata only:
// nothing here can read report contents, and secrets (generated passwords) are only returned to the caller.
import { ApiError } from "./api";

export type OpsOperator = { id: number; email: string };
export type OpsOrg = {
  id: number;
  slug: string;
  name: string;
  active: boolean;
  created_at: string;
  areas_count: number;
  agents_count: number;
  users_count: number;
  tokens_active_count: number;
  reports_count: number;
  last_report_at: string | null;
};
export type OpsAreaNode = { id: number; name: string; parent_id: number | null; children: OpsAreaNode[] };
export type OpsAgent = {
  id: number;
  slug: string;
  name: string;
  area_name: string;
  active: boolean;
  tokens_active_count: number;
  last_report_at: string | null;
  latest_semaforo: string | null;
};
export type OpsUser = {
  id: number;
  email: string;
  active: boolean;
  access: { role: string; area_name: string | null }[];
};
export type OpsReport = {
  id: number;
  agent_slug: string;
  seq: number;
  status_semaforo: string;
  generated_at: string | null;
  published_at: string;
  n_cases: number | null;
  model: string | null;
};
export type OpsDetail = {
  id: number;
  slug: string;
  name: string;
  active: boolean;
  created_at: string;
  areas: OpsAreaNode[];
  agents: OpsAgent[];
  users: OpsUser[];
  reports: OpsReport[];
};
export type OpsOrgEvent = {
  id: number;
  at: string;
  actor_user_id: number | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: number | null;
};
export type OpsEvent = {
  id: number;
  at: string;
  operator_id: number;
  operator_email: string;
  action: string;
  target_org_id: number | null;
  target_org_slug: string | null;
  target_type: string | null;
  target_id: number | null;
};
export type CreatedAdmin = { user_id: number; email: string; password: string };

let onOpsUnauthorized: () => void = () => {};
export function setOpsUnauthorizedHandler(fn: () => void) {
  onOpsUnauthorized = fn;
}

async function opsFetch(path: string, init: RequestInit = {}, handle401 = true): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "Could not reach the server. Please try again in a moment.");
  }
  if (res.status === 401 && handle401) onOpsUnauthorized();
  return res;
}

async function friendly(res: Response): Promise<ApiError> {
  let detail = "";
  try {
    const j = await res.json();
    if (typeof j?.detail === "string") detail = j.detail.toLowerCase();
  } catch {
    /* no body */
  }
  if (res.status === 409 && detail.includes("slug")) return new ApiError(409, "That slug is already used by another organization.");
  if (res.status === 409) return new ApiError(409, "That email is already registered.");
  if (res.status === 422) return new ApiError(422, "A field is not valid. Check the values and try again.");
  if (res.status === 404) return new ApiError(404, "Not found.");
  if (res.status === 429) return new ApiError(429, "Too many attempts. Wait a few minutes and try again.");
  if (res.status === 401) return new ApiError(401, "Your session expired. Please log in again.");
  if (res.status >= 500) return new ApiError(res.status, "Server error. Please try again in a moment.");
  return new ApiError(res.status, "Something went wrong. Please try again.");
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await opsFetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await friendly(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const qs = (p: Record<string, number>) => `?${new URLSearchParams(Object.entries(p).map(([k, v]) => [k, String(v)]))}`;

export const opsApi = {
  /** "disabled" = the server answered 404 (AOK_OPS_ENABLED is off): the console must look nonexistent. */
  async me(): Promise<OpsOperator | "anon" | "disabled"> {
    const res = await opsFetch("/v1/ops/auth/me", {}, false);
    if (res.status === 404) return "disabled";
    if (res.status === 401) return "anon";
    if (!res.ok) throw await friendly(res);
    return (await res.json()) as OpsOperator;
  },
  async login(email: string, password: string): Promise<OpsOperator | "disabled"> {
    const res = await opsFetch(
      "/v1/ops/auth/login",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) },
      false,
    );
    if (res.status === 404) return "disabled";
    if (res.status === 401) throw new ApiError(401, "Invalid email or password.");
    if (!res.ok) throw await friendly(res);
    return (await res.json()) as OpsOperator;
  },
  /** Throws if the server could not end the session (an already-expired 401 counts as ended). */
  async logout(): Promise<void> {
    const res = await opsFetch("/v1/ops/auth/logout", { method: "POST" }, false);
    if (!res.ok && res.status !== 401) throw await friendly(res);
  },
  orgs: () => send<OpsOrg[]>("/v1/ops/organizations", "GET"),
  createOrg: (slug: string, name: string) => send<{ id: number }>("/v1/ops/organizations", "POST", { slug, name }),
  patchOrg: (id: number, body: { name?: string; active?: boolean }) => send<{ id: number }>(`/v1/ops/organizations/${id}`, "PATCH", body),
  org: (id: number) => send<OpsDetail>(`/v1/ops/organizations/${id}`, "GET"),
  createAdmin: (id: number, email: string) => send<CreatedAdmin>(`/v1/ops/organizations/${id}/admins`, "POST", { email }),
  resetAdmin: (id: number, userId: number) => send<CreatedAdmin>(`/v1/ops/organizations/${id}/admins/${userId}/reset-password`, "POST"),
  orgEvents: (id: number, limit: number, offset: number) =>
    send<OpsOrgEvent[]>(`/v1/ops/organizations/${id}/events${qs({ limit, offset })}`, "GET"),
  events: (limit: number, offset: number) => send<OpsEvent[]>(`/v1/ops/events${qs({ limit, offset })}`, "GET"),
};
