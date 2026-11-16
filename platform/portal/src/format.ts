import type { Semaforo } from "./api";

const dateTime = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const dateTimeLong = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "long",
  timeStyle: "long", // inclui o fuso do navegador
});

/** Converte ISO para Date. Sem fuso no texto = UTC (é o que a API devolve). */
export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}
/** Data e hora em pt-BR, no fuso do navegador. */
export function fmtDate(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? dateTime.format(d) : "não informado";
}
export function fmtDateLong(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? dateTimeLong.format(d) : "não informado";
}

const pct = new Intl.NumberFormat("pt-BR", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const dec = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const decSigned = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
  signDisplay: "exceptZero",
});
export const fmtPct = (x: number | undefined | null) => (x == null ? "n/d" : pct.format(x));
export const fmtNum = (x: number | undefined | null) => (x == null ? "n/d" : dec.format(x));
export const fmtSigned = (x: number | undefined | null) => (x == null ? "n/d" : decSigned.format(x));

type Light = { label: string; bg: string; mark: string };
const SEMAFORO: Record<Semaforo, Light> = {
  green: { label: "VERDE", bg: "bg-mint", mark: "●" },
  yellow: { label: "AMARELO", bg: "bg-yellow", mark: "▲" },
  red: { label: "VERMELHO", bg: "bg-danger", mark: "■" },
};
/** Cor mais rótulo e símbolo: o semáforo nunca depende só da cor. */
export function semaforoOf(s: string): Light {
  return SEMAFORO[s as Semaforo] ?? { label: s.toUpperCase(), bg: "bg-muted", mark: "?" };
}

// Motivos do semáforo (regras provisórias do motor, versão "provisoria-1").
export const RULE_TEXT: Record<string, string> = {
  eval_regression: "o gate de regressão do eval disparou",
  audit_invalid: "a cadeia de auditoria informada está inválida",
  attack_success_with_guardrails: "houve ataque bem-sucedido com os guardrails ligados",
  false_positive: "houve pergunta legítima bloqueada pelos guardrails (falso positivo)",
  eval_nonsignificant_drop: "o eval mostrou queda de média sem significância estatística",
  no_audit: "nenhum log de auditoria foi informado",
};

export const LIMITS_TEXT =
  "Verde não significa seguro. Significa que, neste teste, com este conjunto de ataques e estas ressalvas, os resultados ficaram dentro dos limites definidos. Não cobre ataques fora da suíte, outros modelos nem uso em produção.";
export const SELF_DECLARED_TEXT =
  "O relatório é autodeclarado: é gerado e publicado pelo time responsável pelo agente. O portal guarda, mostra e registra os downloads, mas não repete os testes nem comprova que os resultados são verdadeiros.";
