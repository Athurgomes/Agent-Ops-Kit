import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import type { AreaNode } from "./api";
import { areaPath, CatalogProvider, RequireAuth, useAuth, useCatalog } from "./auth";
import { CONTACT_URL } from "./brand";
import { copy } from "./copy";
import { Button, cx, LinkButton, Logo } from "./ui";

// ---------------------------------------------------------------------------------------------
// Public layout: fixed 72px header (logo, centered nav, actions), content and clean footer.

function PublicNavItems({ dark = false, onNavigate }: { dark?: boolean; onNavigate?: () => void }) {
  const cls = dark ? "navlink-dark" : "navlink";
  const a = (href: string, label: string) => (
    <a key={href} href={href} className={cls} onClick={onNavigate}>
      {label}
    </a>
  );
  return (
    <>
      {a("/#how-it-works", copy.nav.howItWorks)}
      {a("/#features", copy.nav.features)}
      {a("/#faq", copy.nav.faq)}
    </>
  );
}

export function PublicLayout({ children }: { children?: ReactNode } = {}) {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const isLanding = loc.pathname === "/";
  const [onDark, setOnDark] = useState(isLanding);

  useEffect(() => setOpen(false), [loc.pathname]);

  useEffect(() => {
    if (!isLanding) {
      setOnDark(false);
      return;
    }

    let rafId = 0;
    const measure = () => {
      rafId = 0;
      const hero = document.querySelector<HTMLElement>("[data-hero-iris]");
      if (!hero) {
        setOnDark((prev) => (prev ? false : prev));
        return;
      }
      const stage = hero.querySelector<HTMLElement>("[data-hero-stage]");
      if (stage) {
        const total = Math.max(1, hero.offsetHeight - stage.offsetHeight);
        const progress = Math.min(1, Math.max(0, -hero.getBoundingClientRect().top / total));
        const next = progress < 0.48;
        setOnDark((prev) => (prev === next ? prev : next));
        return;
      }
      const darkBlock = hero.querySelector<HTMLElement>("[data-hero-dark]");
      const next = darkBlock ? darkBlock.getBoundingClientRect().bottom > 72 : false;
      setOnDark((prev) => (prev === next ? prev : next));
    };

    const schedule = () => {
      if (rafId === 0) {
        rafId = requestAnimationFrame(measure);
      }
    };

    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setOnDark(true);
    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    mq.addEventListener("change", schedule);

    return () => {
      if (rafId !== 0) cancelAnimationFrame(rafId);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      mq.removeEventListener("change", schedule);
    };
  }, [isLanding]);

  const effectiveDark = isLanding && onDark;
  const hasContact = CONTACT_URL.trim().length > 0;

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        {copy.common.skipToContent}
      </a>
      <header
        className={cx(
          "sticky top-0 z-40 backdrop-blur-md transition-colors duration-200",
          effectiveDark
            ? "border-b border-white/15 bg-ink/95 text-white"
            : "border-b border-ink bg-paper/95 text-ink",
        )}
      >
        <div className="container-page grid h-[72px] grid-cols-[auto_1fr] items-center gap-6 lg:grid-cols-[1fr_auto_1fr]">
          <Logo inverted={effectiveDark} />
          <nav aria-label={copy.aria.mainNav} className="hidden items-center justify-center gap-8 lg:flex">
            <PublicNavItems dark={effectiveDark} />
          </nav>
          <div className="flex items-center justify-end gap-3">
            {me ? (
              <LinkButton to="/app" variant="primary" size="sm">
                {copy.nav.openPortal}
              </LinkButton>
            ) : (
              <>
                {hasContact && (
                  <a
                    href={CONTACT_URL}
                    className={cx(
                      "btn btn-sm hidden sm:inline-flex",
                      effectiveDark ? "btn-ghost-dark" : "btn-secondary",
                    )}
                  >
                    {copy.nav.contact}
                  </a>
                )}
                <LinkButton to="/login" variant="primary" size="sm" className="hidden sm:inline-flex">
                  {copy.nav.login}
                </LinkButton>
              </>
            )}
            <button
              type="button"
              className={cx("btn btn-sm lg:hidden", effectiveDark ? "btn-ghost-dark" : "")}
              aria-expanded={open}
              aria-controls="public-menu"
              onClick={() => setOpen((v) => !v)}
            >
              {open ? copy.common.close : copy.common.menu}
            </button>
          </div>
        </div>
        {open && (
          <nav
            id="public-menu"
            aria-label={copy.aria.mobileMenu}
            className={cx(
              "lg:hidden",
              effectiveDark ? "border-t border-white/15 bg-ink text-white" : "border-t border-ink bg-paper text-ink",
            )}
          >
            <div className="container-page flex flex-col items-start gap-4 py-6">
              <PublicNavItems dark={effectiveDark} onNavigate={() => setOpen(false)} />
              {me ? (
                <div className="pt-2">
                  <LinkButton to="/app" variant="primary" size="sm">
                    {copy.nav.openPortal}
                  </LinkButton>
                </div>
              ) : (
                <div className="flex flex-wrap gap-3 pt-2">
                  <LinkButton to="/login" variant="primary" size="sm">
                    {copy.nav.login}
                  </LinkButton>
                  {hasContact && (
                    <a
                      href={CONTACT_URL}
                      className={cx("btn btn-sm", effectiveDark ? "btn-ghost-dark" : "btn-secondary")}
                    >
                      {copy.nav.contact}
                    </a>
                  )}
                </div>
              )}
            </div>
          </nav>
        )}
      </header>
      <main id="content" className="w-full min-w-0 flex-1 overflow-x-clip">
        {children ?? <Outlet />}
      </main>
      <Footer />
    </div>
  );
}

function Footer() {
  const { me } = useAuth();
  const hasContact = CONTACT_URL.trim().length > 0;
  const col = "flex flex-col items-start gap-3 text-sm";
  const h = "font-mono text-xs font-semibold uppercase tracking-[0.08em] text-ink";
  const link = "text-subtle hover:text-accent";
  return (
    <footer className="border-t border-ink bg-paper text-ink">
      <div className="container-page grid grid-cols-2 gap-x-6 gap-y-12 py-20 lg:grid-cols-[2fr_1fr_1fr]">
        <div className="col-span-2 flex flex-col items-start gap-4 lg:col-span-1">
          <Logo />
          <p className="max-w-xs text-sm text-subtle">{copy.footer.description}</p>
        </div>
        <div className={col}>
          <p className={h}>{copy.footer.productHeading}</p>
          <a href="/#how-it-works" className={link}>
            {copy.nav.howItWorks}
          </a>
          <a href="/#features" className={link}>
            {copy.nav.features}
          </a>
          <a href="/#faq" className={link}>
            {copy.nav.faq}
          </a>
        </div>
        <div className={col}>
          <p className={h}>{copy.footer.portalHeading}</p>
          <Link to={me ? "/app" : "/login"} className={link}>
            {me ? copy.nav.openPortal : copy.nav.login}
          </Link>
          {hasContact && (
            <a href={CONTACT_URL} className={link}>
              {copy.nav.contact}
            </a>
          )}
        </div>
      </div>
      <div className="border-t border-line">
        <p className="container-page py-6 font-mono text-xs text-subtle">{copy.footer.disclaimer}</p>
      </div>
    </footer>
  );
}

// ---------------------------------------------------------------------------------------------
// Logged-in area: fixed logbook sidebar on desktop; on mobile it becomes a menu.

function TreeNode({
  node,
  selected,
  trail,
  isChild = false,
}: {
  node: AreaNode;
  selected: number | null;
  trail: Set<number>;
  isChild?: boolean;
}) {
  const [open, setOpen] = useState(true);
  const has = node.children.length > 0;
  const active = node.id === selected;
  return (
    <li>
      <div className="flex items-center">
        {has ? (
          <button
            type="button"
            className="flex size-7 shrink-0 items-center justify-center font-mono text-xs font-semibold text-subtle hover:text-accent"
            aria-expanded={open}
            aria-label={`${open ? copy.app.collapse : copy.app.expand} ${node.name}`}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "−" : "+"}
          </button>
        ) : (
          <span className="flex w-7 shrink-0 items-center justify-center font-mono text-xs text-subtle" aria-hidden="true">
            {isChild ? "├──" : "·"}
          </span>
        )}
        <Link
          to={`/app/areas/${node.id}`}
          aria-current={active ? "page" : undefined}
          className={cx(
            "min-w-0 flex-1 truncate border-l-2 py-1.5 pl-2.5 text-sm no-underline hover:bg-surface hover:underline",
            active ? "border-accent bg-accent-soft font-bold text-accent" : "border-transparent font-medium text-ink",
            !active && trail.has(node.id) && "font-bold",
          )}
        >
          {node.name}
        </Link>
      </div>
      {has && open && (
        <ul className="m-0 ml-3 list-none border-l border-ink/25 p-0 pl-2">
          {node.children.map((c) => (
            <TreeNode key={c.id} node={c} selected={selected} trail={trail} isChild />
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
  const itemCls = ({ isActive }: { isActive: boolean }) => cx("side-item text-sm", isActive && "active");
  const sectionLabel =
    "mt-6 border-t border-ink/20 px-4 pb-2 pt-4 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle";

  return (
    <div className="flex h-full flex-col bg-paper">
      <div className="hidden h-[72px] shrink-0 items-center justify-between border-b border-ink px-4 lg:flex">
        <Logo to="/app" />
        <span className="border border-ink bg-surface px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-ink">
          {copy.app.logbookTag}
        </span>
      </div>
      <nav aria-label={copy.aria.appNav} className="flex-1 overflow-y-auto pb-4 pt-3">
        <NavLink to="/app" end className={itemCls}>
          {copy.app.allAreas}
        </NavLink>
        <p className={sectionLabel}>{copy.app.areasHeading}</p>
        {cat.ready && cat.tree.length === 0 && <p className="px-4 text-sm text-subtle">{copy.app.noAreas}</p>}
        <ul className="m-0 list-none px-2 p-0">
          {cat.tree.map((n) => (
            <TreeNode key={n.id} node={n} selected={selected} trail={trail} />
          ))}
        </ul>
        <p className={sectionLabel}>{copy.app.downloadsHeading}</p>
        <NavLink to="/app/downloads" className={itemCls}>
          {copy.app.myDownloads}
        </NavLink>
        {me?.is_org_admin && (
          <>
            <p className={sectionLabel}>{copy.app.adminHeading}</p>
            <NavLink to="/app/admin/areas" className={itemCls}>
              {copy.app.adminAreas}
            </NavLink>
            <NavLink to="/app/admin/agents" className={itemCls}>
              {copy.app.adminAgents}
            </NavLink>
            <NavLink to="/app/admin/users" className={itemCls}>
              {copy.app.adminUsers}
            </NavLink>
            <NavLink to="/app/admin/activity" className={itemCls}>
              {copy.app.adminActivity}
            </NavLink>
            <NavLink to="/app/admin/downloads" className={itemCls}>
              {copy.app.adminDownloads}
            </NavLink>
          </>
        )}
      </nav>
      <div className="shrink-0 border-t border-ink p-4">
        <p className="mb-3 truncate font-mono text-xs text-subtle" title={me?.email}>
          {me?.email}
        </p>
        <Button
          size="sm"
          className="w-full"
          onClick={async () => {
            setLogoutError(false);
            try {
              await logout();
            } catch {
              setLogoutError(true);
            }
          }}
        >
          {copy.app.logout}
        </Button>
        {logoutError && (
          <p role="alert" className="mt-3 text-sm font-semibold">
            {copy.app.logoutError}
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
    <div className="min-h-screen bg-paper text-ink">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        {copy.common.skipToContent}
      </a>
      <div className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-ink bg-paper px-6 lg:hidden">
        <div className="flex items-center gap-3">
          <Logo to="/app" />
          <span className="border border-ink bg-surface px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-ink">
            {copy.app.logbookTag}
          </span>
        </div>
        <Button size="sm" aria-expanded={open} aria-controls="app-menu" onClick={() => setOpen((v) => !v)}>
          {open ? copy.common.close : copy.common.menu}
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
        <div className="mx-auto max-w-[1200px] px-5 py-10 sm:px-6 lg:px-12 lg:py-12">
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
