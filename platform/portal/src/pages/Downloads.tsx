import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { DownloadItem } from "../api";
import { useCatalog } from "../auth";
import { fmtDate } from "../format";
import { Button, Card, ErrorBox, Loading, Select, Tag, Title } from "../ui";

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

  return (
    <div className="flex flex-col gap-6">
      <Title>{admin ? "Todos os downloads" : "Meus downloads"}</Title>
      <p className="max-w-3xl font-medium">
        {admin
          ? "Todos os downloads da organização, com o e-mail de quem baixou. Este registro existe para rastreio e deve ser tratado com cuidado (LGPD)."
          : "Seus downloads. Ninguém além de você (e dos administradores da organização) vê esta lista."}{" "}
        Datas no fuso do seu navegador.
      </p>

      <Card tone="pink">
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()}>
          <Select
            label="Área"
            id="f-area"
            value={area}
            onChange={(e) => {
              setArea(e.target.value);
              setAgent("");
            }}
          >
            <option value="">Todas</option>
            {cat.areas.map((a) => (
              <option key={a.id} value={a.id}>
                {"— ".repeat(a.depth)}
                {a.name}
              </option>
            ))}
          </Select>
          <Select label="Agente" id="f-agent" value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">Todos</option>
            {agentOptions.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </form>
      </Card>

      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && rows.length === 0 && <Loading />}
      {!loading && !error && rows.length === 0 && (
        <Card>
          <p className="font-bold">Nenhum download encontrado.</p>
        </Card>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse">
            <caption className="sr-only">Histórico de downloads</caption>
            <thead>
              <tr className="bg-yellow">
                {admin && <th scope="col" className="brutal p-2 text-left uppercase">E-mail</th>}
                <th scope="col" className="brutal p-2 text-left uppercase">Agente</th>
                <th scope="col" className="brutal p-2 text-left uppercase">Área</th>
                <th scope="col" className="brutal p-2 text-left uppercase">Formato</th>
                <th scope="col" className="brutal p-2 text-left uppercase">Baixado em</th>
                <th scope="col" className="brutal p-2 text-left uppercase">Relatório gerado em</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id} className="align-top">
                  {admin && <td className="brutal break-all p-2">{d.user_email}</td>}
                  <td className="brutal p-2">
                    <Link to={`/app/relatorios/${d.report_id}`} className="font-bold underline">
                      {d.agent_name}
                    </Link>{" "}
                    <span className="text-sm">(versão {d.seq})</span>
                  </td>
                  <td className="brutal p-2">{d.area_name}</td>
                  <td className="brutal p-2">
                    <Tag tone="mint">{d.format}</Tag>
                  </td>
                  <td className="brutal p-2">{fmtDate(d.downloaded_at)}</td>
                  <td className="brutal p-2">{fmtDate(d.generated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {more && (
        <div>
          <Button tone="yellow" disabled={loading} onClick={() => load(rows.length)}>
            {loading ? "Carregando…" : "Carregar mais"}
          </Button>
        </div>
      )}
    </div>
  );
}
