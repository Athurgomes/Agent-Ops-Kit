import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { BRAND } from "./brand";
import { useAuth } from "./auth";
import { Button, LinkButton } from "./ui";

const navCls = ({ isActive }: { isActive: boolean }) =>
  `brutal px-3 py-2 font-black uppercase no-underline ${isActive ? "bg-yellow" : "bg-paper"}`;

export function Layout({ children }: { children: ReactNode }) {
  const { me, logout } = useAuth();
  const nav = useNavigate();

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-yellow focus:p-3 brutal"
      >
        Ir para o conteúdo
      </a>
      <header className="brutal border-x-0 border-t-0 bg-pink">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <Link
            to={me ? "/app" : "/"}
            className="title brutal bg-yellow px-3 py-1 text-2xl no-underline"
          >
            {BRAND}
          </Link>
          <nav aria-label="Principal" className="flex flex-1 flex-wrap items-center gap-2">
            {me ? (
              <>
                <NavLink to="/app" end className={navCls}>
                  Áreas
                </NavLink>
                <NavLink to="/app/downloads" className={navCls}>
                  Meus downloads
                </NavLink>
                {me.is_org_admin && (
                  <NavLink to="/app/admin/downloads" className={navCls}>
                    Todos os downloads
                  </NavLink>
                )}
              </>
            ) : (
              <NavLink to="/" end className={navCls}>
                Início
              </NavLink>
            )}
          </nav>
          {me ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className="break-all text-sm font-bold">{me.email}</span>
              <Button
                tone="white"
                className="px-3 py-2 text-sm"
                onClick={async () => {
                  await logout();
                  nav("/");
                }}
              >
                Sair
              </Button>
            </div>
          ) : (
            <LinkButton to="/entrar" className="px-4 py-2">
              Entrar
            </LinkButton>
          )}
        </div>
      </header>
      <main id="conteudo" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        {children}
      </main>
      <footer className="brutal border-x-0 border-b-0 bg-muted">
        <p className="mx-auto max-w-6xl px-4 py-4 text-sm font-bold">
          {BRAND} é um nome provisório e fictício. Os relatórios são autodeclarados e não
          garantem segurança.
        </p>
      </footer>
    </div>
  );
}
