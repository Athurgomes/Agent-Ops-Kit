import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { AsciiSounding, AsciiWaves } from "../AsciiArt";
import { areaPath, useCatalog } from "../auth";
import { copy } from "../copy";
import { fmtDate } from "../format";
import { ErrorBox, LinkButton, PageHeader, SemaforoBadge, SignatureBadge, Tag, VerificationBadge, useAsync } from "../ui";

export function AgentReports() {
  const { areaId, agentId } = useParams();
  const aid = Number(areaId);
  const gid = Number(agentId);
  const cat = useCatalog();
  const agent = cat.agents.find((a) => a.id === gid);
  const st = useAsync(() => api.reports(gid), [gid]);

  useEffect(() => {
    document.title = `${copy.agentReports.pageTitle(agent?.name)} · ${copy.brand.full}`;
  }, [agent?.name]);

  const crumbs = [
    { label: copy.areas.crumbRoot, to: "/app" },
    ...areaPath(cat.areas, aid).map((a) => ({ label: a.name, to: `/app/areas/${a.id}` })),
    { label: agent?.name ?? copy.agentReports.crumbFallback },
  ];
  const reports = st.data ?? [];
  const latest = reports[0];

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={agent?.name ?? copy.agentReports.titleFallback}
        lead={copy.agentReports.lead}
        stamp={copy.agentReports.stamp}
      >
        {agent?.slug && <Tag>{agent.slug}</Tag>}
      </PageHeader>

      {st.loading && (
        <div role="status" aria-live="polite" className="border border-ink bg-paper">
          <span className="sr-only">{copy.agentReports.loadingLabel}</span>
          <div className="flex items-center justify-between border-b border-line bg-surface px-5 py-3">
            <span className="eyebrow">{copy.agentReports.loadingCaption}</span>
            <span className="font-mono text-xs text-subtle">···</span>
          </div>
          <AsciiWaves className="h-20 border-b border-line" />
          <div className="flex animate-pulse flex-col gap-3 p-6">
            <div className="h-6 w-1/3 border border-line bg-surface" />
            <div className="h-14 w-full border border-line bg-surface" />
            <div className="h-14 w-full border border-line bg-surface" />
          </div>
        </div>
      )}

      {st.error && <ErrorBox>{st.error}</ErrorBox>}

      {st.data && st.data.length === 0 && (
        <section className="grid grid-cols-1 border border-ink bg-surface md:grid-cols-[1.35fr_1fr]">
          <div className="flex flex-col items-start justify-center gap-3 p-8 lg:p-10">
            <Tag>{copy.agentReports.emptyTag}</Tag>
            <h2 className="heading text-2xl lg:text-3xl">{copy.agentReports.emptyTitle}</h2>
            <p className="max-w-lg text-subtle">{copy.agentReports.emptyBody}</p>
          </div>
          <div className="flex flex-col justify-between border-t border-ink/25 bg-surface md:border-l md:border-t-0">
            <AsciiSounding className="h-44" />
            <p className="border-t border-line px-4 py-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">
              {copy.agentReports.emptyArtCaption}
            </p>
          </div>
        </section>
      )}

      {latest && (
        <section aria-labelledby="latest" className="mb-12">
          <div className="border border-ink bg-paper">
            <div className="ruler-x" aria-hidden="true" />
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-6 py-3">
              <div className="flex flex-wrap items-center gap-3">
                <h2 id="latest" className="eyebrow text-ink">
                  {copy.agentReports.latestEyebrow}
                </h2>
                <span className="inline-block border border-ink bg-ink px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-paper">
                  {copy.agentReports.latestBadge}
                </span>
              </div>
              <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
                {copy.agentReports.versionRef(latest.seq)}
              </span>
            </div>

            <div className="grid grid-cols-12 items-end gap-6 p-6 lg:p-8">
              <div className="col-span-12 flex flex-col items-start gap-4 md:col-span-5">
                <p className="heading text-4xl lg:text-5xl">{copy.agentReports.latestVersion(latest.seq)}</p>
                <SemaforoBadge value={latest.status_semaforo} size="lg" />
                <p className="text-sm text-subtle">{copy.agentReports.latestSemaforoNote}</p>
                <div className="flex flex-wrap gap-2">
                  <SignatureBadge signed={latest.signed} fingerprint={latest.key_fingerprint} />
                  <VerificationBadge verified={latest.verified} status={latest.verification_status} />
                </div>
              </div>

              <dl className="col-span-12 m-0 grid grid-cols-1 gap-4 border-t border-line pt-4 md:col-span-4 md:border-l md:border-t-0 md:pl-6 md:pt-0">
                <div>
                  <dt className="eyebrow">{copy.agentReports.generatedAt}</dt>
                  <dd className="mt-1 font-mono text-sm font-semibold tabular-nums text-ink">
                    {fmtDate(latest.generated_at)}
                  </dd>
                </div>
                <div className="border-t border-line pt-3">
                  <dt className="eyebrow">{copy.agentReports.publishedAt}</dt>
                  <dd className="mt-1 font-mono text-sm font-semibold tabular-nums text-ink">
                    {fmtDate(latest.published_at)}
                  </dd>
                </div>
              </dl>

              <div className="col-span-12 md:col-span-3 md:justify-self-end">
                <LinkButton to={`/app/reports/${latest.id}`} variant="primary" className="w-full md:w-auto">
                  {copy.agentReports.openReport}
                </LinkButton>
              </div>
            </div>
          </div>
        </section>
      )}

      {reports.length > 0 && (
        <section aria-labelledby="history">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="history" className="eyebrow text-ink">
              {copy.agentReports.historyHeading}
            </h2>
            <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
              {copy.agentReports.historyCount(reports.length)}
            </span>
          </div>

          <div className="overflow-x-auto border border-ink bg-paper">
            <table className="data-table min-w-[44rem]">
              <caption className="sr-only">{copy.agentReports.historyCaption}</caption>
              <thead>
                <tr>
                  <th scope="col">{copy.agentReports.columns.version}</th>
                  <th scope="col">{copy.agentReports.columns.semaforo}</th>
                  <th scope="col">{copy.agentReports.columns.publishedAt}</th>
                  <th scope="col">{copy.agentReports.columns.summary}</th>
                  <th scope="col" className="text-right">
                    {copy.agentReports.columns.action}
                  </th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r, idx) => (
                  <tr key={r.id} className="hover:bg-surface">
                    <th scope="row" className="whitespace-nowrap">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <Link
                          to={`/app/reports/${r.id}`}
                          className="font-display text-lg font-extrabold text-ink no-underline hover:text-accent"
                        >
                          {copy.agentReports.latestVersion(r.seq)}
                        </Link>
                        {idx === 0 && (
                          <span className="inline-block border border-ink bg-ink px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-paper">
                            {copy.agentReports.latestBadge}
                          </span>
                        )}
                      </div>
                    </th>
                    <td className="whitespace-nowrap">
                      <SemaforoBadge value={r.status_semaforo} />
                    </td>
                    <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">
                      {fmtDate(r.published_at)}
                    </td>
                    <td>
                      <p className="font-mono text-xs tabular-nums text-ink">
                        {copy.agentReports.rowGeneratedPrefix}
                        {fmtDate(r.generated_at)}
                      </p>
                      <p className="mt-1 text-sm text-subtle">{copy.agentReports.rowDetailsHint}</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <SignatureBadge signed={r.signed} fingerprint={r.key_fingerprint} />
                        <VerificationBadge verified={r.verified} status={r.verification_status} />
                      </div>
                    </td>
                    <td className="whitespace-nowrap text-right">
                      <Link
                        to={`/app/reports/${r.id}`}
                        className="link font-mono text-xs uppercase tracking-[0.05em]"
                      >
                        {copy.agentReports.openLink}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-6 border border-ink/30 border-l-4 border-l-accent bg-surface px-5 py-4 text-sm text-ink">
            {copy.agentReports.honestyStrip}
          </p>
        </section>
      )}
    </>
  );
}
