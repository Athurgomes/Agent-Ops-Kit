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
      setError(e instanceof Error ? e.message : "Error.");
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
        crumbs={[{ label: "Downloads" }, { label: admin ? "All downloads" : "My downloads" }]}
        title={admin ? "All downloads" : "My downloads"}
        lead={
          admin
            ? "Every download in the organization, with the email of who downloaded it. This log exists for traceability and should be handled with care (personal data). Dates use your browser's time zone."
            : "The reports you downloaded, and when. Only you and your organization's admins can see this list. Dates use your browser's time zone."
        }
      />

      <form
        aria-label="Filters"
        className="mb-6 grid grid-cols-1 gap-4 box p-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto] lg:items-end"
        onSubmit={(e) => e.preventDefault()}
      >
        <Select
          label="Area"
          id="f-area"
          value={area}
          onChange={(e) => {
            setArea(e.target.value);
            setAgent("");
          }}
        >
          <option value="">All areas</option>
          {cat.areas.map((a) => (
            <option key={a.id} value={a.id}>
              {"— ".repeat(a.depth)}
              {a.name}
            </option>
          ))}
        </Select>
        <Select label="Agent" id="f-agent" value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="">All agents</option>
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
          Clear filters
        </Button>
      </form>

      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && rows.length === 0 && <Loading />}
      {!loading && !error && rows.length === 0 && (
        <EmptyState title={filtered ? "No downloads match these filters." : "No downloads yet."}>
          {filtered
            ? "Try clearing the filters."
            : "When a report is downloaded, it shows up here with the date and time."}
        </EmptyState>
      )}

      {rows.length > 0 && (
        <div className="box max-h-[70vh] overflow-auto">
          <table className="data-table min-w-[48rem]">
            <caption className="sr-only">Download history</caption>
            <thead>
              <tr>
                {admin && <th scope="col">Email</th>}
                <th scope="col">Agent</th>
                <th scope="col">Area</th>
                <th scope="col">Format</th>
                <th scope="col">Downloaded at</th>
                <th scope="col">Report generated at</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id}>
                  {admin && <td className="whitespace-nowrap">{d.user_email}</td>}
                  <td className="min-w-[13rem]">
                    <Link to={`/app/reports/${d.report_id}`} className="font-bold">
                      {d.agent_name}
                    </Link>
                    <span className="block text-sm">version {d.seq}</span>
                  </td>
                  <td>{d.area_name}</td>
                  <td>
                    <Tag>{d.format.toUpperCase()}</Tag>
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
            {loading ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </>
  );
}
