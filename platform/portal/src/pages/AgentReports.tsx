import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { areaPath, useCatalog } from "../auth";
import { fmtDate } from "../format";
import { EmptyState, ErrorBox, LinkButton, Loading, PageHeader, SemaforoBadge, useAsync } from "../ui";

export function AgentReports() {
  const { areaId, agentId } = useParams();
  const aid = Number(areaId);
  const gid = Number(agentId);
  const cat = useCatalog();
  const agent = cat.agents.find((a) => a.id === gid);
  const st = useAsync(() => api.reports(gid), [gid]);
  const crumbs = [
    { label: "Areas", to: "/app" },
    ...areaPath(cat.areas, aid).map((a) => ({ label: a.name, to: `/app/areas/${a.id}` })),
    { label: agent?.name ?? "Agent" },
  ];
  const [latest, ...older] = st.data ?? [];

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={agent?.name ?? "Reports"}
        lead="Reports published for this agent. They are self-reported by the team that owns it."
      />
      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <EmptyState title="No reports published yet.">
          When the team publishes the first report for this agent, it will show up here.
        </EmptyState>
      )}

      {latest && (
        <section aria-labelledby="latest" className="mb-12">
          <h2 id="latest" className="mb-4 text-lg font-extrabold">
            Latest report
          </h2>
          <div className="box grid grid-cols-12 items-end gap-6 p-6 lg:p-8">
            <div className="col-span-12 flex flex-col items-start gap-4 md:col-span-5">
              <SemaforoBadge value={latest.status_semaforo} size="lg" />
              <p className="heading text-5xl">Version {latest.seq}</p>
            </div>
            <dl className="col-span-12 m-0 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 md:col-span-4">
              <dt className="text-subtle">Generated</dt>
              <dd className="m-0 font-semibold">{fmtDate(latest.generated_at)}</dd>
              <dt className="text-subtle">Published</dt>
              <dd className="m-0 font-semibold">{fmtDate(latest.published_at)}</dd>
            </dl>
            <div className="col-span-12 md:col-span-3 md:justify-self-end">
              <LinkButton to={`/app/reports/${latest.id}`} variant="primary">
                Open report
              </LinkButton>
            </div>
          </div>
        </section>
      )}

      {older.length > 0 && (
        <section aria-labelledby="previous">
          <h2 id="previous" className="mb-4 text-lg font-extrabold">
            Previous versions
          </h2>
          <div className="box overflow-x-auto">
            <table className="data-table min-w-[36rem]">
              <caption className="sr-only">Previous report versions</caption>
              <thead>
                <tr>
                  <th scope="col">Version</th>
                  <th scope="col">Traffic light</th>
                  <th scope="col">Generated</th>
                  <th scope="col">Published</th>
                  <th scope="col">
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {older.map((r) => (
                  <tr key={r.id}>
                    <td className="font-bold">Version {r.seq}</td>
                    <td>
                      <SemaforoBadge value={r.status_semaforo} />
                    </td>
                    <td>{fmtDate(r.generated_at)}</td>
                    <td>{fmtDate(r.published_at)}</td>
                    <td className="text-right">
                      <Link to={`/app/reports/${r.id}`} className="link">
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
