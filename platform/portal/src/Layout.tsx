import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import type { AreaNode } from "./api";
import { areaPath, CatalogProvider, RequireAuth, useAuth, useCatalog } from "./auth";
import { BRAND, REPO_URL } from "./brand";
import { Button, cx, LinkButton, Logo, SoonButton, SoonText } from "./ui";

// ---------------------------------------------------------------------------------------------
// Public layout: fixed 72px header (logo, centered nav, actions), content and full footer.

function PublicNavItems({ onNavigate }: { onNavigate?: () => void }) {
  const a = (href: string, label: string) => (
    <a key={href} href={href} className="navlink" onClick={onNavigate}>
      {label}
    </a>
  );
  return (
    <>
      {a("/#features", "Features")}
      {a("/#how-it-works", "How it works")}
      <SoonText className="font-semibold text-subtle">Pricing</SoonText>
      {a("/#faq", "FAQ")}
    </>
  );
}

export function PublicLayout() {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        Skip to content
      </a>
      <header className="rule-b sticky top-0 z-40 bg-paper">
        <div className="container-page grid h-[72px] grid-cols-[auto_1fr] items-center gap-6 lg:grid-cols-[1fr_auto_1fr]">
          <Logo />
          <nav aria-label="Main" className="hidden items-center justify-center gap-8 lg:flex">
            <PublicNavItems />
          </nav>
          <div className="flex items-center justify-end gap-3">
            {me ? (
              <LinkButton to="/app" variant="primary" size="sm">
                Open portal
              </LinkButton>
            ) : (
              <>
                <LinkButton to="/login" size="sm" className="hidden sm:inline-flex">
                  Log In
                </LinkButton>
                <SoonButton className="hidden sm:inline-flex">Sign Up</SoonButton>
              </>
            )}
            <Button size="sm" className="lg:hidden" aria-expanded={open} aria-controls="public-menu" onClick={() => setOpen((v) => !v)}>
              Menu
            </Button>
          </div>
        </div>
        {open && (
          <nav id="public-menu" aria-label="Menu" className="rule-t bg-paper lg:hidden">
            <div className="container-page flex flex-col items-start gap-4 py-6">
              <PublicNavItems onNavigate={() => setOpen(false)} />
              {!me && (
                <div className="flex flex-wrap gap-3 pt-2">
                  <LinkButton to="/login" size="sm">
                    Log In
                  </LinkButton>
                  <SoonButton>Sign Up</SoonButton>
                </div>
              )}
            </div>
          </nav>
        )}
      </header>
      <main id="content" className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}

function Footer() {
  const col = "flex flex-col items-start gap-3 text-sm";
  const h = "font-extrabold";
  const link = "text-subtle hover:text-accent";
  return (
    <footer className="rule-t">
      <div className="container-page grid grid-cols-2 gap-x-6 gap-y-12 py-24 lg:grid-cols-[2fr_1fr_1fr_1fr]">
        <div className="col-span-2 flex flex-col items-start gap-4 lg:col-span-1">
          <Logo />
          <p className="max-w-xs text-sm text-subtle">
            Reports for AI agents, organized by area. {BRAND} is the portal of the open-source agent-ops-kit.
          </p>
          <div className="flex flex-wrap gap-4 pt-2 text-sm text-subtle">
            <SoonText>Instagram</SoonText>
            <SoonText>LinkedIn</SoonText>
            <SoonText>X</SoonText>
          </div>
        </div>
        <div className={col}>
          <p className={h}>Product</p>
          <a href="/#features" className={link}>Features</a>
          <a href="/#how-it-works" className={link}>How it works</a>
          <a href="/#faq" className={link}>FAQ</a>
          <SoonText className="text-subtle">Pricing</SoonText>
        </div>
        <div className={col}>
          <p className={h}>Resources</p>
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className={link}>
            GitHub
          </a>
          <SoonText className="text-subtle">Docs</SoonText>
          <SoonText className="text-subtle">Blog</SoonText>
        </div>
        <div className={col}>
          <p className={h}>Company</p>
          <SoonText className="text-subtle">Contact</SoonText>
          <SoonText className="text-subtle">Terms</SoonText>
          <SoonText className="text-subtle">Privacy</SoonText>
        </div>
      </div>
      <div className="rule-t">
        <p className="container-page py-6 text-sm text-subtle">
          {BRAND} is a provisional, fictional name. Reports are self-reported and do not guarantee safety.
        </p>
      </div>
    </footer>
  );
}

// ---------------------------------------------------------------------------------------------
// Logged-in area: fixed sidebar on desktop; on mobile it becomes a menu.

function TreeNode({ node, selected, trail }: { node: AreaNode; selected: number | null; trail: Set<number> }) {
  const [open, setOpen] = useState(true);
  const has = node.children.length > 0;
  const active = node.id === selected;
  return (
    <li>
      <div className="flex items-center">
        {has ? (
          <button
            type="button"
            className="flex size-7 shrink-0 items-center justify-center font-bold text-subtle hover:text-accent"
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${node.name}`}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "−" : "+"}
          </button>
        ) : (
          <span className="size-7 shrink-0" aria-hidden="true" />
        )}
        <Link
          to={`/app/areas/${node.id}`}
          aria-current={active ? "page" : undefined}
          className={cx(
            "min-w-0 flex-1 truncate border-l-[3px] py-1 pl-2 no-underline hover:underline",
            active ? "border-accent font-extrabold" : "border-transparent font-medium",
            !active && trail.has(node.id) && "font-bold",
          )}
        >
          {node.name}
        </Link>
      </div>
      {has && open && (
        <ul className="m-0 ml-3 list-none border-l border-ink p-0 pl-2">
          {node.children.map((c) => (
            <TreeNode key={c.id} node={c} selected={selected} trail={trail} />
          ))}
        </ul>
      )}
    </li>
  );
}

function SidebarContent() {
  const { me, logout } = useAuth();
  const cat = useCatalog();
  const params = useParams();
  const selected = params.areaId ? Number(params.areaId) : null;
  const [logoutError, setLogoutError] = useState(false);
  const trail = new Set(selected ? areaPath(cat.areas, selected).map((a) => a.id) : []);
  const itemCls = ({ isActive }: { isActive: boolean }) => cx("side-item", isActive && "active");
  const label = "px-4 pb-2 pt-8 text-sm font-extrabold";

  return (
    <div className="flex h-full flex-col">
      <div className="hidden h-[72px] shrink-0 items-center px-4 lg:flex">
        <Logo to="/app" />
      </div>
      <nav aria-label="Main" className="rule-t flex-1 overflow-y-auto pb-4 pt-4">
        <NavLink to="/app" end className={itemCls}>
          All areas
        </NavLink>
        <p className={label}>Areas</p>
        {cat.ready && cat.tree.length === 0 && <p className="px-4 text-sm text-subtle">No areas available.</p>}
        <ul className="m-0 list-none px-2 p-0">
          {cat.tree.map((n) => (
            <TreeNode key={n.id} node={n} selected={selected} trail={trail} />
          ))}
        </ul>
        <p className={label}>Downloads</p>
        <NavLink to="/app/downloads" className={itemCls}>
          My downloads
        </NavLink>
        {me?.is_org_admin && (
          <>
            <p className={label}>Administration</p>
            <NavLink to="/app/admin/areas" className={itemCls}>
              Areas
            </NavLink>
            <NavLink to="/app/admin/agents" className={itemCls}>
              Agents
            </NavLink>
            <NavLink to="/app/admin/users" className={itemCls}>
              Users
            </NavLink>
            <NavLink to="/app/admin/activity" className={itemCls}>
              Activity
            </NavLink>
            <NavLink to="/app/admin/downloads" className={itemCls}>
              All downloads
            </NavLink>
          </>
        )}
      </nav>
      <div className="rule-t shrink-0 p-4">
        <p className="mb-3 truncate text-sm text-subtle" title={me?.email}>
          {me?.email}
        </p>
        <Button
          size="sm"
          className="w-full"
          onClick={async () => {
            setLogoutError(false);
            try {
              await logout(); // clears local state only after the server confirmed; then RequireAuth sends us home
            } catch {
              setLogoutError(true); // never pretend the session ended
            }
          }}
        >
          Log out
        </Button>
        {logoutError && (
          <p role="alert" className="mt-3 text-sm font-semibold">
            Could not end the session on the server; try again.
          </p>
        )}
      </div>
    </div>
  );
}

function Shell() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);

  return (
    <div className="min-h-screen">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        Skip to content
      </a>
      <div className="rule-b sticky top-0 z-40 flex h-16 items-center justify-between bg-paper px-6 lg:hidden">
        <Logo to="/app" />
        <Button size="sm" aria-expanded={open} aria-controls="app-menu" onClick={() => setOpen((v) => !v)}>
          {open ? "Close" : "Menu"}
        </Button>
      </div>
      <aside
        id="app-menu"
        className={cx(
          "z-30 bg-paper lg:fixed lg:inset-y-0 lg:left-0 lg:block lg:w-72 lg:border-r lg:border-ink",
          open ? "fixed inset-x-0 bottom-0 top-16 block" : "hidden",
        )}
      >
        <SidebarContent />
      </aside>
      <main id="content" className="lg:pl-72">
        <div className="mx-auto max-w-[1200px] px-6 py-12 lg:px-12">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

/** Everything under /app needs a session; the catalog (areas and agents) loads once per login. */
export function AppShell() {
  return (
    <RequireAuth>
      <CatalogProvider>
        <Shell />
      </CatalogProvider>
    </RequireAuth>
  );
}
