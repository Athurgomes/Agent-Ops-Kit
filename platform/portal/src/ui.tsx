// Small in-house components (no UI library).
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { Link } from "react-router-dom";
import { BRAND } from "./brand";
import { semaforoOf } from "./format";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

// ---- buttons ---------------------------------------------------------------------------------

type Variant = "primary" | "secondary";
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

/** Not-yet-available action: not clickable (no href, no handler), default cursor, "Soon" badge. */
export function SoonButton({
  children,
  variant = "primary",
  size = "sm",
  className,
}: {
  children: ReactNode;
  variant?: Variant;
  size?: Size;
  className?: string;
}) {
  return (
    <span
      role="button"
      aria-disabled="true"
      title="Coming soon"
      className={cx(btnCls(variant, size, className), "soon")}
    >
      {children}
      <span className="soon-badge">Soon</span>
    </span>
  );
}

/** Not-yet-available text item (nav or footer): not a link, with a discreet "Soon" label. */
export function SoonText({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span aria-disabled="true" title="Coming soon" className={cx("soon inline-flex items-center gap-2 text-subtle", className)}>
      {children}
      <span className="soon-badge">Soon</span>
    </span>
  );
}

// ---- blocks ----------------------------------------------------------------------------------

export function Logo({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="text-2xl font-extrabold tracking-tight text-navy no-underline" aria-label={`${BRAND}, home`}>
      {BRAND}
    </Link>
  );
}

export function Card({
  shadow = false,
  className,
  children,
}: {
  shadow?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return <div className={cx("card p-6", shadow && "card-soft", className)}>{children}</div>;
}

/** Small neutral label. */
export function Tag({ children, tone = "tint" }: { children: ReactNode; tone?: "tint" | "soft" }) {
  return (
    <span
      className={cx(
        "inline-block rounded-full px-3 py-1 text-sm font-semibold",
        tone === "tint" ? "bg-tint text-navy" : "bg-soft text-subtle",
      )}
    >
      {children}
    </span>
  );
}

/** Traffic-light pill: color + dot + text (never color alone). */
export function SemaforoBadge({ value, size = "md" }: { value: string; size?: "md" | "lg" }) {
  const s = semaforoOf(value);
  return (
    <span
      className={cx(
        "inline-flex items-center gap-2 whitespace-nowrap rounded-full font-semibold",
        s.cls,
        size === "lg" ? "px-4 py-2 text-lg" : "px-3 py-1 text-sm",
      )}
    >
      <span aria-hidden="true" className={cx("size-2.5 rounded-full", s.dot)} />
      <span className="sr-only">Traffic light: </span>
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
  const size = As === "h1" ? "text-3xl lg:text-4xl" : As === "h2" ? "text-2xl lg:text-3xl" : "text-xl";
  return <As className={cx("heading", size, className)}>{children}</As>;
}

export function Chevron({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" className={cx("chev shrink-0 transition-transform", className)}>
      <path d="M3 6l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ---- states ----------------------------------------------------------------------------------

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex animate-pulse flex-col gap-4" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="h-8 w-1/3 rounded-lg bg-line" />
      <div className="h-24 w-full rounded-2xl bg-soft" />
      <div className="h-24 w-full rounded-2xl bg-soft" />
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-2xl border border-[#fecaca] bg-[#fef2f2] p-4 text-[#7f1d1d]">
      <span aria-hidden="true" className="font-bold">
        !
      </span>
      <div>{children}</div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-2xl border border-dashed border-[#cbd5e1] bg-soft p-12">
      <p className="text-xl font-bold text-navy">{title}</p>
      {children && <p className="max-w-xl text-subtle">{children}</p>}
    </div>
  );
}

// ---- forms -----------------------------------------------------------------------------------

export function Field({ label, id, ...p }: { label: string; id: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-semibold text-navy">
        {label}
      </label>
      <input id={id} className="rounded-xl border border-[#cbd5e1] bg-paper px-4 py-3 hover:border-accent" {...p} />
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
      <label htmlFor={id} className="text-sm font-semibold text-navy">
        {label}
      </label>
      <select id={id} className="rounded-xl border border-[#cbd5e1] bg-paper px-4 py-2.5 hover:border-accent" {...p}>
        {children}
      </select>
    </div>
  );
}

// ---- page navigation -------------------------------------------------------------------------

export type Crumb = { to?: string; label: string };
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="You are here">
      <ol className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-1 p-0 text-sm text-subtle">
        {items.map((c, i) => (
          <li key={i} className="flex min-w-0 items-center gap-2">
            {i > 0 && <span aria-hidden="true">/</span>}
            {c.to ? (
              <Link to={c.to} className="hover:text-accent hover:underline">
                {c.label}
              </Link>
            ) : (
              <span aria-current="page" className="truncate font-medium text-ink">
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
  children,
}: {
  crumbs: Crumb[];
  title: string;
  lead?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-12 flex flex-col gap-4">
      <Breadcrumbs items={crumbs} />
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
      (e: unknown) => alive && setSt({ data: null, error: e instanceof Error ? e.message : "Error.", loading: false }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return st;
}
