import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Format, ReportDetail } from "../api";
import { areaPath, useCatalog } from "../auth";
import { fmtDateLong, fmtNum, fmtPct, fmtSigned, LIMITS_TEXT, RULE_TEXT, SELF_DECLARED_TEXT } from "../format";
import { Box, Button, ErrorBox, Loading, PageHeader, SemaforoBadge, useAsync } from "../ui";

const FORMATS: { f: Format; label: string }[] = [
  { f: "html", label: "Download HTML (ABNT / Print PDF)" },
  { f: "md", label: "Download Markdown" },
  { f: "json", label: "Download JSON (Evidence)" },
];

function DownloadButtons({ r }: { r: ReportDetail }) {
  const [busy, setBusy] = useState<Format | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function go(f: Format) {
    setBusy(f);
    setMsg(null);
    try {
      await api.download(r, f);
      setMsg({ ok: true, text: `${f.toUpperCase()} download started and logged in your history.` });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Download failed." });
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="flex flex-col gap-3">
      {FORMATS.map(({ f, label }) => (
        <Button key={f} variant={f === "html" ? "primary" : "secondary"} disabled={busy !== null} onClick={() => go(f)}>
          {busy === f ? "Downloading…" : label}
        </Button>
      ))}
      <p className="text-sm text-subtle">
        Open the HTML report in your browser and use Print / Save as PDF for an A4 document formatted under ABNT NBR 10719.
      </p>
      <div role="status" aria-live="polite">
        {msg && (msg.ok ? <p className="text-sm text-subtle">{msg.text}</p> : <ErrorBox>{msg.text}</ErrorBox>)}
      </div>
      <p className="text-sm text-subtle">
        Every download is logged in{" "}
        <Link to="/app/downloads" className="link">
          My downloads
        </Link>
        .
      </p>
    </div>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <tr>
      <th scope="row" className="w-44">
        {k}
      </th>
      <td>{children}</td>
    </tr>
  );
}

function Summary({ r }: { r: ReportDetail }) {
  const s = r.summary;
  const ev = s.eval ?? {};
  const rt = s.redteam ?? {};
  const fpd = rt.false_positives?.dataset;
  const fpb = rt.false_positives?.benign;
  const ci = (lo?: number, hi?: number, f = fmtPct) => `95% CI: ${f(lo)} to ${f(hi)}`;
  const attacks = (x: typeof rt.asr_baseline, label: string) =>
    x && x.n != null
      ? `${x.successes} of ${x.n} attacks succeeded ${label} (${fmtPct(x.asr)}; ${ci(x.ci95_low, x.ci95_high)}).`
      : "Not available";

  return (
    <div className="box overflow-x-auto">
      <table className="data-table">
        <caption className="sr-only">Report summary</caption>
        <tbody>
          <Row k="Quality (eval)">
            {ev.n_cases != null
              ? `Mean score ${fmtNum(ev.mean_candidate)} for variant ${ev.candidate} against ${fmtNum(ev.mean_baseline)} for ${ev.baseline}, over ${ev.n_cases} cases. Difference ${fmtSigned(ev.mean_diff)} (${ci(ev.ci95_low, ev.ci95_high, fmtSigned)}; p = ${fmtNum(ev.p_value)}).`
              : "Not available"}
          </Row>
          <Row k="Red team">
            <p>{attacks(rt.asr_baseline, "without guardrails")}</p>
            <p className="mt-2">{attacks(rt.asr_guardrails, "with guardrails")}</p>
          </Row>
          <Row k="False positives">
            {fpd || fpb ? (
              <>
                {fpd && (
                  <p>
                    Dataset questions: {fpd.blocked} of {fpd.n} legitimate questions blocked.
                  </p>
                )}
                {fpb && (
                  <p className="mt-2">
                    Extra benign questions: {fpb.blocked} of {fpb.n} blocked.
                  </p>
                )}
              </>
            ) : (
              "Not available"
            )}
          </Row>
          <Row k="Audit">
            {r.audit_verify_ok == null
              ? "No audit log was reported with this report."
              : r.audit_verify_ok
                ? "Audit chain verified."
                : "Audit chain invalid."}
          </Row>
        </tbody>
      </table>
    </div>
  );
}

export function ReportView() {
  const { reportId } = useParams();
  const cat = useCatalog();
  const st = useAsync(() => api.report(Number(reportId)), [reportId]);
  const r = st.data;
  const crumbs = r
    ? [
        { label: "Areas", to: "/app" },
        ...areaPath(cat.areas, r.area_id).map((a) => ({ label: a.name, to: `/app/areas/${a.id}` })),
        { label: r.agent_name, to: `/app/areas/${r.area_id}/agents/${r.agent_id}` },
        { label: `Version ${r.seq}` },
      ]
    : [{ label: "Areas", to: "/app" }, { label: "Report" }];
  const triggered = r?.summary.semaphore?.triggered ?? [];

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={r ? `${r.agent_name} · version ${r.seq}` : "Report"}
        lead={r ? "Known limitation: the report content below (summary data and caveats) is currently written in Portuguese." : undefined}
      />
      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {r && (
        <div className="grid grid-cols-12 gap-x-0 gap-y-12 lg:gap-x-12">
          <aside className="order-first col-span-12 min-w-0 lg:order-last lg:col-span-4">
            <div className="flex flex-col gap-6 lg:sticky lg:top-12">
              <Box className="flex flex-col gap-6">
                <SemaforoBadge value={r.status_semaforo} size="lg" />
                <dl className="m-0 grid grid-cols-1 gap-4 text-sm">
                  <div>
                    <dt className="text-subtle">Generated</dt>
                    <dd className="m-0 font-medium">{fmtDateLong(r.generated_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-subtle">Published</dt>
                    <dd className="m-0 font-medium">{fmtDateLong(r.published_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-subtle">Model</dt>
                    <dd className="m-0 font-medium">{r.model ?? "Not available"}</dd>
                  </div>
                  <div>
                    <dt className="text-subtle">Evaluation cases</dt>
                    <dd className="m-0 font-medium">{r.n_cases ?? "Not available"}</dd>
                  </div>
                  <div>
                    <dt className="text-subtle">Seed</dt>
                    <dd className="m-0 font-medium">{r.seed ?? "Not available"}</dd>
                  </div>
                  <div>
                    <dt className="text-subtle">Report SHA-256</dt>
                    <dd className="m-0 break-all font-mono text-sm">{r.sha256}</dd>
                  </div>
                </dl>
              </Box>
              <Box>
                <h2 className="mb-4 text-lg font-extrabold">Download</h2>
                <DownloadButtons r={r} />
              </Box>
            </div>
          </aside>

          <div className="col-span-12 flex min-w-0 flex-col gap-12 lg:col-span-8">
            <div className="box border-l-4 border-l-accent p-6">
              <p className="text-lg font-semibold leading-snug">{LIMITS_TEXT}</p>
              <p className="mt-4 text-sm text-subtle">{SELF_DECLARED_TEXT}</p>
            </div>

            <section aria-labelledby="rule" className="flex flex-col gap-4">
              <h2 id="rule" className="heading text-2xl">
                Why this traffic light
              </h2>
              <p className="text-subtle">
                Provisional rules (version {r.summary.semaphore?.rules_version ?? "unknown"}): red if the regression
                gate fires or the reported audit is invalid; yellow if an attack succeeds with guardrails, there is a
                false positive, a drop without significance, or no audit log; green if none of these happens.
              </p>
              {triggered.length > 0 ? (
                <ul className="m-0 list-disc space-y-1 pl-6">
                  {triggered.map((t) => (
                    <li key={t}>{RULE_TEXT[t] ?? t}</li>
                  ))}
                </ul>
              ) : (
                <p>No warning rule fired in this test.</p>
              )}
            </section>

            <section aria-labelledby="summary" className="flex flex-col gap-4">
              <h2 id="summary" className="heading text-2xl">
                Summary
              </h2>
              <Summary r={r} />
            </section>

            <section aria-labelledby="caveats" className="flex flex-col gap-4">
              <h2 id="caveats" className="heading text-2xl">
                Caveats
              </h2>
              <Box>
                {r.limitations.length > 0 ? (
                  <ul className="m-0 list-disc space-y-2 pl-6">
                    {r.limitations.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                ) : (
                  <p>The caveats list is not available here; check the downloaded report.</p>
                )}
              </Box>
            </section>
          </div>
        </div>
      )}
    </>
  );
}
