import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Format, ReportDetail } from "../api";
import { areaPath, useCatalog } from "../auth";
import {
  LIMITS_TEXT,
  RULE_TEXT,
  SELF_DECLARED_TEXT,
  fmtDate,
  fmtDateLong,
  fmtNum,
  fmtPct,
  fmtSigned,
} from "../format";
import { Breadcrumbs, Button, Card, ErrorBox, Loading, Semaforo, Title, useAsync } from "../ui";

const FORMATS: { f: Format; label: string }[] = [
  { f: "md", label: "Baixar MD" },
  { f: "html", label: "Baixar HTML" },
  { f: "json", label: "Baixar JSON" },
];

function Downloads({ r }: { r: ReportDetail }) {
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
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-3">
        {FORMATS.map(({ f, label }) => (
          <Button key={f} tone={f === "html" ? "orange" : "white"} disabled={busy !== null} onClick={() => go(f)}>
            {busy === f ? "Baixando…" : label}
          </Button>
        ))}
      </div>
      <div role="status" aria-live="polite">
        {msg && (msg.ok ? <p className="font-bold">{msg.text}</p> : <ErrorBox>{msg.text}</ErrorBox>)}
      </div>
    </div>
  );
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <tr className="align-top">
      <th scope="row" className="brutal bg-muted p-2 text-left font-black uppercase">
        {k}
      </th>
      <td className="brutal p-2">{children}</td>
    </tr>
  );
}

function Summary({ r }: { r: ReportDetail }) {
  const s = r.summary;
  const ev = s.eval ?? {};
  const rt = s.redteam ?? {};
  const base = rt.asr_baseline;
  const guard = rt.asr_guardrails;
  const fpd = rt.false_positives?.dataset;
  const fpb = rt.false_positives?.benign;
  const ci = (lo?: number, hi?: number, f = fmtPct) => `IC 95%: ${f(lo)} a ${f(hi)}`;
  const attacks = (x: typeof base, label: string) =>
    x && x.n != null
      ? `${x.successes} de ${x.n} ataques tiveram sucesso ${label} (${fmtPct(x.asr)}; ${ci(x.ci95_low, x.ci95_high)}).`
      : "não informado";

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <caption className="sr-only">Resumo do relatório</caption>
        <tbody>
          <Row k="Qualidade (eval)">
            {ev.n_cases != null
              ? `Média de ${fmtNum(ev.mean_candidate)} na variante ${ev.candidate} contra ${fmtNum(ev.mean_baseline)} na ${ev.baseline}, em ${ev.n_cases} casos. Diferença ${fmtSigned(ev.mean_diff)} (${ci(ev.ci95_low, ev.ci95_high, fmtSigned)}; p = ${fmtNum(ev.p_value)}).`
              : "não informado"}
          </Row>
          <Row k="Red team">
            <p className="m-0">{attacks(base, "sem guardrails")}</p>
            <p className="m-0 mt-1">{attacks(guard, "com guardrails")}</p>
          </Row>
          <Row k="Falsos positivos">
            {fpd || fpb ? (
              <>
                {fpd && <p className="m-0">Conjunto do dataset: {fpd.blocked} de {fpd.n} perguntas legítimas bloqueadas.</p>}
                {fpb && <p className="m-0 mt-1">Perguntas benignas extras: {fpb.blocked} de {fpb.n} bloqueadas.</p>}
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
    <div className="flex flex-col gap-6">
      <Breadcrumbs items={crumbs} />
      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {r && (
        <>
          <Title>
            {r.agent_name} · versão {r.seq}
          </Title>

          <Card tone="yellow">
            <div className="flex flex-wrap items-center gap-4">
              <Semaforo value={r.status_semaforo} big />
              <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                <dt className="font-black uppercase">Gerado em</dt>
                <dd className="m-0">{fmtDateLong(r.generated_at)}</dd>
                <dt className="font-black uppercase">Publicado em</dt>
                <dd className="m-0">{fmtDateLong(r.published_at)}</dd>
                <dt className="font-black uppercase">Modelo</dt>
                <dd className="m-0">{r.model ?? "não informado"}</dd>
              </dl>
            </div>
            <p className="mt-4 text-lg font-bold">{LIMITS_TEXT}</p>
            <p className="mt-2 font-medium">{SELF_DECLARED_TEXT}</p>
          </Card>

          <section aria-labelledby="regra" className="flex flex-col gap-3">
            <Title as="h2">
              <span id="regra">Por que este semáforo</span>
            </Title>
            <p className="font-medium">
              Regras provisórias (versão {r.summary.semaphore?.rules_version ?? "não informada"}):
              vermelho se o gate de regressão disparar ou a auditoria informada for inválida;
              amarelo se houver ataque bem-sucedido com guardrails, falso positivo, queda não
              significativa ou ausência de auditoria; verde se nada disso ocorrer.
            </p>
            {triggered.length > 0 ? (
              <ul className="list-disc pl-6 font-medium">
                {triggered.map((t) => (
                  <li key={t}>{RULE_TEXT[t] ?? t}</li>
                ))}
              </ul>
            ) : (
              <p className="font-medium">Nenhuma regra de alerta disparou neste teste.</p>
            )}
          </section>

          <section aria-labelledby="resumo" className="flex flex-col gap-3">
            <Title as="h2">
              <span id="resumo">Resumo</span>
            </Title>
            <Summary r={r} />
          </section>

          <section aria-labelledby="ressalvas">
            <Card tone="pink">
              <Title as="h2" className="mb-3">
                <span id="ressalvas">Ressalvas</span>
              </Title>
              {r.limitations.length > 0 ? (
                <ul className="m-0 list-disc space-y-2 pl-6 font-medium">
                  {r.limitations.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              ) : (
                <p className="font-medium">
                  A lista de ressalvas não está disponível aqui; consulte o relatório baixado.
                </p>
              )}
            </Card>
          </section>

          <section aria-labelledby="baixar" className="flex flex-col gap-3">
            <Title as="h2">
              <span id="baixar">Baixar</span>
            </Title>
            <Downloads r={r} />
            <p className="text-sm font-medium">
              Cada download fica registrado em <Link to="/app/downloads" className="underline">Meus downloads</Link>.
            </p>
          </section>

          <details className="brutal bg-muted p-4">
            <summary className="cursor-pointer font-black uppercase">Dados de verificação</summary>
            <dl className="m-0 mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="font-black uppercase">SHA-256</dt>
              <dd className="m-0 break-all font-mono">{r.sha256}</dd>
              <dt className="font-black uppercase">Semente</dt>
              <dd className="m-0">{r.seed ?? "não informada"}</dd>
              <dt className="font-black uppercase">Casos</dt>
              <dd className="m-0">{r.n_cases ?? "não informado"}</dd>
              <dt className="font-black uppercase">Publicado</dt>
              <dd className="m-0">{fmtDate(r.published_at)}</dd>
            </dl>
          </details>
        </>
      )}
    </div>
  );
}
