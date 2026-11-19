import { useEffect } from "react";
import { AsciiCompass } from "../AsciiArt";
import { useAuth } from "../auth";
import { BRAND } from "../brand";
import { copy } from "../copy";
import { LinkButton } from "../ui";
import { CornerMarks } from "./AuthShell";

export function NotFound() {
  const { me } = useAuth();

  useEffect(() => {
    const before = document.title;
    document.title = `${copy.notFound.pageTitle} · ${BRAND}`;
    return () => {
      document.title = before;
    };
  }, []);

  return (
    <section className="bg-surface text-ink">
      <div className="container-page py-14 sm:py-20 lg:py-24">
        <div className="relative border border-ink bg-paper">
          <CornerMarks />

          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink bg-surface px-6 py-3.5 sm:px-10">
            <p className="eyebrow flex items-center gap-2.5">
              <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
              {copy.notFound.eyebrow}
            </p>
            <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle">
              {copy.notFound.coordinate}
            </span>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12">
            <div className="flex flex-col justify-between gap-8 p-6 sm:p-10 lg:col-span-7 lg:p-12">
              <div className="flex flex-col gap-5">
                <p
                  aria-hidden="true"
                  className="font-display text-[5.5rem] font-extrabold leading-none tracking-[-0.05em] text-ink sm:text-[7.5rem] lg:text-[9.5rem]"
                >
                  404<span className="text-accent">.</span>
                </p>

                <div aria-hidden="true" className="ruler-x" />

                <h1 className="heading text-3xl sm:text-4xl lg:text-5xl">{copy.notFound.title}</h1>
                <p className="max-w-xl text-subtle">{copy.notFound.body}</p>
              </div>

              <div className="flex flex-wrap items-center gap-4 pt-2">
                {me ? (
                  <>
                    <LinkButton to="/app" variant="primary" size="lg">
                      {copy.notFound.openPortal}
                    </LinkButton>
                    <LinkButton to="/" variant="secondary" size="lg">
                      {copy.notFound.backHome}
                    </LinkButton>
                  </>
                ) : (
                  <>
                    <LinkButton to="/" variant="primary" size="lg">
                      {copy.notFound.backHome}
                    </LinkButton>
                    <LinkButton to="/login" variant="secondary" size="lg">
                      {copy.notFound.login}
                    </LinkButton>
                  </>
                )}
              </div>
            </div>

            <div className="relative flex flex-col justify-between gap-4 border-t border-ink bg-ink p-6 text-white sm:p-8 lg:col-span-5 lg:border-l lg:border-t-0">
              <span
                aria-hidden="true"
                className="pointer-events-none absolute bottom-1.5 right-2 select-none font-mono text-xs font-normal leading-none text-white/75"
              >
                +
              </span>
              <span
                aria-hidden="true"
                className="pointer-events-none absolute bottom-1.5 left-2 select-none font-mono text-xs font-normal leading-none text-white/75 lg:hidden"
              >
                +
              </span>
              <AsciiCompass className="h-60 sm:h-64" />
              <div className="flex flex-col gap-3">
                <div aria-hidden="true" className="ruler-x-light" />
                <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-[#D4D4D4]">
                  {copy.notFound.artCaption}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
