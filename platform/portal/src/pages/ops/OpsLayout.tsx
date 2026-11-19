import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { copy } from "../../copy";
import { useOps } from "../../opsAuth";
import { Button, Logo, cx } from "../../ui";

/** The console looks like another product on purpose: a fixed dark bar, no area sidebar, no public links. */
export function OpsBar({ children }: { children?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-40 bg-ink text-white">
      <div className="container-page flex min-h-14 flex-wrap items-center gap-x-6 gap-y-2 py-2">
        <div className="flex items-center gap-3">
          <Logo to={null} inverted size="text-lg" />
          <span aria-hidden="true" className="text-white/40">
            ·
          </span>
          <span className="text-sm font-semibold text-white/80">{copy.opsBar.subtitle}</span>
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
    cx("font-semibold no-underline hover:underline", isActive ? "underline decoration-2 underline-offset-8" : "text-white/80");

  return (
    <div className="min-h-screen">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        {copy.common.skipToContent}
      </a>
      <OpsBar>
        <nav aria-label="Operator" className="flex flex-wrap items-center gap-6">
          <NavLink to="/ops/organizations" className={link}>
            Organizations
          </NavLink>
          <NavLink to="/ops/activity" className={link}>
            Activity
          </NavLink>
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <span className="break-all text-sm text-white/80">{operator?.email}</span>
          <Button
            size="sm"
            onClick={async () => {
              setError(false);
              try {
                await logout();
              } catch {
                setError(true); // never pretend the session ended
              }
            }}
          >
            Log out
          </Button>
        </div>
      </OpsBar>
      {error && (
        <p role="alert" className="container-page py-3 text-sm font-semibold">
          Could not end the session on the server; try again.
        </p>
      )}
      <main id="content" className="mx-auto max-w-[1200px] px-6 py-12">
        <Outlet />
      </main>
    </div>
  );
}
