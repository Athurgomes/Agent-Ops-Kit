// Small in-house components (no UI library).
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { Link } from "react-router-dom";
import { AsciiSounding, AsciiWaves } from "./AsciiArt";
import { copy } from "./copy";
import { fmtApiError, semaforoOf } from "./format";

export { Logo } from "./Logo";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

// ---- buttons ---------------------------------------------------------------------------------

type Variant = "primary" | "secondary" | "dark";
type Size = "sm" | "md" | "lg";
const btnCls = (v: Variant, s: Size, extra?: string) =>
  cx("btn", `btn-${v}`, s === "sm" && "btn-sm", s === "lg" && "btn-lg", extra);

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button type="button" className={btnCls(variant, size, className)} {...p} />;
}

export function LinkButton({
  to,
  variant = "secondary",
  size = "md",
  className,
  children,
}: {
  to: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link to={to} className={btnCls(variant, size, className)}>
      {children}
    </Link>
  );
}

// ---- blocks ----------------------------------------------------------------------------------

/** Flat logbook panel with 1px ink border. */
export function Box({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("box p-6", className)}>{children}</div>;
}

/** Uppercase mono stamp with 1px border. */
export function Tag({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  return (
    <span
      className={cx(
        "inline-block rounded-[2px] border px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.06em]",
        muted ? "border-ink/40 bg-paper text-subtle" : "border-ink bg-surface text-ink",
      )}
    >
      {children}
    </span>
  );
}

/** Traffic-light label: color + distinct Unicode glyph + text (never color alone). Colors only ever mean the result. */
export function SemaforoBadge({ value, size = "md" }: { value: string; size?: "md" | "lg" }) {
  const s = semaforoOf(value);
  return (
    <span
      className={cx(
        "inline-flex items-center whitespace-nowrap rounded-none border font-mono font-semibold uppercase tracking-[0.06em]",
        s.cls,
        size === "lg" ? "gap-2.5 px-4 py-2 text-base" : "gap-2 px-2.5 py-1 text-xs",
      )}
    >
      <span aria-hidden="true" className={cx("shrink-0 leading-none", size === "lg" ? "text-lg" : "text-sm")}>
        {s.glyph}
      </span>
      <span className="sr-only">{copy.aria.trafficLightPrefix}</span>
      {s.label}
    </span>
  );
}

export function Title({
  as: As = "h1",
  children,
  className,
}: {
  as?: "h1" | "h2" | "h3";
  children: ReactNode;
  className?: string;
}) {
  const size = As === "h1" ? "text-4xl lg:text-5xl" : As === "h2" ? "text-2xl lg:text-3xl" : "text-xl";
  return <As className={cx("heading", size, className)}>{children}</As>;
}

// ---- states ----------------------------------------------------------------------------------

export function Loading({ label = copy.common.loading }: { label?: string }) {
  return (
    <div role="status" className="flex animate-pulse flex-col gap-4" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="h-8 w-1/3 border border-line bg-hair" />
      <div className="h-20 w-full border border-line bg-surface" />
      <div className="h-20 w-full border border-line bg-surface" />
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-3 border border-[#991b1b] bg-[#fef2f2] p-4 text-[#991b1b]">
      <span aria-hidden="true" className="font-mono font-semibold">
        [!]
      </span>
      <div>{children}</div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 border border-dashed border-ink/40 bg-surface p-10">
      <p className="heading text-2xl">{title}</p>
      {children && <p className="max-w-xl text-subtle">{children}</p>}
    </div>
  );
}

/** Logbook loading block with ASCII waves (aria-hidden, respects prefers-reduced-motion). */
export function LogbookLoading({
  label = copy.common.loading,
  caption,
}: {
  label?: string;
  caption: string;
}) {
  return (
    <div role="status" aria-live="polite" className="border border-ink bg-paper">
      <span className="sr-only">{label}</span>
      <div className="flex items-center justify-between border-b border-line bg-surface px-5 py-3">
        <span className="eyebrow">{caption}</span>
        <span className="font-mono text-xs text-subtle">···</span>
      </div>
      <AsciiWaves className="h-20 border-b border-line" />
      <div className="flex animate-pulse flex-col gap-3 p-6">
        <div className="h-8 w-1/3 border border-line bg-surface" />
        <div className="h-12 w-full border border-line bg-surface" />
        <div className="h-12 w-full border border-line bg-surface" />
      </div>
    </div>
  );
}

/** Logbook empty state with ASCII sounding gauge (aria-hidden, respects prefers-reduced-motion). */
export function LogbookEmpty({
  tag,
  title,
  artCaption,
  children,
}: {
  tag: string;
  title: string;
  artCaption: string;
  children?: ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 border border-ink bg-surface md:grid-cols-[1.35fr_1fr]">
      <div className="flex flex-col items-start justify-center gap-3 p-8 lg:p-10">
        <Tag>{tag}</Tag>
        <h2 className="heading text-2xl lg:text-3xl">{title}</h2>
        {children && <p className="max-w-lg text-subtle">{children}</p>}
      </div>
      <div className="flex flex-col justify-between border-t border-ink/25 bg-surface md:border-l md:border-t-0">
        <AsciiSounding className="h-40" />
        <p className="border-t border-line px-4 py-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">
          {artCaption}
        </p>
      </div>
    </section>
  );
}

// ---- forms -----------------------------------------------------------------------------------

export function Field({
  label,
  id,
  aside,
  hint,
  ...p
}: { label: string; id: string; aside?: ReactNode; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-4">
        <label htmlFor={id} className="font-bold">
          {label}
        </label>
        {aside}
      </div>
      <input
        id={id}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="rounded-[2px] border border-ink/35 bg-paper px-4 py-3 text-ink focus:border-accent"
        {...p}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-subtle">
          {hint}
        </p>
      )}
    </div>
  );
}

export function Select({
  label,
  id,
  children,
  ...p
}: { label: string; id: string; children: ReactNode } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor={id} className="text-sm font-bold">
        {label}
      </label>
      <select
        id={id}
        className="rounded-[2px] border border-ink/35 bg-paper px-4 py-3 text-ink focus:border-accent"
        {...p}
      >
        {children}
      </select>
    </div>
  );
}

// ---- page navigation -------------------------------------------------------------------------

export type Crumb = { to?: string; label: string };
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label={copy.aria.breadcrumbs}>
      <ol className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-1 p-0 font-mono text-xs uppercase tracking-[0.06em] text-subtle">
        {items.map((c, i) => (
          <li key={i} className="flex min-w-0 items-center gap-2">
            {i > 0 && <span aria-hidden="true">/</span>}
            {c.to ? (
              <Link to={c.to} className="underline hover:text-accent">
                {c.label}
              </Link>
            ) : (
              <span aria-current="page" className="truncate font-semibold text-ink">
                {c.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PageHeader({
  crumbs,
  title,
  lead,
  stamp,
  children,
}: {
  crumbs: Crumb[];
  title: string;
  lead?: ReactNode;
  stamp?: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-10 flex flex-col gap-4 border-b border-ink pb-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Breadcrumbs items={crumbs} />
        {stamp && (
          <span className="border border-ink bg-surface px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-ink">
            {stamp}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Title className="min-w-0 max-w-3xl">{title}</Title>
        {children}
      </div>
      {lead && <p className="max-w-3xl text-subtle">{lead}</p>}
    </header>
  );
}

export type AsyncState<T> = { data: T | null; error: string | null; loading: boolean };
/** Loads data; reloads when `deps` change. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [st, setSt] = useState<AsyncState<T>>({ data: null, error: null, loading: true });
  useEffect(() => {
    let alive = true;
    setSt((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (data) => alive && setSt({ data, error: null, loading: false }),
      (e: unknown) => alive && setSt({ data: null, error: fmtApiError(e), loading: false }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return st;
}
