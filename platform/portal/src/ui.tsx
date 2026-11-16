// Componentes pequenos próprios (sem biblioteca de UI).
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import { semaforoOf } from "./format";

const join = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");

type Tone = "orange" | "yellow" | "mint" | "pink" | "white";
const TONE: Record<Tone, string> = {
  orange: "bg-orange",
  yellow: "bg-yellow",
  mint: "bg-mint",
  pink: "bg-pink",
  white: "bg-paper",
};
const BTN =
  "brutal brutal-shadow press inline-flex items-center justify-center gap-2 px-5 py-3 font-display font-black uppercase text-ink no-underline cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";

export function Button({
  tone = "orange",
  className,
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone }) {
  return <button type="button" className={join(BTN, TONE[tone], className)} {...p} />;
}

export function LinkButton({
  to,
  tone = "orange",
  children,
  className,
}: {
  to: string;
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link to={to} className={join(BTN, TONE[tone], className)}>
      {children}
    </Link>
  );
}

export function Card({
  tone = "white",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={join("brutal brutal-shadow p-5 sm:p-6", TONE[tone], className)}>{children}</div>
  );
}

export function Tag({ children, tone = "yellow" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={join("brutal inline-block px-3 py-1 text-sm font-black uppercase", TONE[tone])}>
      {children}
    </span>
  );
}

export function Semaforo({ value, big = false }: { value: string; big?: boolean }) {
  const s = semaforoOf(value);
  return (
    <span
      className={join(
        "brutal inline-flex items-center gap-2 font-display font-black uppercase",
        s.bg,
        big ? "px-5 py-3 text-3xl" : "px-3 py-1 text-sm",
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
  const size = As === "h1" ? "text-4xl sm:text-6xl" : As === "h2" ? "text-2xl sm:text-4xl" : "text-xl";
  return <As className={join("title", size, className)}>{children}</As>;
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return (
    <p role="status" className="p-6 font-black uppercase">
      {label}
    </p>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="brutal bg-danger p-4 font-bold">
      {children}
    </div>
  );
}

export function Field({
  label,
  id,
  ...p
}: { label: string; id: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="font-black uppercase">
        {label}
      </label>
      <input id={id} className="brutal bg-paper px-3 py-3 text-lg" {...p} />
    </div>
  );
}

export function Select({
  label,
  id,
  children,
  ...p
}: { label: string; id: string; children: ReactNode } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="font-black uppercase">
        {label}
      </label>
      <select id={id} className="brutal bg-paper px-3 py-3 text-base" {...p}>
        {children}
      </select>
    </div>
  );
}

export type Crumb = { to?: string; label: string };
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Você está em" className="mb-4">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-bold">
        {items.map((c, i) => (
          <li key={i} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden="true">/</span>}
            {c.to ? (
              <Link to={c.to} className="underline">
                {c.label}
              </Link>
            ) : (
              <span aria-current="page">{c.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
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
        alive &&
        setSt({ data: null, error: e instanceof Error ? e.message : "Erro.", loading: false }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return st;
}
