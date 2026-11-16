import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, setUnauthorizedHandler } from "./api";
import type { AgentItem, AreaNode, Me } from "./api";
import { Loading } from "./ui";

type AuthState = {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};
const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null)); // 401 em qualquer chamada limpa o estado
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setMe(await api.login(email, password));
  }, []);
  const logout = useCallback(async () => {
    await api.logout();
    setMe(null);
  }, []);

  const value = useMemo(() => ({ me, loading, login, logout }), [me, loading, login, logout]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("AuthProvider ausente");
  return v;
}

/** Rotas protegidas: sem sessão volta ao login (e para onde a pessoa queria ir depois). */
export function RequireAuth({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { me, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/entrar" replace state={{ from: loc.pathname + loc.search }} />;
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
};
const CatalogCtx = createContext<CatalogState>({
  tree: [],
  areas: [],
  agents: [],
  ready: false,
  error: null,
});

function flatten(nodes: AreaNode[], depth = 0, out: Flat[] = []): Flat[] {
  for (const n of nodes) {
    out.push({ id: n.id, name: n.name, depth, parent_id: n.parent_id });
    flatten(n.children, depth + 1, out);
  }
  return out;
}

export function CatalogProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CatalogState>({
    tree: [],
    areas: [],
    agents: [],
    ready: false,
    error: null,
  });
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const tree = await api.areas();
        const areas = flatten(tree);
        const lists = await Promise.all(areas.map((a) => api.agents(a.id)));
        if (alive) setState({ tree, areas, agents: lists.flat(), ready: true, error: null });
      } catch (e) {
        if (alive)
          setState((s) => ({ ...s, ready: true, error: e instanceof Error ? e.message : "Erro." }));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);
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
