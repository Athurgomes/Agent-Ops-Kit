import { Link, useParams } from "react-router-dom";
import { areaPath, useCatalog } from "../auth";
import { EmptyState, ErrorBox, Loading, PageHeader, Tag } from "../ui";

const ROW = "rule-t group grid grid-cols-[1fr_auto] items-baseline gap-4 py-5 no-underline last:border-b last:border-ink";

export function Areas() {
  const { areaId } = useParams();
  const cat = useCatalog();
  const id = areaId ? Number(areaId) : null;

  if (!cat.ready) return <Loading />;
  if (cat.error) return <ErrorBox>{cat.error}</ErrorBox>;

  // no area chosen: top-level areas; with an area: its sub-areas and agents
  const subareas = cat.areas.filter((a) => a.parent_id === id);
  const here = id != null ? cat.areas.find((a) => a.id === id) : null;
  const agents = id != null ? cat.agents.filter((a) => a.area_id === id) : [];
  const crumbs =
    id == null
      ? [{ label: "Areas" }]
      : [
          { label: "Areas", to: "/app" },
          ...areaPath(cat.areas, id).map((a, i, all) =>
            i === all.length - 1 ? { label: a.name } : { label: a.name, to: `/app/areas/${a.id}` },
          ),
        ];

  if (id != null && !here) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Areas", to: "/app" }, { label: "Not found" }]} title="Area not found" />
        <EmptyState title="This area does not exist, or you do not have access to it." />
      </>
    );
  }

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={here ? here.name : "Areas"}
        lead={
          here
            ? "The agents in this area. Pick one to see its published reports."
            : "Pick an area to see its agents and their published reports."
        }
      />

      {cat.tree.length === 0 && (
        <EmptyState title="You do not have access to any area yet.">Ask an admin of your organization.</EmptyState>
      )}

      {subareas.length > 0 && (
        <section aria-labelledby="sub" className="mb-12">
          <h2 id="sub" className="mb-4 text-lg font-extrabold">
            {here ? "Sub-areas" : "Your areas"}
          </h2>
          <ul className="m-0 list-none p-0">
            {subareas.map((a) => {
              const n = cat.agents.filter((g) => g.area_id === a.id).length;
              const subs = cat.areas.filter((s) => s.parent_id === a.id).length;
              return (
                <li key={a.id}>
                  <Link to={`/app/areas/${a.id}`} className={ROW}>
                    <span>
                      <span className="heading block text-2xl group-hover:text-accent">{a.name}</span>
                      <span className="text-sm text-subtle">
                        {n} {n === 1 ? "agent" : "agents"}
                        {subs > 0 && ` · ${subs} ${subs === 1 ? "sub-area" : "sub-areas"}`}
                      </span>
                    </span>
                    <span className="link">Open →</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {here && (
        <section aria-labelledby="agents">
          <h2 id="agents" className="mb-4 text-lg font-extrabold">
            Agents
          </h2>
          {agents.length === 0 ? (
            <EmptyState title="No agents in this area yet." />
          ) : (
            <ul className="m-0 list-none p-0">
              {agents.map((a) => (
                <li key={a.id}>
                  <Link to={`/app/areas/${a.area_id}/agents/${a.id}`} className={ROW}>
                    <span>
                      <span className="heading block text-2xl group-hover:text-accent">{a.name}</span>
                      <span className="font-mono text-sm text-subtle">{a.slug}</span>
                    </span>
                    <span className="flex items-center gap-4">
                      {!a.active && <Tag>Inactive</Tag>}
                      <span className="link">View reports →</span>
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
