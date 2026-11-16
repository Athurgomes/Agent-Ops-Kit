import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { ReportItem } from "../api";
import { areaPath, useCatalog } from "../auth";
import { fmtDate } from "../format";
import { Breadcrumbs, Card, ErrorBox, Loading, Semaforo, Tag, Title, useAsync } from "../ui";

function Dates({ r }: { r: ReportItem }) {
  return (
    <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      <dt className="font-black uppercase">Gerado em</dt>
      <dd className="m-0">{fmtDate(r.generated_at)}</dd>
      <dt className="font-black uppercase">Publicado em</dt>
      <dd className="m-0">{fmtDate(r.published_at)}</dd>
    </dl>
  );
}

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
    <div className="flex flex-col gap-6">
      <Breadcrumbs items={crumbs} />
      <Title>{agent?.name ?? "Relatórios"}</Title>
      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <Card>
          <p className="font-bold">Este agente ainda não tem relatório publicado.</p>
        </Card>
      )}
      {latest && (
        <section aria-labelledby="recente">
          <Card tone="yellow">
            <div className="flex flex-wrap items-center gap-3">
              <Tag tone="orange">Mais recente</Tag>
              <Semaforo value={latest.status_semaforo} big />
            </div>
            <Title as="h2" className="my-4">
              <span id="recente">Versão {latest.seq}</span>
            </Title>
            <Dates r={latest} />
            <Link
              to={`/app/relatorios/${latest.id}`}
              className="brutal brutal-shadow press mt-5 inline-block bg-orange px-5 py-3 font-display font-black uppercase text-ink no-underline"
            >
              Abrir relatório
            </Link>
          </Card>
        </section>
      )}
      {older.length > 0 && (
        <section aria-labelledby="anteriores">
          <Title as="h2" className="mb-4">
            <span id="anteriores">Versões anteriores</span>
          </Title>
          <ul className="m-0 flex list-none flex-col gap-4 p-0">
            {older.map((r) => (
              <li key={r.id}>
                <Card className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-3">
                      <span className="title text-xl">Versão {r.seq}</span>
                      <Semaforo value={r.status_semaforo} />
                    </div>
                    <Dates r={r} />
                  </div>
                  <Link to={`/app/relatorios/${r.id}`} className="font-black uppercase underline">
                    Abrir relatório →
                  </Link>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
