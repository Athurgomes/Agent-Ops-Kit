import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { areaPath, useCatalog } from "../auth";
import { fmtDate, semaforoOf } from "../format";
import { EmptyState, ErrorBox, Loading, PageHeader, SemaforoBadge, LinkButton, cx, useAsync } from "../ui";

export function AgentReports() {
  const { areaId, agentId } = useParams();
  const aid = Number(areaId);
  const gid = Number(agentId);
  const cat = useCatalog();
  const agent = cat.agents.find((a) => a.id === gid);
  const st = useAsync(() => api.reports(gid), [gid]);
  const crumbs = [
    { label: "Áreas", to: "/app" },
    ...areaPath(cat.areas, aid).map((a) => ({ label: a.name, to: `/app/areas/${a.id}` })),
    { label: agent?.name ?? "Agente" },
  ];
  const [latest, ...older] = st.data ?? [];

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={agent?.name ?? "Relatórios"}
        lead="Relatórios publicados para este agente. Eles são autodeclarados pelo time responsável."
      />
      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <EmptyState title="Nenhum relatório publicado ainda.">
          Quando o time publicar o primeiro relatório deste agente, ele aparece aqui.
        </EmptyState>
      )}

      {latest && (
        <section aria-labelledby="recente" className="mb-12">
          <h2 id="recente" className="display mb-4 text-xl">
            Relatório mais recente
          </h2>
          <div className="brutal shadow-hard bg-paper">
            <div className={cx("h-4 border-b-[3px] border-ink", semaforoOf(latest.status_semaforo).bg)} aria-hidden="true" />
            <div className="grid grid-cols-12 items-center gap-6 p-6">
              <div className="col-span-12 flex flex-col items-start gap-2 md:col-span-4">
                <SemaforoBadge value={latest.status_semaforo} size="lg" />
                <p className="display text-xl">Versão {latest.seq}</p>
              </div>
              <dl className="col-span-12 m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 md:col-span-5">
                <dt className="font-bold">Gerado em</dt>
                <dd className="m-0">{fmtDate(latest.generated_at)}</dd>
                <dt className="font-bold">Publicado em</dt>
                <dd className="m-0">{fmtDate(latest.published_at)}</dd>
              </dl>
              <div className="col-span-12 md:col-span-3 md:justify-self-end">
                <LinkButton to={`/app/relatorios/${latest.id}`} variant="primary">
                  Abrir relatório
                </LinkButton>
              </div>
            </div>
          </div>
        </section>
      )}

      {older.length > 0 && (
        <section aria-labelledby="anteriores">
          <h2 id="anteriores" className="display mb-4 text-xl">
            Versões anteriores
          </h2>
          <div className="brutal overflow-x-auto">
            <table className="data-table min-w-[36rem]">
              <caption className="sr-only">Versões anteriores do relatório</caption>
              <thead>
                <tr>
                  <th scope="col">Versão</th>
                  <th scope="col">Semáforo</th>
                  <th scope="col">Gerado em</th>
                  <th scope="col">Publicado em</th>
                  <th scope="col">
                    <span className="sr-only">Ação</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {older.map((r) => (
                  <tr key={r.id}>
                    <td className="font-bold">Versão {r.seq}</td>
                    <td>
                      <SemaforoBadge value={r.status_semaforo} />
                    </td>
                    <td>{fmtDate(r.generated_at)}</td>
                    <td>{fmtDate(r.published_at)}</td>
                    <td className="text-right">
                      <Link to={`/app/relatorios/${r.id}`} className="font-bold">
                        Abrir
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
