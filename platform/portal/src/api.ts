// Cliente da API. A sessão é um cookie HttpOnly definido pelo servidor: aqui só enviamos o cookie.

export type Me = {
  id: number;
  email: string;
  is_org_admin: boolean;
  memberships: { area_id: number | null; role: string }[];
};
export type AreaNode = { id: number; name: string; parent_id: number | null; children: AreaNode[] };
export type AgentItem = { id: number; area_id: number; slug: string; name: string; active: boolean };
export type Semaforo = "green" | "yellow" | "red";
export type ReportItem = {
  id: number;
  seq: number;
  published_at: string;
  generated_at: string | null;
  status_semaforo: string;
};
export type Rate = { n?: number; successes?: number; asr?: number; ci95_low?: number; ci95_high?: number };
export type FpRate = { n?: number; blocked?: number; rate?: number; ci95_low?: number; ci95_high?: number };
export type Summary = {
  generated_at?: string | null;
  semaphore?: { color?: string; triggered?: string[]; rules_version?: string };
  agent?: { name?: string; model?: string; prompt_version?: string } | null;
  eval?: {
    baseline?: string;
    candidate?: string;
    n_cases?: number;
    mean_baseline?: number;
    mean_candidate?: number;
    mean_diff?: number;
    ci95_low?: number;
    ci95_high?: number;
    p_value?: number;
    regression?: boolean;
  };
  redteam?: {
    asr_baseline?: Rate | null;
    asr_guardrails?: Rate | null;
    false_positives?: { dataset?: FpRate; benign?: FpRate } | null;
  };
  audit?: { ok?: boolean; anchor?: string | null } | null;
};
export type ReportDetail = ReportItem & {
  agent_id: number;
  agent_slug: string;
  agent_name: string;
  area_id: number;
  sha256: string;
  audit_verify_ok: boolean | null;
  audit_anchor: string | null;
  model: string | null;
  seed: number | null;
  n_cases: number | null;
  summary: Summary;
  limitations: string[];
};
export type DownloadItem = {
  id: number;
  report_id: number;
  seq: number;
  agent_id: number;
  agent_slug: string;
  agent_name: string;
  area_id: number;
  area_name: string;
  format: string;
  downloaded_at: string;
  generated_at: string | null;
  user_email: string | null;
};
export type Format = "md" | "html" | "json";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: () => void = () => {};
/** O AuthProvider registra aqui o que fazer num 401 (limpar o estado e voltar ao login). */
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export async function request(path: string, init: RequestInit = {}, handle401 = true): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "Could not reach the server. Please try again in a moment.");
  }
  if (res.status === 401 && handle401) onUnauthorized();
  return res;
}

export function failure(res: Response): ApiError {
  let msg = "Something went wrong. Please try again.";
  if (res.status === 404) msg = "Not found, or you do not have access.";
  else if (res.status === 429) msg = "Too many attempts. Wait a few minutes and try again.";
  else if (res.status === 401) msg = "Your session expired. Please log in again.";
  else if (res.status >= 500) msg = "Server error. Please try again in a moment.";
  return new ApiError(res.status, msg);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await request(path);
  if (!res.ok) throw failure(res);
  return (await res.json()) as T;
}

const qs = (p: Record<string, string | number | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
};

export const api = {
  async login(email: string, password: string): Promise<Me> {
    const res = await request(
      "/v1/auth/login",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      },
      false,
    );
    if (res.status === 401) throw new ApiError(401, "Invalid email or password.");
    if (!res.ok) throw failure(res);
    return (await res.json()) as Me;
  },
  /** Throws if the server could not end the session (an already-expired 401 counts as ended). */
  async logout(): Promise<void> {
    const res = await request("/v1/auth/logout", { method: "POST" }, false);
    if (!res.ok && res.status !== 401) throw failure(res);
  },
  async me(): Promise<Me | null> {
    const res = await request("/v1/auth/me", {}, false);
    if (res.status === 401) return null;
    if (!res.ok) throw failure(res);
    return (await res.json()) as Me;
  },
  /** Whether password recovery by email is switched on in this server (never throws). */
  async capabilities(): Promise<{ password_reset: boolean }> {
    try {
      const res = await request("/v1/auth/capabilities", {}, false);
      if (!res.ok) return { password_reset: false };
      return { password_reset: (await res.json()).password_reset === true };
    } catch {
      return { password_reset: false };
    }
  },
  /** Returns the HTTP status (0 = network error). The caller must show the same message for any of them. */
  async forgotPassword(email: string): Promise<number> {
    try {
      const res = await request(
        "/v1/auth/password/forgot",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) },
        false,
      );
      return res.status;
    } catch {
      return 0;
    }
  },
  /** Returns the HTTP status (204 = done, 400 = invalid or expired link, 422 = password too short, 429 = too many). */
  async resetPassword(token: string, newPassword: string): Promise<number> {
    try {
      const res = await request(
        "/v1/auth/password/reset",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, new_password: newPassword }) },
        false,
      );
      return res.status;
    } catch {
      return 0;
    }
  },
  areas: () => getJson<AreaNode[]>("/v1/areas"),
  agents: (areaId: number) => getJson<AgentItem[]>(`/v1/areas/${areaId}/agents`),
  reports: (agentId: number) => getJson<ReportItem[]>(`/v1/agents/${agentId}/reports`),
  report: (id: number) => getJson<ReportDetail>(`/v1/reports/${id}`),
  downloads: (
    admin: boolean,
    f: { area_id?: number; agent_id?: number; limit?: number; offset?: number },
  ) => getJson<DownloadItem[]>(`/v1/${admin ? "admin" : "me"}/downloads${qs(f)}`),
  /** Baixa o arquivo (o servidor registra o download) e o entrega ao navegador como arquivo. */
  async download(report: { id: number; agent_slug: string; seq: number }, format: Format) {
    const res = await request(`/v1/reports/${report.id}/download?format=${format}`);
    if (!res.ok) throw failure(res);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report.agent_slug}-${report.seq}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
