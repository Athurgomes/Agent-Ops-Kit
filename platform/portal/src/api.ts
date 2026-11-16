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

async function request(path: string, init: RequestInit = {}, handle401 = true): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "Não foi possível falar com o servidor. Tente de novo em instantes.");
  }
  if (res.status === 401 && handle401) onUnauthorized();
  return res;
}

function failure(res: Response): ApiError {
  let msg = "Algo deu errado. Tente de novo.";
  if (res.status === 404) msg = "Não encontrado ou sem permissão de acesso.";
  else if (res.status === 429) msg = "Muitas tentativas. Aguarde alguns minutos e tente de novo.";
  else if (res.status === 401) msg = "Sessão expirada. Entre de novo.";
  else if (res.status >= 500) msg = "Erro no servidor. Tente de novo em instantes.";
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
    if (res.status === 401) throw new ApiError(401, "E-mail ou senha inválidos.");
    if (!res.ok) throw failure(res);
    return (await res.json()) as Me;
  },
  async logout(): Promise<void> {
    await request("/v1/auth/logout", { method: "POST" }, false).catch(() => {});
  },
  async me(): Promise<Me | null> {
    const res = await request("/v1/auth/me", {}, false);
    if (res.status === 401) return null;
    if (!res.ok) throw failure(res);
    return (await res.json()) as Me;
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
