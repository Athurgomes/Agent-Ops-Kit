import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../../api";
import { AsciiCompass } from "../../AsciiArt";
import { copy } from "../../copy";
import { fmtApiError } from "../../format";
import { useOps } from "../../opsAuth";
import { Button, ErrorBox, Field, Logo } from "../../ui";
import { CornerMarks } from "../AuthShell";

export function OpsLogin() {
  const { status, login } = useOps();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;
  const target = from?.startsWith("/ops") && from !== "/ops/login" ? from : "/ops/organizations";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const lCopy = copy.ops.login;

  useEffect(() => {
    const before = document.title;
    document.title = `${lCopy.pageTitle} · ${copy.opsBar.subtitle} · ${copy.brand.full}`;
    return () => {
      document.title = before;
    };
  }, [lCopy.pageTitle]);

  if (status === "authed") return <Navigate to={target} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      nav(target, { replace: true });
    } catch (err) {
      // generic error: never reveals whether the email exists
      if (err instanceof ApiError && err.status !== 401) {
        setError(fmtApiError(err));
      } else {
        setError(copy.auth.errors.invalidCredentials);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-surface text-ink lg:grid lg:grid-cols-12">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        {copy.common.skipToContent}
      </a>

      {/* Mobile compact header */}
      <header className="border-b border-ink bg-ink text-white lg:hidden">
        <div className="flex items-center justify-between gap-4 px-5 py-4">
          <Logo to={null} inverted size="text-2xl" />
          <span className="inline-flex items-center gap-2 border border-white/35 bg-white/5 px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white">
            <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
            {copy.opsBar.badge}
          </span>
        </div>
        <div className="border-t border-white/20 px-5 py-2.5">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white/85">
            {lCopy.folio}
          </p>
        </div>
      </header>

      {/* Desktop dark logbook panel (isolated: no public links) */}
      <aside
        aria-label={lCopy.asideAria}
        className="hidden border-r border-ink bg-ink text-white lg:col-span-5 lg:flex lg:flex-col lg:justify-between lg:p-10 xl:p-14"
      >
        <div className="flex flex-col gap-6">
          <p className="flex items-center gap-2.5 font-mono text-xs font-semibold uppercase tracking-[0.08em] text-white/85">
            <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
            {lCopy.folio}
          </p>

          <Logo to={null} inverted size="text-5xl" />

          <div className="flex flex-col gap-3">
            <p className="font-display text-2xl font-extrabold leading-[1.06] tracking-[-0.03em] text-white xl:text-3xl">
              {lCopy.asideTitle}
            </p>
            <p className="max-w-sm text-sm leading-relaxed text-[#D4D4D4]">{lCopy.asideSubtitle}</p>
          </div>
        </div>

        <div className="relative my-8 border border-white/25 bg-[#0A0A0A] p-5">
          <CornerMarks dark />
          <div className="mb-3 flex items-center justify-between gap-2 border-b border-white/20 pb-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white/85">
            <span>{lCopy.coordinate}</span>
            <span>{lCopy.compassCode}</span>
          </div>
          <AsciiCompass className="h-52" />
          <div aria-hidden="true" className="ruler-x-light mt-3" />
        </div>

        <div className="border-t border-white/25 pt-5">
          <p className="text-sm text-[#D4D4D4]">{lCopy.asideNote}</p>
        </div>
      </aside>

      {/* Right light logbook form sheet */}
      <main
        id="content"
        className="flex min-w-0 flex-col justify-between px-4 py-8 sm:px-8 sm:py-12 lg:col-span-7 lg:px-14 lg:py-14"
      >
        <div className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center">
          <div className="relative border border-ink bg-paper">
            <CornerMarks />
            <div className="border-b border-ink bg-surface px-6 py-4 sm:px-10">
              <div className="flex items-center justify-between gap-3">
                <p className="eyebrow flex items-center gap-2.5">
                  <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
                  {lCopy.eyebrow}
                </p>
                <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle">
                  {lCopy.sheetCode}
                </span>
              </div>
              <div aria-hidden="true" className="ruler-x mt-3" />
            </div>

            <div className="p-6 sm:p-10">
              <h1 className="heading text-3xl sm:text-5xl">{lCopy.title}</h1>
              <p className="mt-3 text-subtle">{lCopy.subtitle}</p>
              <form onSubmit={submit} className="mt-8 flex flex-col gap-6">
                <Field
                  label={lCopy.emailLabel}
                  id="ops-email"
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <Field
                  label={lCopy.passwordLabel}
                  id="ops-password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                {error && <ErrorBox>{error}</ErrorBox>}
                <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
                  {busy ? lCopy.submitting : lCopy.submit}
                </Button>
              </form>
            </div>
          </div>
        </div>

        <footer className="mx-auto mt-8 w-full max-w-lg border-t border-line pt-4">
          <p className="font-mono text-xs font-normal text-subtle">{lCopy.footerNote}</p>
        </footer>
      </main>
    </div>
  );
}
