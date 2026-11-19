import { useEffect } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AsciiCompass, AsciiHorizon } from "../AsciiArt";
import { BRAND } from "../brand";
import { copy } from "../copy";
import { Logo } from "../ui";

export function CornerMarks({ dark = false }: { dark?: boolean }) {
  const tone = dark ? "text-white/75" : "text-ink";
  return (
    <>
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute left-2 top-1.5 select-none font-mono text-xs font-normal leading-none ${tone}`}
      >
        +
      </span>
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute right-2 top-1.5 select-none font-mono text-xs font-normal leading-none ${tone}`}
      >
        +
      </span>
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute bottom-1.5 left-2 select-none font-mono text-xs font-normal leading-none ${tone}`}
      >
        +
      </span>
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute bottom-1.5 right-2 select-none font-mono text-xs font-normal leading-none ${tone}`}
      >
        +
      </span>
    </>
  );
}

/** Asymmetric logbook shell shared by login and password recovery pages. */
export function AuthShell({
  title,
  sheetCode = copy.auth.shell.sheetCode,
  art = "horizon",
  children,
}: {
  title: string;
  sheetCode?: string;
  art?: "horizon" | "compass";
  children: ReactNode;
}) {
  useEffect(() => {
    const before = document.title;
    document.title = `${title} · ${BRAND}`;
    return () => {
      document.title = before;
    };
  }, [title]);

  const artCode = art === "compass" ? copy.auth.shell.compassCode : copy.auth.shell.beaconCode;

  return (
    <div className="min-h-screen bg-surface text-ink lg:grid lg:grid-cols-12">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-paper focus:p-4">
        {copy.common.skipToContent}
      </a>

      {/* Mobile compact header */}
      <header className="border-b border-ink bg-ink text-white lg:hidden">
        <div className="flex items-center justify-between gap-4 px-5 py-4">
          <Logo inverted size="text-2xl" />
          <Link
            to="/"
            className="font-mono text-xs font-semibold uppercase tracking-[0.06em] text-white/85 underline-offset-4 hover:text-white hover:underline"
          >
            {copy.auth.shell.backHome}
          </Link>
        </div>
        <div className="border-t border-white/20 px-5 py-2.5">
          <p className="flex items-center gap-2 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white/85">
            <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
            {copy.auth.shell.folio}
          </p>
        </div>
      </header>

      {/* Desktop dark logbook panel */}
      <aside
        aria-label={copy.auth.shell.asideAria}
        className="hidden border-r border-ink bg-ink text-white lg:col-span-5 lg:flex lg:flex-col lg:justify-between lg:p-10 xl:p-14"
      >
        <div className="flex flex-col gap-6">
          <p className="flex items-center gap-2.5 font-mono text-xs font-semibold uppercase tracking-[0.08em] text-white/85">
            <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
            {copy.auth.shell.folio}
          </p>

          <Logo inverted size="text-5xl" />

          <div className="flex flex-col gap-3">
            <p className="font-display text-2xl font-extrabold leading-[1.06] tracking-[-0.03em] text-white xl:text-3xl">
              {copy.brand.tagline}
            </p>
            <p className="max-w-sm text-sm leading-relaxed text-[#D4D4D4]">{copy.brand.subtitle}</p>
          </div>
        </div>

        <div className="relative my-8 border border-white/25 bg-[#0A0A0A] p-5">
          <CornerMarks dark />
          <div className="mb-3 flex items-center justify-between gap-2 border-b border-white/20 pb-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white/85">
            <span>{copy.auth.shell.coordinate}</span>
            <span>{artCode}</span>
          </div>
          {art === "compass" ? <AsciiCompass className="h-52" /> : <AsciiHorizon className="h-[17rem]" />}
          <div aria-hidden="true" className="ruler-x-light mt-3" />
        </div>

        <div className="flex flex-col gap-4 border-t border-white/25 pt-5">
          <p className="text-sm text-[#D4D4D4]">{copy.auth.shell.accessNote}</p>
          <div>
            <Link
              to="/"
              className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-white/85 underline-offset-4 hover:text-white hover:underline"
            >
              {copy.auth.shell.backHome}
            </Link>
          </div>
        </div>
      </aside>

      {/* Right light logbook sheet */}
      <main
        id="content"
        className="flex min-w-0 flex-col justify-between px-4 py-8 sm:px-8 sm:py-12 lg:col-span-7 lg:px-14 lg:py-14"
      >
        <div className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center">
          <div className="relative border border-ink bg-paper">
            <CornerMarks />
            <div className="border-b border-ink bg-surface px-6 py-4 sm:px-10">
              <div className="flex items-center justify-end gap-3">
                <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle">
                  {sheetCode}
                </span>
              </div>
              <div aria-hidden="true" className="ruler-x mt-3" />
            </div>

            <div className="p-6 sm:p-10">{children}</div>
          </div>
        </div>

        <footer className="mx-auto mt-8 w-full max-w-lg border-t border-line pt-4">
          <p className="font-mono text-xs font-normal text-subtle">{copy.auth.shell.footerNote}</p>
        </footer>
      </main>
    </div>
  );
}
