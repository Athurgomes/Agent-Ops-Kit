import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { AreaNode } from "../api";
import { areaPath, useCatalog } from "../auth";
import { Breadcrumbs, Card, ErrorBox, Loading, Tag, Title, useAsync } from "../ui";

function Tree({ nodes, selected }: { nodes: AreaNode[]; selected: number | null }) {
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {nodes.map((n) => (
        <li key={n.id}>
          <Link
            to={`/app/areas/${n.id}`}
            aria-current={n.id === selected ? "page" : undefined}
            className={`brutal block px-3 py-2 font-black no-underline ${
              n.id === selected ? "bg-yellow" : "bg-paper"
            }`}
          >
            {n.name}
          </Link>
          {n.children.length > 0 && (
            <div className="ml-4 mt-2 border-l-4 border-ink pl-3">
              <Tree nodes={n.children} selected={selected} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function Areas() {
  const { areaId } = useParams();
  const id = areaId ? Number(areaId) : null;
  const cat = useCatalog();

  return (
    <div className="flex flex-col gap-6">
      <Title>Áreas</Title>
      {!cat.ready && <Loading />}
      {cat.error && <ErrorBox>{cat.error}</ErrorBox>}
      {cat.ready && !cat.error && cat.tree.length === 0 && (
        <Card>
          <p className="font-bold">Você ainda não tem acesso a nenhuma área. Peça a um administrador.</p>
        </Card>
      )}
      {cat.tree.length > 0 && (
        <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <nav aria-label="Árvore de áreas">
            <Card tone="pink">
              <Tree nodes={cat.tree} selected={id} />
            </Card>
          </nav>
          <section aria-live="polite">
            {id == null ? (
              <Card>
                <p className="font-bold">Escolha uma área para ver os agentes.</p>
              </Card>
            ) : (
              <AreaAgents areaId={id} />
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function AreaAgents({ areaId }: { areaId: number }) {
  const cat = useCatalog();
  const st = useAsync(() => api.agents(areaId), [areaId]);
  const crumbs = areaPath(cat.areas, areaId).map((a) => ({ label: a.name }));
  const area = crumbs[crumbs.length - 1];

  return (
    <div className="flex flex-col gap-4">
      {crumbs.length > 0 && <Breadcrumbs items={[{ label: "Áreas", to: "/app" }, ...crumbs]} />}
      <Title as="h2">{area ? `Agentes de ${area.label}` : "Agentes"}</Title>
      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <Card>
          <p className="font-bold">Nenhum agente nesta área ainda.</p>
        </Card>
      )}
      {st.data && (
        <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2">
          {st.data.map((a) => (
            <li key={a.id}>
              <Link
                to={`/app/areas/${areaId}/agentes/${a.id}`}
                className="brutal brutal-shadow press flex h-full flex-col gap-2 bg-mint p-5 no-underline text-ink"
              >
                <span className="title text-xl">{a.name}</span>
                <span className="text-sm font-bold">{a.slug}</span>
                {!a.active && <Tag tone="white">Inativo</Tag>}
                <span className="mt-auto font-black uppercase">Ver relatórios →</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
