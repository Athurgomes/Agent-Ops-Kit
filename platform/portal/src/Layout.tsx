import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import type { AreaNode } from "./api";
import { areaPath, CatalogProvider, RequireAuth, useAuth, useCatalog } from "./auth";
import { BRAND, REPO_URL } from "./brand";
import { Button, Chevron, cx, LinkButton, Logo, SoonButton, SoonText } from "./ui";

// ---------------------------------------------------------------------------------------------
// Public layout: fixed 72px header (logo, centered nav, actions), content and full footer.

const NAV = [
  { href: "/#features", label: "Features" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#faq", label: "FAQ" },
];

function PublicNavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      {NAV.slice(0, 2).map((l) => (
        <a key={l.href} href={l.href} className="navlink" onClick={onNavigate}>
          {l.label}
        </a>
      ))}
      <SoonText className="font-medium text-ink">Pricing</SoonText>
      {NAV.slice(2).map((l) => (
        <a key={l.href} href={l.href} className="navlink" onClick={onNavigate}>
          {l.label}
        </a>
      ))}
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
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-lg focus:bg-paper focus:p-4">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-line bg-paper/90 backdrop-blur">
        <div className="container-page grid h-[72px] grid-cols-[auto_1fr_auto] items-center gap-6 lg:grid-cols-[1fr_auto_1fr]">
          <Logo />
          <nav aria-label="Main" className="hidden items-center justify-center gap-8 lg:flex">
            <PublicNavItems />
          </nav>
          <div className="flex items-center justify-end gap-2">
            {me ? (
              <LinkButton to="/app" variant="primary" size="sm">
                Open portal
              </LinkButton>
            ) : (
              <>
                <LinkButton to="/login" variant="secondary" size="sm" className="hidden sm:inline-flex">
                  Log In
                </LinkButton>
                <SoonButton className="hidden sm:inline-flex">Sign Up</SoonButton>
              </>
            )}
            <Button
              size="sm"
              className="lg:hidden"
              aria-expanded={open}
              aria-controls="public-menu"
              onClick={() => setOpen((v) => !v)}
            >
              Menu
            </Button>
          </div>
        </div>
        {open && (
          <nav id="public-menu" aria-label="Menu" className="border-t border-line bg-paper lg:hidden">
            <div className="container-page flex flex-col items-start gap-4 py-6">
              <PublicNavItems onNavigate={() => setOpen(false)} />
              {!me && (
                <div className="flex flex-wrap gap-2 pt-2">
                  <LinkButton to="/login" variant="secondary" size="sm">
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
  const col = "flex flex-col items-start gap-3";
  const h = "text-sm font-semibold text-navy";
  return (
    <footer className="border-t border-line bg-soft">
      <div className="container-page grid grid-cols-2 gap-x-6 gap-y-12 py-24 lg:grid-cols-[2fr_1fr_1fr_1fr]">
        <div className="col-span-2 flex flex-col items-start gap-4 lg:col-span-1">
          <Logo />
          <p className="max-w-xs text-sm text-subtle">
            Reports for AI agents, organized by area. {BRAND} is the portal of the open-source agent-ops-kit.
          </p>
          <div className="flex flex-wrap gap-4 pt-2 text-sm">
            <SoonText>Instagram</SoonText>
            <SoonText>LinkedIn</SoonText>
            <SoonText>X</SoonText>
          </div>
        </div>
        <div className={col}>
          <p className={h}>Product</p>
          <a href="/#features" className="text-sm text-subtle hover:text-accent">Features</a>
          <a href="/#how-it-works" className="text-sm text-subtle hover:text-accent">How it works</a>
          <a href="/#faq" className="text-sm text-subtle hover:text-accent">FAQ</a>
          <SoonText className="text-sm">Pricing</SoonText>
        </div>
        <div className={col}>
          <p className={h}>Resources</p>
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="text-sm text-subtle hover:text-accent">
            GitHub
          </a>
          <SoonText className="text-sm">Docs</SoonText>
          <SoonText className="text-sm">Blog</SoonText>
        </div>
        <div className={col}>
          <p className={h}>Company</p>
          <SoonText className="text-sm">Contact</SoonText>
          <SoonText className="text-sm">Terms</SoonText>
          <SoonText className="text-sm">Privacy</SoonText>
        </div>
      </div>
      <div className="border-t border-line">
        <p className="container-page py-6 text-sm text-subtle">
          {BRAND} is a provisional, fictional name. Reports are self-reported and do not guarantee safety.
        </p>
      </div>
    </footer>
  );
}

// ---------------------------------------------------------------------------------------------
// Logged-in area: light fixed sidebar on desktop; on mobile it becomes a menu.

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
            className="flex size-8 shrink-0 items-center justify-center rounded-lg text-subtle hover:bg-soft"
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${node.name}`}
            onClick={() => setOpen((v) => !v)}
          >
            <Chevron className={open ? "" : "-rotate-90"} />
          </button>
        ) : (
          <span className="size-8 shrink-0" aria-hidden="true" />
        )}
        <Link
          to={`/app/areas/${node.id}`}
          aria-current={active ? "page" : undefined}
          className={cx(
            "min-w-0 flex-1 truncate rounded-lg px-2 py-1 no-underline hover:bg-soft",
            active ? "bg-tint font-bold text-navy hover:bg-tint" : "font-medium",
            !active && trail.has(node.id) && "text-navy",
          )}
        >
          {node.name}
        </Link>
      </div>
      {has && open && (
        <ul className="m-0 ml-4 list-none border-l border-line p-0 pl-2">
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
  const nav = useNavigate();
  const params = useParams();
  const selected = params.areaId ? Number(params.areaId) : null;
  const trail = new Set(selected ? areaPath(cat.areas, selected).map((a) => a.id) : []);
  const itemCls = ({ isActive }: { isActive: boolean }) => cx("side-item", isActive && "active");
  const label = "px-4 pb-1 pt-6 text-xs font-semibold uppercase tracking-wide text-subtle";

  return (
    <div className="flex h-full flex-col">
      <div className="hidden h-[72px] shrink-0 items-center px-6 lg:flex">
        <Logo to="/app" />
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 pb-4">
        <NavLink to="/app" end className={itemCls}>
          All areas
        </NavLink>
        <p className={label}>Areas</p>
        {cat.ready && cat.tree.length === 0 && <p className="px-4 text-sm text-subtle">No areas available.</p>}
        <ul className="m-0 list-none p-0">
          {cat.tree.map((n) => (
            <TreeNode key={n.id} node={n} selected={selected} trail={trail} />
          ))}
        </ul>
        <p className={label}>Downloads</p>
        <NavLink to="/app/downloads" className={itemCls}>
          My downloads
        </NavLink>
        {me?.is_org_admin && (
          <NavLink to="/app/admin/downloads" className={itemCls}>
            All downloads
          </NavLink>
        )}
      </nav>
      <div className="shrink-0 border-t border-line p-4">
        <p className="mb-2 truncate text-sm text-subtle" title={me?.email}>
          {me?.email}
        </p>
        <Button
          size="sm"
          className="w-full"
          onClick={async () => {
            await logout();
            nav("/");
          }}
        >
          Log out
        </Button>
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
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-lg focus:bg-paper focus:p-4">
        Skip to content
      </a>
      <div className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-line bg-paper px-6 lg:hidden">
        <Logo to="/app" />
        <Button size="sm" aria-expanded={open} aria-controls="app-menu" onClick={() => setOpen((v) => !v)}>
          {open ? "Close" : "Menu"}
        </Button>
      </div>
      <aside
        id="app-menu"
        className={cx(
          "z-30 bg-paper lg:fixed lg:inset-y-0 lg:left-0 lg:block lg:w-72 lg:border-r lg:border-line",
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
