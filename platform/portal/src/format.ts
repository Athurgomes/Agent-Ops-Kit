import { ApiError } from "./api";
import type { Semaforo } from "./api";
import { copy } from "./copy";

const LOCALE = "pt-BR";

export const NOT_AVAILABLE = copy.format.notAvailable;
export const NA = copy.format.na;

/** Converts ISO to Date. No time zone in the text = UTC (that is what the API returns). */
export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Date and time in pt-BR using the browser's time zone. */
export function fmtDate(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? d.toLocaleString(LOCALE, { dateStyle: "medium", timeStyle: "short" }) : NOT_AVAILABLE;
}

export function fmtDateLong(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? d.toLocaleString(LOCALE, { dateStyle: "long", timeStyle: "long" }) : NOT_AVAILABLE;
}

export const fmtPct = (x: number | undefined | null) =>
  x == null
    ? NA
    : x.toLocaleString(LOCALE, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const fmtNum = (x: number | undefined | null) =>
  x == null ? NA : x.toLocaleString(LOCALE, { minimumFractionDigits: 3, maximumFractionDigits: 3 });

export const fmtSigned = (x: number | undefined | null) =>
  x == null
    ? NA
    : x.toLocaleString(LOCALE, { minimumFractionDigits: 3, maximumFractionDigits: 3, signDisplay: "exceptZero" });

export function fmtApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return copy.errors.network;
    if (err.status === 401) return copy.errors.unauthorized;
    if (err.status === 404) return err.message || copy.errors.notFound;
    if (err.status === 429) return copy.errors.tooMany;
    if (err.status >= 500) return copy.errors.server;
    return err.message || copy.errors.generic;
  }
  return err instanceof Error && err.message ? err.message : copy.common.errorFallback;
}

export type Light = { glyph: string; label: string; cls: string; dot: string };

/** Traffic-light colors and distinct Unicode glyphs represent only the report result, never decoration. */
export const SEMAFORO: Record<Semaforo, Light> = {
  green: {
    glyph: copy.format.semaforo.green.glyph,
    label: copy.format.semaforo.green.label,
    cls: "bg-[#ecfdf5] text-[#064e3b] border-[#064e3b]",
    dot: "bg-[#15803d]",
  },
  yellow: {
    glyph: copy.format.semaforo.yellow.glyph,
    label: copy.format.semaforo.yellow.label,
    cls: "bg-[#fffbeb] text-[#78350f] border-[#92400e]",
    dot: "bg-[#b45309]",
  },
  red: {
    glyph: copy.format.semaforo.red.glyph,
    label: copy.format.semaforo.red.label,
    cls: "bg-[#fef2f2] text-[#7f1d1d] border-[#991b1b]",
    dot: "bg-[#b91c1c]",
  },
};

export function semaforoOf(s: string): Light {
  return SEMAFORO[s as Semaforo] ?? { glyph: "■", label: s, cls: "bg-surface text-ink border-ink", dot: "bg-ink" };
}

// Reasons for the traffic light (engine rules, version "provisoria-1").
export const RULE_TEXT: Record<string, string> = copy.format.rules;

export const LIMITS_TEXT = copy.format.limitsText;
export const SELF_DECLARED_TEXT = copy.format.selfDeclaredText;
