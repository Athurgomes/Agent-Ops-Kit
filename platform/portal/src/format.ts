import type { Semaforo } from "./api";

/** Converts ISO to Date. No time zone in the text = UTC (that is what the API returns). */
export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}
/** Date and time in the browser's locale and time zone. */
export function fmtDate(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Not available";
}
export function fmtDateLong(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? d.toLocaleString(undefined, { dateStyle: "long", timeStyle: "long" }) : "Not available";
}

const NA = "n/a";
export const fmtPct = (x: number | undefined | null) =>
  x == null ? NA : x.toLocaleString(undefined, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const fmtNum = (x: number | undefined | null) =>
  x == null ? NA : x.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
export const fmtSigned = (x: number | undefined | null) =>
  x == null
    ? NA
    : x.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3, signDisplay: "exceptZero" });

type Light = { label: string; cls: string; dot: string };
/** The traffic light colors only ever mean the report result; they are never decoration. */
const SEMAFORO: Record<Semaforo, Light> = {
  green: { label: "Green", cls: "bg-[#dcfce7] text-[#14532d]", dot: "bg-[#16a34a]" },
  yellow: { label: "Yellow", cls: "bg-[#fef3c7] text-[#78350f]", dot: "bg-[#d97706]" },
  red: { label: "Red", cls: "bg-[#fee2e2] text-[#7f1d1d]", dot: "bg-[#dc2626]" },
};
export function semaforoOf(s: string): Light {
  return SEMAFORO[s as Semaforo] ?? { label: s, cls: "bg-soft text-ink", dot: "bg-subtle" };
}

// Reasons for the traffic light (engine rules, version "provisoria-1").
export const RULE_TEXT: Record<string, string> = {
  eval_regression: "the evaluation regression gate fired",
  audit_invalid: "the reported audit chain is invalid",
  attack_success_with_guardrails: "an attack succeeded with guardrails on",
  false_positive: "a legitimate question was blocked by the guardrails (false positive)",
  eval_nonsignificant_drop: "the evaluation showed a drop in the mean without statistical significance",
  no_audit: "no audit log was reported",
};

export const LIMITS_TEXT =
  "Green does not mean safe. It means that, in this test, with this set of attacks and these caveats, the results stayed within the defined limits. It does not cover attacks outside the suite, other models, or production use.";
export const SELF_DECLARED_TEXT =
  "Reports are self-reported: they are generated and published by the team that owns the agent. The portal stores them, shows them and logs downloads, but it does not rerun the tests or prove the results are true.";
