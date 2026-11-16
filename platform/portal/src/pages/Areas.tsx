import { Link, useParams } from "react-router-dom";
import { areaPath, useCatalog } from "../auth";
import { EmptyState, ErrorBox, Loading, PageHeader, Tag } from "../ui";

export function Areas() {
  const { areaId } = useParams();
  const cat = useCatalog();
  const id = areaId ? Number(areaId) : null;

  if (!cat.ready) return <Loading />;
  if (cat.error) return <ErrorBox>{cat.error}</ErrorBox>;

  // sem área escolhida: cartões das áreas de topo; com área: sub-áreas e agentes
  const subareas = cat.areas.filter((a) => a.parent_id === id);
  const here = id != null ? cat.areas.find((a) => a.id === id) : null;
  const agents = id != null ? cat.agents.filter((a) => a.area_id === id) : [];
  const crumbs =
    id == null
      ? [{ label: "Áreas" }]
      : [
          { label: "Áreas", to: "/app" },
          ...areaPath(cat.areas, id).map((a, i, all) =>
            i === all.length - 1 ? { label: a.name } : { label: a.name, to: `/app/areas/${a.id}` },
          ),
        ];

  if (id != null && !here) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Áreas", to: "/app" }, { label: "Não encontrada" }]} title="Área não encontrada" />
        <EmptyState title="Esta área não existe ou você não tem acesso." />
      </>
    );
  }

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={here ? here.name : "Áreas"}
        lead={
          here
            ? "Agentes desta área. Escolha um para ver os relatórios publicados."
            : "Escolha uma área para ver os agentes e os relatórios publicados."
        }
      />

      {cat.tree.length === 0 && (
        <EmptyState title="Você ainda não tem acesso a nenhuma área.">
          Peça a um administrador da sua organização.
        </EmptyState>
      )}

      {subareas.length > 0 && (
        <section aria-labelledby="sub" className="mb-12">
          <h2 id="sub" className="display mb-4 text-xl">
            {here ? "Sub-áreas" : "Suas áreas"}
          </h2>
          <ul className="m-0 grid list-none grid-cols-1 gap-6 p-0 md:grid-cols-2 xl:grid-cols-3">
            {subareas.map((a) => {
              const n = cat.agents.filter((g) => g.area_id === a.id).length;
              const subs = cat.areas.filter((s) => s.parent_id === a.id).length;
              return (
                <li key={a.id}>
                  <Link
                    to={`/app/areas/${a.id}`}
                    className="brutal card-link flex h-full flex-col gap-2 bg-pink p-6 no-underline"
                  >
                    <span className="display text-xl">{a.name}</span>
                    <span className="text-sm">
                      {n} {n === 1 ? "agente" : "agentes"}
                      {subs > 0 && ` · ${subs} ${subs === 1 ? "sub-área" : "sub-áreas"}`}
                    </span>
                    <span className="mt-auto pt-4 font-bold">Abrir área →</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {here && (
        <section aria-labelledby="agentes">
          <h2 id="agentes" className="display mb-4 text-xl">
            Agentes
          </h2>
          {agents.length === 0 ? (
            <EmptyState title="Nenhum agente nesta área ainda." />
          ) : (
            <ul className="m-0 grid list-none grid-cols-1 gap-6 p-0 md:grid-cols-2 xl:grid-cols-3">
              {agents.map((a) => (
                <li key={a.id}>
                  <Link
                    to={`/app/areas/${a.area_id}/agentes/${a.id}`}
                    className="brutal card-link flex h-full flex-col gap-2 bg-paper p-6 no-underline"
                  >
                    <span className="display text-lg">{a.name}</span>
                    <span className="font-mono text-sm">{a.slug}</span>
                    <span className="mt-auto flex items-center justify-between pt-4">
                      <span className="font-bold">Ver relatórios →</span>
                      {!a.active && <Tag tone="muted">Inativo</Tag>}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
