import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Format, ReportDetail } from "../api";
import { areaPath, useCatalog } from "../auth";
import { fmtDateLong, fmtNum, fmtPct, fmtSigned, LIMITS_TEXT, RULE_TEXT, SELF_DECLARED_TEXT } from "../format";
import { Button, Card, ErrorBox, Loading, PageHeader, SemaforoBadge, useAsync } from "../ui";

const FORMATS: { f: Format; label: string }[] = [
  { f: "md", label: "Baixar MD" },
  { f: "html", label: "Baixar HTML" },
  { f: "json", label: "Baixar JSON" },
];

function DownloadButtons({ r }: { r: ReportDetail }) {
  const [busy, setBusy] = useState<Format | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function go(f: Format) {
    setBusy(f);
    setMsg(null);
    try {
      await api.download(r, f);
      setMsg({ ok: true, text: `Download de ${f.toUpperCase()} iniciado e registrado no seu histórico.` });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Erro ao baixar." });
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="flex flex-col gap-4">
      {FORMATS.map(({ f, label }) => (
        <Button key={f} variant={f === "html" ? "dark" : "secondary"} disabled={busy !== null} onClick={() => go(f)}>
          {busy === f ? "Baixando…" : label}
        </Button>
      ))}
      <div role="status" aria-live="polite">
        {msg && (msg.ok ? <p className="text-sm font-semibold">{msg.text}</p> : <ErrorBox>{msg.text}</ErrorBox>)}
      </div>
      <p className="text-sm">
        Cada download fica registrado em{" "}
        <Link to="/app/downloads" className="font-bold">
          Meus downloads
        </Link>
        .
      </p>
    </div>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <tr>
      <th scope="row" className="w-48">
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
  const ci = (lo?: number, hi?: number, f = fmtPct) => `IC 95%: ${f(lo)} a ${f(hi)}`;
  const attacks = (x: typeof rt.asr_baseline, label: string) =>
    x && x.n != null
      ? `${x.successes} de ${x.n} ataques tiveram sucesso ${label} (${fmtPct(x.asr)}; ${ci(x.ci95_low, x.ci95_high)}).`
      : "não informado";

  return (
    <div className="brutal overflow-x-auto">
      <table className="data-table">
        <caption className="sr-only">Resumo do relatório</caption>
        <tbody>
          <Row k="Qualidade (eval)">
            {ev.n_cases != null
              ? `Média de ${fmtNum(ev.mean_candidate)} na variante ${ev.candidate} contra ${fmtNum(ev.mean_baseline)} na ${ev.baseline}, em ${ev.n_cases} casos. Diferença ${fmtSigned(ev.mean_diff)} (${ci(ev.ci95_low, ev.ci95_high, fmtSigned)}; p = ${fmtNum(ev.p_value)}).`
              : "não informado"}
          </Row>
          <Row k="Red team">
            <p>{attacks(rt.asr_baseline, "sem guardrails")}</p>
            <p className="mt-2">{attacks(rt.asr_guardrails, "com guardrails")}</p>
          </Row>
          <Row k="Falsos positivos">
            {fpd || fpb ? (
              <>
                {fpd && (
                  <p>
                    Conjunto do dataset: {fpd.blocked} de {fpd.n} perguntas legítimas bloqueadas.
                  </p>
                )}
                {fpb && (
                  <p className="mt-2">
                    Perguntas benignas extras: {fpb.blocked} de {fpb.n} bloqueadas.
                  </p>
                )}
              </>
            ) : (
              "não informado"
            )}
          </Row>
          <Row k="Auditoria">
            {r.audit_verify_ok == null
              ? "Nenhum log de auditoria foi informado neste relatório."
              : r.audit_verify_ok
                ? "Cadeia de auditoria verificada."
                : "Cadeia de auditoria inválida."}
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
        { label: "Áreas", to: "/app" },
        ...areaPath(cat.areas, r.area_id).map((a) => ({ label: a.name, to: `/app/areas/${a.id}` })),
        { label: r.agent_name, to: `/app/areas/${r.area_id}/agentes/${r.agent_id}` },
        { label: `Versão ${r.seq}` },
      ]
    : [{ label: "Áreas", to: "/app" }, { label: "Relatório" }];
  const triggered = r?.summary.semaphore?.triggered ?? [];

  return (
    <>
      <PageHeader crumbs={crumbs} title={r ? `${r.agent_name} · versão ${r.seq}` : "Relatório"} />
      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {r && (
        <div className="grid grid-cols-12 gap-x-0 gap-y-12 lg:gap-x-12">
          <aside className="order-first col-span-12 min-w-0 lg:order-last lg:col-span-4">
            <div className="flex flex-col gap-6 lg:sticky lg:top-12">
              <Card shadow className="flex flex-col gap-6">
                <SemaforoBadge value={r.status_semaforo} size="lg" />
                <dl className="m-0 grid grid-cols-1 gap-4 text-sm">
                  <div>
                    <dt className="font-bold">Gerado em</dt>
                    <dd className="m-0">{fmtDateLong(r.generated_at)}</dd>
                  </div>
                  <div>
                    <dt className="font-bold">Publicado em</dt>
                    <dd className="m-0">{fmtDateLong(r.published_at)}</dd>
                  </div>
                  <div>
                    <dt className="font-bold">Modelo</dt>
                    <dd className="m-0">{r.model ?? "não informado"}</dd>
                  </div>
                  <div>
                    <dt className="font-bold">Casos de avaliação</dt>
                    <dd className="m-0">{r.n_cases ?? "não informado"}</dd>
                  </div>
                  <div>
                    <dt className="font-bold">Semente</dt>
                    <dd className="m-0">{r.seed ?? "não informada"}</dd>
                  </div>
                  <div>
                    <dt className="font-bold">SHA-256 do relatório</dt>
                    <dd className="m-0 break-all font-mono text-sm">{r.sha256}</dd>
                  </div>
                </dl>
              </Card>
              <Card tone="muted">
                <h2 className="display mb-4 text-lg">Baixar</h2>
                <DownloadButtons r={r} />
              </Card>
            </div>
          </aside>

          <div className="col-span-12 flex min-w-0 flex-col gap-12 lg:col-span-8">
            <div className="brutal bg-yellow p-6">
              <p className="text-lg font-extrabold leading-snug">{LIMITS_TEXT}</p>
              <p className="mt-4 text-sm">{SELF_DECLARED_TEXT}</p>
            </div>

            <section aria-labelledby="regra" className="flex flex-col gap-4">
              <h2 id="regra" className="display text-2xl">
                Por que este semáforo
              </h2>
              <p>
                Regras provisórias (versão {r.summary.semaphore?.rules_version ?? "não informada"}):
                vermelho se o gate de regressão disparar ou a auditoria informada for inválida; amarelo
                se houver ataque bem-sucedido com guardrails, falso positivo, queda não significativa ou
                ausência de auditoria; verde se nada disso ocorrer.
              </p>
              {triggered.length > 0 ? (
                <ul className="m-0 list-disc space-y-1 pl-6">
                  {triggered.map((t) => (
                    <li key={t}>{RULE_TEXT[t] ?? t}</li>
                  ))}
                </ul>
              ) : (
                <p>Nenhuma regra de alerta disparou neste teste.</p>
              )}
            </section>

            <section aria-labelledby="resumo" className="flex flex-col gap-4">
              <h2 id="resumo" className="display text-2xl">
                Resumo
              </h2>
              <Summary r={r} />
            </section>

            <section aria-labelledby="ressalvas">
              <Card tone="pink" className="flex flex-col gap-4">
                <h2 id="ressalvas" className="display text-2xl">
                  Ressalvas
                </h2>
                {r.limitations.length > 0 ? (
                  <ul className="m-0 list-disc space-y-2 pl-6">
                    {r.limitations.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                ) : (
                  <p>A lista de ressalvas não está disponível aqui; consulte o relatório baixado.</p>
                )}
              </Card>
            </section>
          </div>
        </div>
      )}
    </>
  );
}
