import { useState } from "react";
import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { copy } from "../../copy";
import { useOps } from "../../opsAuth";
import { ErrorBox, Logo, cx } from "../../ui";

/** The console looks like another product on purpose: a fixed dark bar, no area sidebar, no public links. */
export function OpsBar({ children }: { children?: ReactNode }) {
  return (
    <header className="sticky top-0 z-40 border-b border-ink bg-ink text-white">
      <div className="container-page flex min-h-16 flex-wrap items-center gap-x-6 gap-y-3 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Logo to={null} inverted size="text-xl" />
          <span className="inline-flex items-center gap-2 border border-white/35 bg-white/5 px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white">
            <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
            {copy.opsBar.badge}
          </span>
        </div>
        {children}
      </div>
    </header>
  );
}

export function OpsLayout() {
  const { operator, logout } = useOps();
  const [error, setError] = useState(false);
  const link = ({ isActive }: { isActive: boolean }) =>
    cx(
      "inline-flex items-center gap-2 border-b-2 py-1 font-mono text-xs font-semibold uppercase tracking-[0.08em] no-underline transition-colors",
      isActive
        ? "border-accent text-white"
        : "border-transparent text-white/80 hover:border-white/40 hover:text-white",
    );

  return (
    <div className="min-h-screen bg-paper text-ink">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        {copy.common.skipToContent}
      </a>
      <OpsBar>
        <nav aria-label={copy.opsBar.navAria} className="flex flex-wrap items-center gap-6">
          <NavLink to="/ops/organizations" className={link}>
            {copy.opsBar.organizations}
          </NavLink>
          <NavLink to="/ops/activity" className={link}>
            {copy.opsBar.activity}
          </NavLink>
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <span className="break-all font-mono text-xs text-[#D4D4D4]">{operator?.email}</span>
          <button
            type="button"
            className="btn btn-sm btn-ghost-dark"
            onClick={async () => {
              setError(false);
              try {
                await logout();
              } catch {
                setError(true); // never pretend the session ended
              }
            }}
          >
            {copy.opsBar.logout}
          </button>
        </div>
      </OpsBar>
      <div aria-hidden="true" className="ruler-x bg-surface" />
      {error && (
        <div className="container-page pt-6">
          <ErrorBox>{copy.opsBar.logoutError}</ErrorBox>
        </div>
      )}
      <main id="content" className="mx-auto max-w-[1200px] px-5 py-10 sm:px-6 lg:py-12">
        <Outlet />
      </main>
    </div>
  );
}
