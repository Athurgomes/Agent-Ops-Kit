import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, setUnauthorizedHandler } from "./api";
import type { AgentItem, AreaNode, Me } from "./api";
import { fmtApiError } from "./format";
import { Loading } from "./ui";

type AuthState = {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loggedOut: boolean; // true after an explicit log out (so we go home, not to the login page)
  logout: () => Promise<void>;
};
const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [loggedOut, setLoggedOut] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null)); // 401 em qualquer chamada limpa o estado
    if (window.location.pathname.startsWith("/ops")) {
      setLoading(false); // o console do operador tem sessão própria: o portal não consulta /v1/auth/me lá
      return;
    }
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setMe(await api.login(email, password));
    setLoggedOut(false);
  }, []);
  // Only clears the local state after the server confirmed the session ended; otherwise it throws.
  const logout = useCallback(async () => {
    await api.logout();
    setLoggedOut(true);
    setMe(null);
  }, []);

  const value = useMemo(
    () => ({ me, loading, loggedOut, login, logout }),
    [me, loading, loggedOut, login, logout],
  );
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("AuthProvider missing");
  return v;
}

/** Rotas protegidas: sem sessão volta ao login (e para onde a pessoa queria ir depois). */
export function RequireAuth({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { me, loading, loggedOut } = useAuth();
  const loc = useLocation();
  if (loading) return <Loading />;
  if (!me && loggedOut) return <Navigate to="/" replace />;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  if (admin && !me.is_org_admin) return <Navigate to="/app" replace />;
  return <>{children}</>;
}

// ---- áreas e agentes visíveis (carregados uma vez por sessão, para breadcrumbs e filtros) ----

export type Flat = { id: number; name: string; depth: number; parent_id: number | null };
type CatalogState = {
  tree: AreaNode[];
  areas: Flat[];
  agents: AgentItem[];
  ready: boolean;
  error: string | null;
  reload: () => void; // refetch after an admin changes areas or agents
};
const CatalogCtx = createContext<CatalogState>({
  tree: [],
  areas: [],
  agents: [],
  ready: false,
  error: null,
  reload: () => {},
});

function flatten(nodes: AreaNode[], depth = 0, out: Flat[] = []): Flat[] {
  for (const n of nodes) {
    out.push({ id: n.id, name: n.name, depth, parent_id: n.parent_id });
    flatten(n.children, depth + 1, out);
  }
  return out;
}

export function CatalogProvider({ children }: { children: ReactNode }) {
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const [state, setState] = useState<CatalogState>({
    tree: [],
    areas: [],
    agents: [],
    ready: false,
    error: null,
    reload,
  });
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const tree = await api.areas();
        const areas = flatten(tree);
        const lists = await Promise.all(areas.map((a) => api.agents(a.id)));
        if (alive) setState({ tree, areas, agents: lists.flat(), ready: true, error: null, reload });
      } catch (e) {
        if (alive) setState((s) => ({ ...s, ready: true, error: fmtApiError(e) }));
      }
    })();
    return () => {
      alive = false;
    };
  }, [tick, reload]);
  return <CatalogCtx.Provider value={state}>{children}</CatalogCtx.Provider>;
}

export const useCatalog = () => useContext(CatalogCtx);

/** Caminho da área até a raiz (para breadcrumbs). */
export function areaPath(areas: Flat[], id: number): Flat[] {
  const byId = new Map(areas.map((a) => [a.id, a]));
  const out: Flat[] = [];
  for (let cur = byId.get(id); cur; cur = cur.parent_id != null ? byId.get(cur.parent_id) : undefined)
    out.unshift(cur);
  return out;
}
