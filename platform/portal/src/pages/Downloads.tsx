import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { DownloadItem } from "../api";
import { useCatalog } from "../auth";
import { fmtDate } from "../format";
import { Button, EmptyState, ErrorBox, Loading, PageHeader, Select, Tag } from "../ui";

const PAGE = 50;

export function Downloads({ admin = false }: { admin?: boolean }) {
  const cat = useCatalog();
  const [area, setArea] = useState("");
  const [agent, setAgent] = useState("");
  const [rows, setRows] = useState<DownloadItem[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const agentOptions = cat.agents.filter((a) => !area || a.area_id === Number(area));

  async function load(offset: number) {
    setLoading(true);
    setError(null);
    try {
      const page = await api.downloads(admin, {
        area_id: area ? Number(area) : undefined,
        agent_id: agent ? Number(agent) : undefined,
        limit: PAGE,
        offset,
      });
      setRows((prev) => (offset === 0 ? page : [...prev, ...page]));
      setMore(page.length === PAGE);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setRows([]);
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [admin, area, agent]);

  const filtered = area !== "" || agent !== "";

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Downloads" }, { label: admin ? "Todos os downloads" : "Meus downloads" }]}
        title={admin ? "Todos os downloads" : "Meus downloads"}
        lead={
          admin
            ? "Todos os downloads da organização, com o e-mail de quem baixou. Este registro existe para rastreio e deve ser tratado com cuidado (LGPD). Datas no fuso do seu navegador."
            : "Os relatórios que você baixou e quando. Só você e os administradores da organização veem esta lista. Datas no fuso do seu navegador."
        }
      />

      <form
        aria-label="Filtros"
        className="brutal mb-6 grid grid-cols-1 gap-4 bg-muted p-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto] lg:items-end"
        onSubmit={(e) => e.preventDefault()}
      >
        <Select
          label="Área"
          id="f-area"
          value={area}
          onChange={(e) => {
            setArea(e.target.value);
            setAgent("");
          }}
        >
          <option value="">Todas as áreas</option>
          {cat.areas.map((a) => (
            <option key={a.id} value={a.id}>
              {"— ".repeat(a.depth)}
              {a.name}
            </option>
          ))}
        </Select>
        <Select label="Agente" id="f-agent" value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="">Todos os agentes</option>
          {agentOptions.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <Button
          size="sm"
          disabled={!filtered}
          onClick={() => {
            setArea("");
            setAgent("");
          }}
        >
          Limpar filtros
        </Button>
      </form>

      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && rows.length === 0 && <Loading />}
      {!loading && !error && rows.length === 0 && (
        <EmptyState title={filtered ? "Nenhum download com esses filtros." : "Nenhum download ainda."}>
          {filtered
            ? "Tente limpar os filtros."
            : "Quando um relatório for baixado, ele aparece aqui com a data e a hora."}
        </EmptyState>
      )}

      {rows.length > 0 && (
        <div className="brutal max-h-[70vh] overflow-auto">
          <table className="data-table min-w-[48rem]">
            <caption className="sr-only">Histórico de downloads</caption>
            <thead>
              <tr>
                {admin && <th scope="col">E-mail</th>}
                <th scope="col">Agente</th>
                <th scope="col">Área</th>
                <th scope="col">Formato</th>
                <th scope="col">Baixado em</th>
                <th scope="col">Relatório gerado em</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id}>
                  {admin && <td className="whitespace-nowrap">{d.user_email}</td>}
                  <td>
                    <Link to={`/app/relatorios/${d.report_id}`} className="font-bold">
                      {d.agent_name}
                    </Link>
                    <span className="block text-sm">versão {d.seq}</span>
                  </td>
                  <td>{d.area_name}</td>
                  <td>
                    <Tag tone="mint">{d.format.toUpperCase()}</Tag>
                  </td>
                  <td className="whitespace-nowrap">{fmtDate(d.downloaded_at)}</td>
                  <td className="whitespace-nowrap">{fmtDate(d.generated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {more && (
        <div className="mt-6">
          <Button disabled={loading} onClick={() => load(rows.length)}>
            {loading ? "Carregando…" : "Carregar mais"}
          </Button>
        </div>
      )}
    </>
  );
}
