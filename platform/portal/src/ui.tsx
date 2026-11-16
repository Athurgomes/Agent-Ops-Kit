// Componentes pequenos próprios (sem biblioteca de UI).
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { Link } from "react-router-dom";
import { BRAND } from "./brand";
import { semaforoOf } from "./format";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export type Tone = "yellow" | "mint" | "pink" | "white" | "muted";
const TONE: Record<Tone, string> = {
  yellow: "bg-yellow",
  mint: "bg-mint",
  pink: "bg-pink",
  white: "bg-paper",
  muted: "bg-muted",
};

// ---- botões ----------------------------------------------------------------------------------

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

// ---- blocos ----------------------------------------------------------------------------------

export function Logo({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="inline-flex items-center gap-2 no-underline" aria-label={`${BRAND}, início`}>
      <span aria-hidden="true" className="brutal block size-6 bg-yellow" />
      <span className="display text-2xl">{BRAND}</span>
    </Link>
  );
}

/** Cartão. `shadow` só nos cartões de destaque. */
export function Card({
  tone = "white",
  shadow = false,
  className,
  children,
}: {
  tone?: Tone;
  shadow?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cx("brutal p-6", TONE[tone], shadow && "shadow-hard", className)}>{children}</div>
  );
}

export function Tag({ children, tone = "yellow" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={cx("brutal inline-block px-2 py-0.5 text-sm font-bold", TONE[tone])}>{children}</span>
  );
}

/** Selo do semáforo: cor, símbolo e texto (nunca só a cor). */
export function SemaforoBadge({ value, size = "md" }: { value: string; size?: "md" | "lg" }) {
  const s = semaforoOf(value);
  return (
    <span
      className={cx(
        "brutal display inline-flex items-center gap-2 whitespace-nowrap",
        s.bg,
        size === "lg" ? "px-4 py-2 text-2xl" : "px-2 py-1 text-sm",
      )}
    >
      <span aria-hidden="true">{s.mark}</span>
      <span className="sr-only">Semáforo: </span>
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
  const size =
    As === "h1" ? "text-3xl lg:text-4xl" : As === "h2" ? "text-2xl lg:text-3xl" : "text-xl";
  return <As className={cx("display", size, className)}>{children}</As>;
}

export function Chevron({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      width="16"
      height="16"
      className={cx("chev shrink-0 transition-transform", className)}
    >
      <path d="M3 6l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="3" />
    </svg>
  );
}

// ---- estados ---------------------------------------------------------------------------------

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return (
    <div role="status" className="flex animate-pulse flex-col gap-4" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="h-8 w-1/3 bg-muted-2" />
      <div className="h-24 w-full bg-muted" />
      <div className="h-24 w-full bg-muted" />
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="brutal flex items-start gap-4 bg-danger p-4 font-semibold">
      <span aria-hidden="true" className="display text-xl">
        !
      </span>
      <div>{children}</div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="brutal flex flex-col items-start gap-2 border-dashed bg-muted p-12">
      <p className="display text-xl">{title}</p>
      {children && <p className="max-w-xl">{children}</p>}
    </div>
  );
}

// ---- formulário ------------------------------------------------------------------------------

export function Field({ label, id, ...p }: { label: string; id: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="font-bold">
        {label}
      </label>
      <input id={id} className="brutal bg-paper px-4 py-3" {...p} />
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
      <select id={id} className="brutal bg-paper px-4 py-2" {...p}>
        {children}
      </select>
    </div>
  );
}

// ---- navegação de página ---------------------------------------------------------------------

export type Crumb = { to?: string; label: string };
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Você está em">
      <ol className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-1 p-0 text-sm font-semibold">
        {items.map((c, i) => (
          <li key={i} className="flex min-w-0 items-center gap-2">
            {i > 0 && <span aria-hidden="true">/</span>}
            {c.to ? (
              <Link to={c.to} className="underline hover:bg-yellow">
                {c.label}
              </Link>
            ) : (
              <span aria-current="page" className="truncate">
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
    <header className="mb-12 flex flex-col gap-4 border-b-[3px] border-ink pb-6">
      <Breadcrumbs items={crumbs} />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Title className="min-w-0 max-w-3xl">{title}</Title>
        {children}
      </div>
      {lead && <p className="max-w-3xl">{lead}</p>}
    </header>
  );
}

export function Section({
  id,
  tone = "white",
  className,
  children,
}: {
  id?: string;
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={cx(TONE[tone], tone !== "white" && "border-y-[3px] border-ink", className)}>
      <div className="container-page py-24">{children}</div>
    </section>
  );
}

export type AsyncState<T> = { data: T | null; error: string | null; loading: boolean };
/** Carrega dados; recarrega quando `deps` mudam. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [st, setSt] = useState<AsyncState<T>>({ data: null, error: null, loading: true });
  useEffect(() => {
    let alive = true;
    setSt((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (data) => alive && setSt({ data, error: null, loading: false }),
      (e: unknown) =>
        alive && setSt({ data: null, error: e instanceof Error ? e.message : "Erro.", loading: false }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return st;
}
