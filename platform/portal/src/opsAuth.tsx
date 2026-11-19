// Operator session state. Its own context, separate from the portal's AuthProvider: one never clears
// the other. Only mounted under /ops, so the public site and the portal never call /v1/ops.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { copy } from "./copy";
import { PublicLayout } from "./Layout";
import { opsApi, setOpsUnauthorizedHandler } from "./opsApi";
import type { OpsOperator } from "./opsApi";
import { NotFound } from "./pages/NotFound";
import { Loading } from "./ui";

type Status = "loading" | "disabled" | "anon" | "authed";
type OpsState = {
  status: Status;
  operator: OpsOperator | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};
const OpsCtx = createContext<OpsState | null>(null);

export function useOps(): OpsState {
  const v = useContext(OpsCtx);
  if (!v) throw new Error("OpsProvider missing");
  return v;
}

function OpsProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [operator, setOperator] = useState<OpsOperator | null>(null);

  useEffect(() => {
    setOpsUnauthorizedHandler(() => {
      setOperator(null);
      setStatus("anon"); // a 401 on any console call clears only the operator state
    });
    opsApi
      .me()
      .then((r) => {
        if (r === "disabled" || r === "anon") setStatus(r);
        else {
          setOperator(r);
          setStatus("authed");
        }
      })
      .catch(() => setStatus("anon"));
  }, []);

  // Tab title and robots meta only while the console really exists (anon/authed). Never while loading or
  // when the server has it off (disabled): then the page must look like any unknown route, tab included.
  const initialTitleRef = useRef(document.title);
  const live = status === "anon" || status === "authed";
  useEffect(() => {
    if (!live) return;
    const savedTitle = initialTitleRef.current;
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    if (!document.title.includes(copy.opsBar.subtitle)) {
      document.title = `${copy.brand.full} · ${copy.opsBar.subtitle}`;
    }
    return () => {
      meta.remove();
      document.title = savedTitle;
    };
  }, [live]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await opsApi.login(email, password);
    if (r === "disabled") {
      setStatus("disabled");
      return;
    }
    setOperator(r);
    setStatus("authed");
  }, []);
  // Only clears local state once the server confirmed the session ended; otherwise it throws.
  const logout = useCallback(async () => {
    await opsApi.logout();
    setOperator(null);
    setStatus("anon");
  }, []);

  const value = useMemo(() => ({ status, operator, login, logout }), [status, operator, login, logout]);
  return <OpsCtx.Provider value={value}>{children}</OpsCtx.Provider>;
}

/** Root of /ops/*. With the console switched off on the server it looks like any unknown page. */
export function OpsRoot() {
  return (
    <OpsProvider>
      <OpsGate />
    </OpsProvider>
  );
}

function OpsGate() {
  const { status } = useOps();
  if (status === "loading") return <Loading />;
  if (status === "disabled")
    return (
      <PublicLayout>
        <NotFound />
      </PublicLayout>
    );
  return <Outlet />;
}

/** Console pages need an operator session; otherwise go to /ops/login. */
export function RequireOps({ children }: { children: ReactNode }) {
  const { status } = useOps();
  const loc = useLocation();
  if (status !== "authed") return <Navigate to="/ops/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}
