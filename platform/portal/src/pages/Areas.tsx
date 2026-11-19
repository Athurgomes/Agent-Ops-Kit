import { Link, useParams } from "react-router-dom";
import { areaPath, useCatalog } from "../auth";
import { copy } from "../copy";
import { EmptyState, ErrorBox, Loading, PageHeader, Tag } from "../ui";

const fmtIdx = (i: number) => String(i + 1).padStart(2, "0");

export function Areas() {
  const { areaId } = useParams();
  const cat = useCatalog();
  const id = areaId ? Number(areaId) : null;

  if (!cat.ready) return <Loading />;
  if (cat.error) return <ErrorBox>{cat.error}</ErrorBox>;

  const subareas = cat.areas.filter((a) => a.parent_id === id);
  const here = id != null ? cat.areas.find((a) => a.id === id) : null;
  const agents = id != null ? cat.agents.filter((a) => a.area_id === id) : [];
  const crumbs =
    id == null
      ? [{ label: copy.areas.crumbRoot }]
      : [
          { label: copy.areas.crumbRoot, to: "/app" },
          ...areaPath(cat.areas, id).map((a, i, all) =>
            i === all.length - 1 ? { label: a.name } : { label: a.name, to: `/app/areas/${a.id}` },
          ),
        ];

  if (id != null && !here) {
    return (
      <>
        <PageHeader
          crumbs={[{ label: copy.areas.crumbRoot, to: "/app" }, { label: copy.areas.notFoundCrumb }]}
          title={copy.areas.notFoundTitle}
          stamp={copy.areas.stampArea}
        />
        <EmptyState title={copy.areas.notFoundBody} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={here ? here.name : copy.areas.titleRoot}
        lead={here ? copy.areas.leadHere : copy.areas.leadRoot}
        stamp={here ? copy.areas.stampArea : copy.areas.stampRoot}
      />

      {cat.tree.length === 0 && (
        <EmptyState title={copy.areas.emptyTitle}>{copy.areas.emptyHint}</EmptyState>
      )}

      {subareas.length > 0 && (
        <section aria-labelledby="sub" className="mb-12">
          <div className="mb-4 flex items-baseline justify-between gap-4">
            <h2 id="sub" className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-subtle">
              {here ? copy.areas.subareas : copy.areas.yourAreas}
            </h2>
            <span className="font-mono text-xs tabular-nums text-subtle">
              {String(subareas.length).padStart(2, "0")}
            </span>
          </div>

          <div className="overflow-x-auto border border-ink bg-paper">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col" className="w-20">
                    {copy.areas.columns.index}
                  </th>
                  <th scope="col">{copy.areas.columns.area}</th>
                  <th scope="col" className="w-28">
                    {copy.areas.columns.agents}
                  </th>
                  <th scope="col" className="w-32">
                    {copy.areas.columns.subareas}
                  </th>
                  <th scope="col" className="w-28 text-right">
                    {copy.areas.columns.action}
                  </th>
                </tr>
              </thead>
              <tbody>
                {subareas.map((a, idx) => {
                  const n = cat.agents.filter((g) => g.area_id === a.id).length;
                  const subs = cat.areas.filter((s) => s.parent_id === a.id).length;
                  return (
                    <tr key={a.id} className="hover:bg-surface">
                      <td className="font-mono text-xs font-semibold tabular-nums text-subtle">{fmtIdx(idx)}</td>
                      <th scope="row">
                        <Link
                          to={`/app/areas/${a.id}`}
                          className="font-display text-xl font-extrabold text-ink no-underline hover:text-accent"
                        >
                          {a.name}
                        </Link>
                      </th>
                      <td className="font-mono text-sm tabular-nums text-ink">{String(n).padStart(2, "0")}</td>
                      <td className="font-mono text-sm tabular-nums text-subtle">{String(subs).padStart(2, "0")}</td>
                      <td className="text-right">
                        <Link to={`/app/areas/${a.id}`} className="link font-mono text-xs uppercase tracking-[0.05em]">
                          {copy.areas.open}
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {here && (
        <section aria-labelledby="agents">
          <div className="mb-4 flex items-baseline justify-between gap-4">
            <h2 id="agents" className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-subtle">
              {copy.areas.agents}
            </h2>
            <span className="font-mono text-xs tabular-nums text-subtle">
              {String(agents.length).padStart(2, "0")}
            </span>
          </div>

          {agents.length === 0 ? (
            <EmptyState title={copy.areas.emptyAgents} />
          ) : (
            <div className="overflow-x-auto border border-ink bg-paper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col" className="w-20">
                      {copy.areas.agentColumns.index}
                    </th>
                    <th scope="col">{copy.areas.agentColumns.agent}</th>
                    <th scope="col">{copy.areas.agentColumns.slug}</th>
                    <th scope="col" className="w-32">
                      {copy.areas.agentColumns.status}
                    </th>
                    <th scope="col" className="w-36 text-right">
                      {copy.areas.agentColumns.action}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((a, idx) => (
                    <tr key={a.id} className="hover:bg-surface">
                      <td className="font-mono text-xs font-semibold tabular-nums text-subtle">{fmtIdx(idx)}</td>
                      <th scope="row">
                        <Link
                          to={`/app/areas/${a.area_id}/agents/${a.id}`}
                          className="font-display text-xl font-extrabold text-ink no-underline hover:text-accent"
                        >
                          {a.name}
                        </Link>
                      </th>
                      <td className="font-mono text-xs text-subtle">{a.slug}</td>
                      <td>
                        <Tag>{a.active ? copy.areas.active : copy.areas.inactive}</Tag>
                      </td>
                      <td className="text-right">
                        <Link
                          to={`/app/areas/${a.area_id}/agents/${a.id}`}
                          className="link font-mono text-xs uppercase tracking-[0.05em]"
                        >
                          {copy.areas.viewReports}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
