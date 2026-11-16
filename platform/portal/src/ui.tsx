// Small in-house components (no UI library).
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { Link } from "react-router-dom";
import { BRAND } from "./brand";
import { semaforoOf } from "./format";

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

/** Not-yet-available action: not clickable (no href, no handler), default cursor, "Soon" label. */
export function SoonButton({
  children,
  variant = "dark",
  size = "sm",
  className,
}: {
  children: ReactNode;
  variant?: Variant;
  size?: Size;
  className?: string;
}) {
  return (
    <span role="button" aria-disabled="true" title="Coming soon" className={cx(btnCls(variant, size, className), "soon")}>
      {children}
      <span className="soon-badge">Soon</span>
    </span>
  );
}

/** Not-yet-available text item (nav, footer, login): not a link, with a discreet "Soon" label. */
export function SoonText({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span aria-disabled="true" title="Coming soon" className={cx("soon inline-flex items-center gap-2", className)}>
      {children}
      <span className="soon-badge">Soon</span>
    </span>
  );
}

// ---- blocks ----------------------------------------------------------------------------------

export function Logo({ to = "/", size = "text-2xl" }: { to?: string; size?: string }) {
  return (
    <Link to={to} className={cx("heading no-underline", size)} aria-label={`${BRAND}, home`}>
      {BRAND}
    </Link>
  );
}

/** Container: thin black border, square corners, no shadow. */
export function Box({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("box p-6", className)}>{children}</div>;
}

/** Small square label. */
export function Tag({ children }: { children: ReactNode }) {
  return <span className="inline-block border border-ink px-2 py-0.5 text-sm font-semibold">{children}</span>;
}

/** Traffic-light label: color + dot + text (never color alone). Colors only ever mean the result. */
export function SemaforoBadge({ value, size = "md" }: { value: string; size?: "md" | "lg" }) {
  const s = semaforoOf(value);
  return (
    <span
      className={cx(
        "inline-flex items-center gap-2 whitespace-nowrap border border-ink font-bold",
        s.cls,
        size === "lg" ? "px-4 py-2 text-lg" : "px-2.5 py-0.5 text-sm",
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
  const size = As === "h1" ? "text-4xl lg:text-5xl" : As === "h2" ? "text-2xl lg:text-3xl" : "text-xl";
  return <As className={cx("heading", size, className)}>{children}</As>;
}

// ---- states ----------------------------------------------------------------------------------

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex animate-pulse flex-col gap-4" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="h-8 w-1/3 bg-hair" />
      <div className="h-20 w-full bg-hair/60" />
      <div className="h-20 w-full bg-hair/60" />
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="box flex items-start gap-3 bg-[#fee2e2] p-4">
      <span aria-hidden="true" className="font-black">
        !
      </span>
      <div>{children}</div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 border border-dashed border-ink p-12">
      <p className="heading text-2xl">{title}</p>
      {children && <p className="max-w-xl text-subtle">{children}</p>}
    </div>
  );
}

// ---- forms (pills) ---------------------------------------------------------------------------

export function Field({
  label,
  id,
  aside,
  ...p
}: { label: string; id: string; aside?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-4">
        <label htmlFor={id} className="font-bold">
          {label}
        </label>
        {aside}
      </div>
      <input id={id} className="rounded-full border border-ink bg-paper px-5 py-3" {...p} />
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
      <select id={id} className="rounded-full border border-ink bg-paper px-5 py-2.5" {...p}>
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
  children,
}: {
  crumbs: Crumb[];
  title: string;
  lead?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="rule-b mb-12 flex flex-col gap-4 pb-8">
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
