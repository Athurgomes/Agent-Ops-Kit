// Administration API (org_admin only). Server messages are Portuguese, so they are mapped here to
// clear English; secrets (new tokens, passwords) are only ever returned to the caller, never stored.
import { ApiError, failure, request } from "./api";

export type AdminArea = { id: number; name: string; parent_id: number | null; agent_count: number };
export type AdminAgent = {
  id: number;
  slug: string;
  name: string;
  area_id: number;
  area_name: string;
  active: boolean;
  tokens_active_count: number;
  last_report_at: string | null;
};
export type TokenMeta = {
  token_id: number;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
};
export type IssuedToken = { token_id: number; token: string; created_at: string };
export type AccessBrief = { id: number; area_id: number | null; area_name: string | null; role: string };
export type AdminUser = {
  id: number;
  email: string;
  active: boolean;
  created_at: string;
  memberships: AccessBrief[];
};
export type AdminEvent = {
  id: number;
  at: string;
  actor_user_id: number | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: number | null;
};
export type Role = "org_admin" | "area_viewer";

async function adminFailure(res: Response): Promise<ApiError> {
  let detail = "";
  try {
    const j = await res.json();
    if (typeof j?.detail === "string") detail = j.detail.toLowerCase();
  } catch {
    /* no body */
  }
  if (detail.includes("ciclo"))
    return new ApiError(422, "That move would create a loop: an area cannot sit under itself or one of its own sub-areas.");
  if (res.status === 409 && detail.includes("própria conta"))
    return new ApiError(409, "You cannot deactivate your own account.");
  if (res.status === 409 && detail.includes("próprio acesso"))
    return new ApiError(409, "You cannot remove your own organization admin access.");
  if (res.status === 409 && detail.includes("última"))
    return new ApiError(409, "This is the last active organization admin. Make someone else an admin first.");
  if (res.status === 409 && detail.includes("slug")) return new ApiError(409, "That slug is already used by another agent.");
  if (res.status === 409 && detail.includes("mail")) return new ApiError(409, "That email is already registered.");
  if (res.status === 409) return new ApiError(409, "That user already has this access.");
  if (res.status === 422 && detail.includes("area_id")) return new ApiError(422, "Pick an area for this role.");
  if (res.status === 422) return new ApiError(422, "A field is not valid. Check the values and try again.");
  if (res.status === 403) return new ApiError(403, "You do not have permission to do this.");
  if (res.status === 404) return new ApiError(404, "Not found. It may have been removed, or it belongs to another organization.");
  return failure(res);
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await request(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await adminFailure(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const qs = (p: Record<string, number>) => `?${new URLSearchParams(Object.entries(p).map(([k, v]) => [k, String(v)]))}`;

export const adminApi = {
  areas: () => send<AdminArea[]>("/v1/admin/areas", "GET"),
  createArea: (name: string, parent_id: number | null) => send<AdminArea>("/v1/admin/areas", "POST", { name, parent_id }),
  patchArea: (id: number, body: { name?: string; parent_id?: number | null }) =>
    send<AdminArea>(`/v1/admin/areas/${id}`, "PATCH", body),

  agents: () => send<AdminAgent[]>("/v1/admin/agents", "GET"),
  createAgent: (body: { area_id: number; slug: string; name: string }) =>
    send<{ id: number }>("/v1/admin/agents", "POST", body),
  patchAgent: (id: number, body: { name?: string; area_id?: number; active?: boolean }) =>
    send<{ id: number }>(`/v1/admin/agents/${id}`, "PATCH", body),
  tokens: (agentId: number) => send<TokenMeta[]>(`/v1/admin/agents/${agentId}/tokens`, "GET"),
  issueToken: (agentId: number) => send<IssuedToken>(`/v1/admin/agents/${agentId}/tokens`, "POST"),
  revokeToken: (agentId: number, tokenId: number) =>
    send<unknown>(`/v1/admin/agents/${agentId}/tokens/${tokenId}`, "DELETE"),

  users: () => send<AdminUser[]>("/v1/admin/users", "GET"),
  createUser: (email: string, password: string) => send<{ id: number }>("/v1/admin/users", "POST", { email, password }),
  patchUser: (id: number, body: { active?: boolean; password?: string }) =>
    send<{ id: number }>(`/v1/admin/users/${id}`, "PATCH", body),
  grant: (user_id: number, role: Role, area_id: number | null) =>
    send<{ id: number }>("/v1/admin/memberships", "POST", area_id === null ? { user_id, role } : { user_id, role, area_id }),
  revokeAccess: (membershipId: number) => send<void>(`/v1/admin/memberships/${membershipId}`, "DELETE"),

  events: (limit: number, offset: number) => send<AdminEvent[]>(`/v1/admin/events${qs({ limit, offset })}`, "GET"),
};
