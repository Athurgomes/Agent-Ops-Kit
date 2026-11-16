import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import type { AreaNode } from "./api";
import { areaPath, CatalogProvider, RequireAuth, useAuth, useCatalog } from "./auth";
import { BRAND } from "./brand";
import { Button, Chevron, cx, LinkButton, Logo } from "./ui";

// ---------------------------------------------------------------------------------------------
// Layout público: cabeçalho fixo de 72px, conteúdo e rodapé.

const PUBLIC_LINKS = [
  { href: "/#como", label: "Como funciona" },
  { href: "/#recursos", label: "Recursos" },
  { href: "/#limites", label: "Limitações" },
  { href: "/#perguntas", label: "Perguntas" },
];

export function PublicLayout() {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#conteudo" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-yellow focus:p-4 brutal">
        Ir para o conteúdo
      </a>
      <header className="sticky top-0 z-40 border-b-[3px] border-ink bg-paper">
        <div className="container-page flex h-[72px] items-center gap-6">
          <Logo />
          <nav aria-label="Principal" className="ml-auto hidden items-center gap-6 lg:flex">
            {PUBLIC_LINKS.map((l) => (
              <a key={l.href} href={l.href} className="navlink">
                {l.label}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4 lg:ml-0">
            {me ? (
              <LinkButton to="/app" variant="primary" size="sm">
                Abrir portal
              </LinkButton>
            ) : (
              <LinkButton to="/entrar" variant="primary" size="sm">
                Entrar
              </LinkButton>
            )}
            <Button
              size="sm"
              className="lg:hidden"
              aria-expanded={open}
              aria-controls="menu-publico"
              onClick={() => setOpen((v) => !v)}
            >
              Menu
            </Button>
          </div>
        </div>
        {open && (
          <nav id="menu-publico" aria-label="Menu" className="border-t-[3px] border-ink bg-paper lg:hidden">
            <ul className="container-page m-0 flex list-none flex-col gap-2 py-4">
              {PUBLIC_LINKS.map((l) => (
                <li key={l.href}>
                  <a href={l.href} className="navlink">
                    {l.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </header>
      <main id="conteudo" className="min-h-[calc(100vh-72px)] flex-1">
        <Outlet />
      </main>
      <footer className="border-t-[3px] border-ink bg-ink text-paper">
        <div className="container-page flex flex-col gap-4 py-12 lg:flex-row lg:items-center lg:justify-between">
          <p className="display text-2xl">{BRAND}</p>
          <p className="max-w-xl text-sm">
            {BRAND} é um nome provisório e fictício. Os relatórios são autodeclarados e não garantem
            segurança. Projeto de código aberto agent-ops-kit.
          </p>
        </div>
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Área logada: sidebar fixa no desktop; no celular vira menu.

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
            className="flex size-8 shrink-0 items-center justify-center hover:bg-muted"
            aria-expanded={open}
            aria-label={`${open ? "Recolher" : "Expandir"} ${node.name}`}
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
            "min-w-0 flex-1 truncate px-2 py-1 font-semibold no-underline hover:bg-muted",
            active && "bg-yellow hover:bg-yellow",
            !active && trail.has(node.id) && "underline",
          )}
        >
          {node.name}
        </Link>
      </div>
      {has && open && (
        <ul className="m-0 ml-4 list-none border-l-[3px] border-ink p-0 pl-2">
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

  return (
    <div className="flex h-full flex-col">
      <div className="hidden h-[72px] shrink-0 items-center border-b-[3px] border-ink px-6 lg:flex">
        <Logo to="/app" />
      </div>
      <nav aria-label="Principal" className="flex-1 overflow-y-auto py-4">
        <NavLink to="/app" end className={itemCls}>
          Todas as áreas
        </NavLink>
        <p className="px-6 pb-1 pt-4 text-sm font-bold text-ink/70">Árvore de áreas</p>
        <div className="px-2">
          {cat.ready && cat.tree.length === 0 && <p className="px-4 text-sm">Nenhuma área liberada.</p>}
          <ul className="m-0 list-none p-0">
            {cat.tree.map((n) => (
              <TreeNode key={n.id} node={n} selected={selected} trail={trail} />
            ))}
          </ul>
        </div>
        <p className="px-6 pb-1 pt-6 text-sm font-bold text-ink/70">Downloads</p>
        <NavLink to="/app/downloads" className={itemCls}>
          Meus downloads
        </NavLink>
        {me?.is_org_admin && (
          <NavLink to="/app/admin/downloads" className={itemCls}>
            Todos os downloads
          </NavLink>
        )}
      </nav>
      <div className="shrink-0 border-t-[3px] border-ink bg-muted p-4">
        <p className="mb-2 truncate text-sm font-semibold" title={me?.email}>
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
          Sair
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
      <a href="#conteudo" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-yellow focus:p-4 brutal">
        Ir para o conteúdo
      </a>
      {/* celular: barra superior com o botão de menu */}
      <div className="sticky top-0 z-40 flex h-16 items-center justify-between border-b-[3px] border-ink bg-paper px-6 lg:hidden">
        <Logo to="/app" />
        <Button size="sm" aria-expanded={open} aria-controls="menu-app" onClick={() => setOpen((v) => !v)}>
          {open ? "Fechar" : "Menu"}
        </Button>
      </div>
      <aside
        id="menu-app"
        className={cx(
          "z-30 bg-paper lg:fixed lg:inset-y-0 lg:left-0 lg:block lg:w-72 lg:border-r-[3px] lg:border-ink",
          open ? "fixed inset-x-0 bottom-0 top-16 block" : "hidden",
        )}
      >
        <SidebarContent />
      </aside>
      <main id="conteudo" className="lg:pl-72">
        <div className="mx-auto max-w-[1200px] px-6 py-12 lg:px-12">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

/** Tudo em /app exige sessão; o catálogo (áreas e agentes) é carregado uma vez por login. */
export function AppShell() {
  return (
    <RequireAuth>
      <CatalogProvider>
        <Shell />
      </CatalogProvider>
    </RequireAuth>
  );
}
