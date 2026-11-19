import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { DownloadItem } from "../api";
import { AsciiSounding, AsciiWaves } from "../AsciiArt";
import { useCatalog } from "../auth";
import { copy } from "../copy";
import { fmtApiError, fmtDate, NOT_AVAILABLE } from "../format";
import { Button, ErrorBox, PageHeader, Select, Tag } from "../ui";

const PAGE = 50;

export function Downloads({ admin = false }: { admin?: boolean }) {
  const cat = useCatalog();
  const [area, setArea] = useState("");
  const [agent, setAgent] = useState("");
  const [rows, setRows] = useState<DownloadItem[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = `${admin ? copy.downloads.pageTitleAdmin : copy.downloads.pageTitleUser} · ${copy.brand.full}`;
  }, [admin]);

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
      setError(fmtApiError(e));
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
        crumbs={[
          { label: copy.downloads.crumbGroup },
          { label: admin ? copy.downloads.titleAdmin : copy.downloads.titleUser },
        ]}
        title={admin ? copy.downloads.titleAdmin : copy.downloads.titleUser}
        lead={admin ? copy.downloads.leadAdmin : copy.downloads.leadUser}
        stamp={admin ? copy.downloads.stampAdmin : copy.downloads.stampUser}
      />

      <form
        aria-label={copy.downloads.filtersAria}
        className="mb-8 border border-ink bg-surface p-5"
        onSubmit={(e) => e.preventDefault()}
      >
        <p className="eyebrow mb-4 text-ink">{copy.downloads.filtersHeading}</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
          <Select
            label={copy.downloads.areaLabel}
            id="f-area"
            value={area}
            onChange={(e) => {
              setArea(e.target.value);
              setAgent("");
            }}
          >
            <option value="">{copy.downloads.allAreas}</option>
            {cat.areas.map((a) => (
              <option key={a.id} value={a.id}>
                {"— ".repeat(a.depth)}
                {a.name}
              </option>
            ))}
          </Select>
          <Select label={copy.downloads.agentLabel} id="f-agent" value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">{copy.downloads.allAgents}</option>
            {agentOptions.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
          <Button
            size="md"
            className="h-[51px]"
            disabled={!filtered}
            onClick={() => {
              setArea("");
              setAgent("");
            }}
          >
            {copy.downloads.clearFilters}
          </Button>
        </div>
      </form>

      {error && <ErrorBox>{error}</ErrorBox>}

      {loading && rows.length === 0 && (
        <div role="status" aria-live="polite" className="border border-ink bg-paper">
          <span className="sr-only">{copy.downloads.loadingLabel}</span>
          <div className="flex items-center justify-between border-b border-line bg-surface px-5 py-3">
            <span className="eyebrow">{copy.downloads.loadingCaption}</span>
            <span className="font-mono text-xs text-subtle">···</span>
          </div>
          <AsciiWaves className="h-20 border-b border-line" />
          <div className="flex animate-pulse flex-col gap-3 p-6">
            <div className="h-10 w-full border border-line bg-surface" />
            <div className="h-10 w-full border border-line bg-surface" />
            <div className="h-10 w-full border border-line bg-surface" />
          </div>
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <section className="grid grid-cols-1 border border-ink bg-surface md:grid-cols-[1.35fr_1fr]">
          <div className="flex flex-col items-start justify-center gap-3 p-8 lg:p-10">
            <Tag>{copy.downloads.emptyTag}</Tag>
            <h2 className="heading text-2xl lg:text-3xl">
              {filtered ? copy.downloads.emptyFilteredTitle : copy.downloads.emptyTitle}
            </h2>
            <p className="max-w-lg text-subtle">
              {filtered ? copy.downloads.emptyFilteredBody : copy.downloads.emptyBody}
            </p>
          </div>
          <div className="flex flex-col justify-between border-t border-ink/25 bg-surface md:border-l md:border-t-0">
            <AsciiSounding className="h-40" />
            <p className="border-t border-line px-4 py-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">
              {copy.downloads.emptyArtCaption}
            </p>
          </div>
        </section>
      )}

      {rows.length > 0 && (
        <section aria-labelledby="downloads-log">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="downloads-log" className="eyebrow text-ink">
              {copy.downloads.listHeading}
            </h2>
            <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
              {copy.downloads.countLabel(rows.length, more)}
            </span>
          </div>

          <div className="box max-h-[70vh] overflow-auto">
            <table className="data-table min-w-[48rem]">
              <caption className="sr-only">{copy.downloads.tableCaption}</caption>
              <thead>
                <tr>
                  {admin && <th scope="col">{copy.downloads.columns.user}</th>}
                  <th scope="col">{copy.downloads.columns.agent}</th>
                  <th scope="col">{copy.downloads.columns.area}</th>
                  <th scope="col">{copy.downloads.columns.format}</th>
                  <th scope="col">{copy.downloads.columns.downloadedAt}</th>
                  <th scope="col">{copy.downloads.columns.generatedAt}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id} className="hover:bg-surface">
                    {admin && (
                      <td className="whitespace-nowrap font-mono text-xs text-ink">
                        {d.user_email ?? NOT_AVAILABLE}
                      </td>
                    )}
                    <th scope="row" className="min-w-[13rem]">
                      <Link
                        to={`/app/reports/${d.report_id}`}
                        className="font-display text-lg font-extrabold text-ink no-underline hover:text-accent"
                      >
                        {d.agent_name}
                      </Link>
                      <span className="mt-0.5 block font-mono text-xs font-normal text-subtle">
                        {copy.downloads.versionLabel(d.seq)}
                      </span>
                    </th>
                    <td className="text-sm text-ink">{d.area_name}</td>
                    <td>
                      <Tag>{d.format.toUpperCase()}</Tag>
                    </td>
                    <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">
                      {fmtDate(d.downloaded_at)}
                    </td>
                    <td className="whitespace-nowrap font-mono text-xs tabular-nums text-subtle">
                      {fmtDate(d.generated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {more && (
        <div className="mt-6">
          <Button disabled={loading} onClick={() => load(rows.length)}>
            {loading ? copy.downloads.loadingMore : copy.downloads.loadMore}
          </Button>
        </div>
      )}
    </>
  );
}
