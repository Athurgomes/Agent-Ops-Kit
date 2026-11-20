import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Format, ReportDetail } from "../api";
import { AsciiWaves } from "../AsciiArt";
import { areaPath, useCatalog } from "../auth";
import { copy } from "../copy";
import { CopyButton } from "../dialogs";
import {
  fmtApiError,
  fmtDateLong,
  fmtNum,
  fmtPct,
  fmtSigned,
  LIMITS_TEXT,
  NOT_AVAILABLE,
  RULE_TEXT,
  SELF_DECLARED_TEXT,
} from "../format";
import { Button, ErrorBox, PageHeader, SemaforoBadge, SignatureBadge, useAsync } from "../ui";

const FORMATS: { f: Format; label: string }[] = [
  { f: "html", label: copy.reportView.downloadFormats.html },
  { f: "md", label: copy.reportView.downloadFormats.md },
  { f: "json", label: copy.reportView.downloadFormats.json },
];

function DownloadButtons({ r }: { r: ReportDetail }) {
  const [busy, setBusy] = useState<Format | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function go(f: Format) {
    setBusy(f);
    setMsg(null);
    try {
      await api.download(r, f);
      setMsg({ ok: true, text: copy.reportView.downloadStarted(f.toUpperCase()) });
    } catch (e) {
      setMsg({ ok: false, text: fmtApiError(e) || copy.reportView.downloadFailed });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {FORMATS.map(({ f, label }) => (
        <Button
          key={f}
          variant={f === "html" ? "primary" : "secondary"}
          className="w-full"
          disabled={busy !== null}
          onClick={() => go(f)}
        >
          {busy === f ? copy.reportView.downloading : label}
        </Button>
      ))}
      <p className="mt-1 text-sm text-subtle">{copy.reportView.abntHint}</p>
      <div role="status" aria-live="polite">
        {msg &&
          (msg.ok ? (
            <p className="border border-line bg-surface px-3 py-2 text-sm text-ink">{msg.text}</p>
          ) : (
            <ErrorBox>{msg.text}</ErrorBox>
          ))}
      </div>
      <p className="border-t border-line pt-3 text-sm text-subtle">
        {copy.reportView.downloadLoggedPrefix}
        <Link to="/app/downloads" className="link">
          {copy.reportView.downloadLoggedLink}
        </Link>
        {copy.reportView.downloadLoggedSuffix}
      </p>
    </div>
  );
}

function SummaryRow({ k, children }: { k: string; children: ReactNode }) {
  return (
    <tr>
      <th scope="row" className="w-36 sm:w-48">
        {k}
      </th>
      <td className="min-w-0">{children}</td>
    </tr>
  );
}

function SummaryTable({ r }: { r: ReportDetail }) {
  const s = r.summary;
  const ev = s.eval ?? {};
  const rt = s.redteam ?? {};
  const fpd = rt.false_positives?.dataset;
  const fpb = rt.false_positives?.benign;
  const ci = (lo?: number, hi?: number, f = fmtPct) => copy.reportView.ci95(f(lo), f(hi));
  const attacks = (x: typeof rt.asr_baseline, label: string) =>
    x && x.n != null && x.successes != null
      ? copy.reportView.attackLine({
          successes: x.successes,
          n: x.n,
          label,
          pct: fmtPct(x.asr),
          ci: ci(x.ci95_low, x.ci95_high),
        })
      : NOT_AVAILABLE;

  return (
    <div className="overflow-x-auto border border-ink bg-paper">
      <table className="data-table">
        <caption className="sr-only">{copy.reportView.summaryCaption}</caption>
        <thead>
          <tr>
            <th scope="col">{copy.reportView.summaryCols.block}</th>
            <th scope="col">{copy.reportView.summaryCols.detail}</th>
          </tr>
        </thead>
        <tbody>
          <SummaryRow k={copy.reportView.summaryRows.eval}>
            {ev.n_cases != null ? (
              <>
                <p>
                  {copy.reportView.evalLine({
                    meanCand: fmtNum(ev.mean_candidate),
                    cand: ev.candidate ?? NOT_AVAILABLE,
                    meanBase: fmtNum(ev.mean_baseline),
                    base: ev.baseline ?? NOT_AVAILABLE,
                    nCases: ev.n_cases.toLocaleString("pt-BR"),
                    diff: fmtSigned(ev.mean_diff),
                    ci: ci(ev.ci95_low, ev.ci95_high, fmtSigned),
                    pVal: fmtNum(ev.p_value),
                  })}
                </p>
                {typeof ev.regression === "boolean" && (
                  <p className="mt-2 font-mono text-xs text-subtle">
                    {ev.regression ? copy.reportView.evalRegressionYes : copy.reportView.evalRegressionNo}
                  </p>
                )}
              </>
            ) : (
              NOT_AVAILABLE
            )}
          </SummaryRow>
          <SummaryRow k={copy.reportView.summaryRows.redteam}>
            <p>{attacks(rt.asr_baseline, copy.reportView.attackWithoutGuardrails)}</p>
            <p className="mt-2">{attacks(rt.asr_guardrails, copy.reportView.attackWithGuardrails)}</p>
          </SummaryRow>
          <SummaryRow k={copy.reportView.summaryRows.falsePositives}>
            {fpd || fpb ? (
              <>
                {fpd && fpd.blocked != null && fpd.n != null && (
                  <p>{copy.reportView.fpDatasetLine(fpd.blocked, fpd.n)}</p>
                )}
                {fpb && fpb.blocked != null && fpb.n != null && (
                  <p className="mt-2">{copy.reportView.fpBenignLine(fpb.blocked, fpb.n)}</p>
                )}
              </>
            ) : (
              NOT_AVAILABLE
            )}
          </SummaryRow>
          <SummaryRow k={copy.reportView.summaryRows.audit}>
            {r.audit_verify_ok == null
              ? copy.reportView.auditNone
              : r.audit_verify_ok
                ? copy.reportView.auditOk
                : copy.reportView.auditInvalid}
          </SummaryRow>
        </tbody>
      </table>
    </div>
  );
}

function HashesTable({ r }: { r: ReportDetail }) {
  const anchor = r.audit_anchor ?? r.summary.audit?.anchor ?? null;
  const rows: { label: string; value: string }[] = [{ label: copy.reportView.hashRows.reportJson, value: r.sha256 }];
  if (r.prompt_sha256) rows.push({ label: copy.reportView.hashRows.prompt, value: r.prompt_sha256 });
  if (r.dataset_sha256) rows.push({ label: copy.reportView.hashRows.dataset, value: r.dataset_sha256 });
  if (anchor) rows.push({ label: copy.reportView.hashRows.auditAnchor, value: anchor });

  return (
    <div className="border border-ink bg-paper">
      <div className="divide-y divide-line sm:hidden">
        {rows.map((item) => (
          <div key={item.label} className="flex flex-col gap-2.5 p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="eyebrow text-ink">{item.label}</span>
              <CopyButton text={item.value} />
            </div>
            <p className="break-all border border-line bg-surface px-3 py-2 font-mono text-xs text-ink select-all">
              {item.value}
            </p>
          </div>
        ))}
      </div>

      <div className="hidden overflow-x-auto sm:block">
        <table className="data-table">
          <caption className="sr-only">{copy.reportView.hashesCaption}</caption>
          <thead>
            <tr>
              <th scope="col">{copy.reportView.hashCols.artifact}</th>
              <th scope="col">{copy.reportView.hashCols.digest}</th>
              <th scope="col" className="text-right">
                {copy.reportView.hashCols.action}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.label}>
                <th scope="row" className="whitespace-nowrap font-mono text-xs font-semibold text-ink">
                  {item.label}
                </th>
                <td className="min-w-[10rem] break-all font-mono text-xs text-ink select-all">{item.value}</td>
                <td className="whitespace-nowrap text-right">
                  <CopyButton text={item.value} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ReportView() {
  const { reportId } = useParams();
  const cat = useCatalog();
  const st = useAsync(() => api.report(Number(reportId)), [reportId]);
  const r = st.data;

  useEffect(() => {
    document.title = `${copy.reportView.pageTitle(r?.agent_name, r?.seq)} · ${copy.brand.full}`;
  }, [r?.agent_name, r?.seq]);

  const crumbs = r
    ? [
        { label: copy.areas.crumbRoot, to: "/app" },
        ...areaPath(cat.areas, r.area_id).map((a) => ({ label: a.name, to: `/app/areas/${a.id}` })),
        { label: r.agent_name, to: `/app/areas/${r.area_id}/agents/${r.agent_id}` },
        { label: copy.reportView.versionCrumb(r.seq) },
      ]
    : [{ label: copy.areas.crumbRoot, to: "/app" }, { label: copy.reportView.crumbFallback }];

  const triggered = r?.summary.semaphore?.triggered ?? [];
  const rulesVersion = r?.summary.semaphore?.rules_version ?? copy.reportView.rulesVersionUnknown;
  const modelLabel = r?.model ?? r?.summary.agent?.model ?? NOT_AVAILABLE;
  const promptVersion = r?.summary.agent?.prompt_version;

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={r ? copy.reportView.title(r.agent_name, r.seq) : copy.reportView.titleFallback}
        lead={r ? copy.reportView.lead : undefined}
        stamp={copy.reportView.stamp}
      />

      {st.loading && (
        <div role="status" aria-live="polite" className="border border-ink bg-paper">
          <span className="sr-only">{copy.reportView.loadingLabel}</span>
          <div className="flex items-center justify-between border-b border-line bg-surface px-5 py-3">
            <span className="eyebrow">{copy.reportView.loadingCaption}</span>
            <span className="font-mono text-xs text-subtle">···</span>
          </div>
          <AsciiWaves className="h-20 border-b border-line" />
          <div className="flex animate-pulse flex-col gap-3 p-6">
            <div className="h-8 w-2/5 border border-line bg-surface" />
            <div className="h-24 w-full border border-line bg-surface" />
            <div className="h-32 w-full border border-line bg-surface" />
          </div>
        </div>
      )}

      {st.error && <ErrorBox>{st.error}</ErrorBox>}

      {r && (
        <>
          <section
            aria-labelledby="limits-notice"
            className="mb-10 border border-ink border-l-4 border-l-accent bg-surface"
          >
            <div className="border-b border-line px-6 py-2.5">
              <h2 id="limits-notice" className="eyebrow text-ink">
                {copy.reportView.honestyEyebrow}
              </h2>
            </div>
            <div className="p-6">
              <p className="text-lg font-semibold leading-snug text-ink">{LIMITS_TEXT}</p>
              <p className="mt-3 text-sm text-subtle">{SELF_DECLARED_TEXT}</p>
            </div>
          </section>

          <div className="grid grid-cols-12 gap-x-0 gap-y-10 lg:gap-x-10">
            <aside className="col-span-12 min-w-0 lg:order-last lg:col-span-4">
              <div className="flex flex-col gap-6 lg:sticky lg:top-10">
                <section className="border border-ink bg-paper">
                  <div className="ruler-x" aria-hidden="true" />
                  <div className="flex items-center justify-between border-b border-line bg-surface px-5 py-3">
                    <h2 className="eyebrow text-ink">{copy.reportView.metaEyebrow}</h2>
                    <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
                      {copy.reportView.metaVersionCode(r.seq)}
                    </span>
                  </div>
                  <div className="flex flex-col gap-5 p-5">
                    <div className="flex flex-col items-start gap-2">
                      <SemaforoBadge value={r.status_semaforo} size="lg" />
                      <p className="font-mono text-xs text-subtle">{copy.reportView.metaSemaforoNote}</p>
                    </div>
                    <dl className="m-0 flex flex-col gap-3 text-sm">
                      <div className="border-t border-line pt-3">
                        <dt className="eyebrow">{copy.reportView.meta.agentSlug}</dt>
                        <dd className="mt-1 break-all font-mono text-xs font-semibold text-ink">{r.agent_slug}</dd>
                      </div>
                      <div className="border-t border-line pt-3">
                        <dt className="eyebrow">{copy.reportView.meta.generatedAt}</dt>
                        <dd className="mt-1 font-medium text-ink">{fmtDateLong(r.generated_at)}</dd>
                      </div>
                      <div className="border-t border-line pt-3">
                        <dt className="eyebrow">{copy.reportView.meta.publishedAt}</dt>
                        <dd className="mt-1 font-medium text-ink">{fmtDateLong(r.published_at)}</dd>
                      </div>
                      <div className="border-t border-line pt-3">
                        <dt className="eyebrow">{copy.signature.meta}</dt>
                        <dd className="mt-1">
                          <SignatureBadge signed={r.signed} fingerprint={r.key_fingerprint} />
                        </dd>
                      </div>
                      <div className="border-t border-line pt-3">
                        <dt className="eyebrow">{copy.reportView.meta.model}</dt>
                        <dd className="mt-1 break-words font-mono text-xs font-semibold text-ink">{modelLabel}</dd>
                      </div>
                      {promptVersion && (
                        <div className="border-t border-line pt-3">
                          <dt className="eyebrow">{copy.reportView.meta.promptVersion}</dt>
                          <dd className="mt-1 break-words font-mono text-xs font-semibold text-ink">
                            {promptVersion}
                          </dd>
                        </div>
                      )}
                      <div className="grid grid-cols-2 gap-4 border-t border-line pt-3">
                        <div className="flex flex-col justify-between gap-1">
                          <dt className="eyebrow">{copy.reportView.meta.nCases}</dt>
                          <dd className="font-mono text-sm font-semibold tabular-nums text-ink">
                            {r.n_cases != null ? r.n_cases.toLocaleString("pt-BR") : NOT_AVAILABLE}
                          </dd>
                        </div>
                        <div className="flex flex-col justify-between gap-1">
                          <dt className="eyebrow">{copy.reportView.meta.seed}</dt>
                          <dd className="font-mono text-sm font-semibold tabular-nums text-ink">
                            {r.seed != null ? String(r.seed) : NOT_AVAILABLE}
                          </dd>
                        </div>
                      </div>
                    </dl>
                  </div>
                </section>

                <section aria-labelledby="downloads-box" className="border border-ink bg-paper">
                  <div className="flex items-center justify-between gap-3 border-b border-line bg-surface px-5 py-3">
                    <h2 id="downloads-box" className="eyebrow text-ink">
                      {copy.reportView.downloadsHeading}
                    </h2>
                    <span className="whitespace-nowrap font-mono text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">
                      {copy.reportView.downloadsTag}
                    </span>
                  </div>
                  <div className="p-5">
                    <DownloadButtons r={r} />
                  </div>
                </section>
              </div>
            </aside>

            <div className="col-span-12 flex min-w-0 flex-col gap-10 lg:col-span-8">
              <section aria-labelledby="rule" className="flex flex-col gap-4">
                <div>
                  <p className="eyebrow">{copy.reportView.semaforoEyebrow}</p>
                  <h2 id="rule" className="heading mt-1 text-2xl lg:text-3xl">
                    {copy.reportView.semaforoHeading}
                  </h2>
                </div>
                <div className="flex flex-col gap-5 border border-ink bg-paper p-6">
                  <div className="flex flex-wrap items-center gap-4 border-b border-line pb-4">
                    <SemaforoBadge value={r.status_semaforo} size="lg" />
                    <p className="text-sm text-subtle">{copy.reportView.rulesExplanation(rulesVersion)}</p>
                  </div>
                  <div>
                    <h3 className="eyebrow text-ink">{copy.reportView.triggeredHeading}</h3>
                    {triggered.length > 0 ? (
                      <ul className="m-0 mt-3 list-none divide-y divide-line border border-line p-0">
                        {triggered.map((t, idx) => (
                          <li key={t} className="flex items-start gap-3 px-4 py-3 text-sm text-ink">
                            <span
                              aria-hidden="true"
                              className="font-mono text-xs font-semibold tabular-nums text-subtle"
                            >
                              {String(idx + 1).padStart(2, "0")}
                            </span>
                            <span>{RULE_TEXT[t] ?? t}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-3 border border-line bg-surface px-4 py-3 text-sm text-ink">
                        {copy.reportView.noRuleTriggered}
                      </p>
                    )}
                  </div>
                </div>
              </section>

              <section aria-labelledby="summary" className="flex flex-col gap-4">
                <div>
                  <p className="eyebrow">{copy.reportView.summaryEyebrow}</p>
                  <h2 id="summary" className="heading mt-1 text-2xl lg:text-3xl">
                    {copy.reportView.summaryHeading}
                  </h2>
                </div>
                <SummaryTable r={r} />
              </section>

              <section aria-labelledby="caveats" className="flex flex-col gap-4">
                <div>
                  <p className="eyebrow">{copy.reportView.caveatsEyebrow}</p>
                  <h2 id="caveats" className="heading mt-1 text-2xl lg:text-3xl">
                    {copy.reportView.caveatsHeading}
                  </h2>
                </div>
                <div className="border border-ink bg-paper">
                  {r.limitations.length > 0 ? (
                    <ol className="m-0 list-none divide-y divide-line p-0">
                      {r.limitations.map((l, i) => (
                        <li key={i} className="flex items-start gap-4 px-5 py-4 text-sm text-ink">
                          <span
                            aria-hidden="true"
                            className="shrink-0 font-mono text-xs font-semibold tabular-nums text-subtle"
                          >
                            {String(i + 1).padStart(2, "0")}
                          </span>
                          <span>{l}</span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="p-5 text-sm text-subtle">{copy.reportView.caveatsEmpty}</p>
                  )}
                </div>
              </section>

              <section aria-labelledby="hashes" className="flex flex-col gap-4">
                <div>
                  <p className="eyebrow">{copy.reportView.hashesEyebrow}</p>
                  <h2 id="hashes" className="heading mt-1 text-2xl lg:text-3xl">
                    {copy.reportView.hashesHeading}
                  </h2>
                  <p className="mt-2 text-sm text-subtle">{copy.reportView.hashesLead}</p>
                </div>
                <HashesTable r={r} />
              </section>
            </div>
          </div>
        </>
      )}
    </>
  );
}
