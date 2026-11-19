import { useEffect, useRef, useState } from "react";
import { AsciiField } from "../AsciiField";
import { useAuth } from "../auth";
import { CONTACT_URL } from "../brand";
import { copy } from "../copy";
import { LinkButton, Logo } from "../ui";

function HeroDarkContent({ showScrollHint }: { showScrollHint: boolean }) {
  const { me } = useAuth();
  const hasContact = CONTACT_URL.trim().length > 0;

  return (
    <div className="container-page relative z-10 flex h-full flex-col justify-between pb-8 pt-[calc(var(--header-h)+1.75rem)] sm:pb-10 sm:pt-[calc(var(--header-h)+3rem)]">
      <div className="my-auto flex max-w-4xl flex-col items-start gap-5 sm:gap-7">
        <div className="flex flex-wrap items-center gap-4">
          <span className="font-mono text-xs font-semibold uppercase tracking-[0.12em] text-white/60">
            {copy.hero.eyebrow}
          </span>
          <Logo to={null} inverted size="text-2xl sm:text-3xl" />
        </div>

        <h1 className="text-[2.5rem] font-extrabold leading-[1.03] tracking-[-0.035em] text-white sm:text-6xl lg:text-[4.75rem]">
          <span className="font-medium text-white/75">{copy.hero.titlePrefix}</span>
          <span className="font-extrabold text-white">{copy.hero.titleHighlight}</span>
          <span className="font-extrabold text-accent">{copy.hero.titleDot}</span>
        </h1>

        <p className="max-w-xl text-lg leading-relaxed text-white/75 sm:text-xl">{copy.hero.subtitle}</p>

        <div className="flex flex-wrap items-center gap-3 pt-1 sm:gap-4">
          <LinkButton to={me ? "/app" : "/login"} variant="primary" size="lg">
            {me ? copy.nav.openPortal : copy.nav.login}
          </LinkButton>
          <a href="#how-it-works" className="btn btn-ghost-dark btn-lg">
            {copy.hero.ctaSecondary}
          </a>
          {hasContact && (
            <a href={CONTACT_URL} className="btn btn-ghost-dark btn-lg">
              {copy.nav.contact}
            </a>
          )}
        </div>
      </div>

      {showScrollHint && (
        <p className="font-mono text-xs font-semibold uppercase tracking-[0.12em] text-white/55">
          {copy.hero.scrollHint}
        </p>
      )}
    </div>
  );
}

function ProblemLightContent({ insetHeader = true }: { insetHeader?: boolean }) {
  return (
    <div
      className={`container-page relative z-10 flex h-full flex-col justify-center ${
        insetHeader ? "pt-[var(--header-h)]" : ""
      }`}
    >
      <div className="flex max-w-4xl flex-col items-start gap-6 sm:gap-8">
        <p className="eyebrow flex items-center gap-2.5">
          <span aria-hidden="true" className="size-2.5 rounded-full bg-accent" />
          {copy.problem.eyebrow}
        </p>

        <h2 className="text-[2rem] leading-[1.06] tracking-[-0.035em] text-ink sm:text-5xl lg:text-[3.75rem]">
          <span className="font-medium text-ink/70">{copy.problem.titlePrefix}</span>
          <span className="font-extrabold text-accent">{copy.problem.titleHighlight}</span>
          <span className="font-extrabold text-ink">{copy.problem.titleSuffix}</span>
        </h2>

        <p className="max-w-2xl text-lg leading-relaxed text-subtle sm:text-xl">{copy.problem.subtitle}</p>
      </div>
    </div>
  );
}

export function HeroIris() {
  const wrapperRef = useRef<HTMLElement | null>(null);
  const scene1Ref = useRef<HTMLDivElement | null>(null);
  const scene2Ref = useRef<HTMLDivElement | null>(null);
  const [reducedMotion, setReducedMotion] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    setReducedMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;

    if (reducedMotion) {
      wrapper.style.removeProperty("--iris");
      wrapper.style.removeProperty("--hero-fade");
      return;
    }

    let rafId = 0;

    const update = () => {
      rafId = 0;
      const stage = wrapper.querySelector<HTMLElement>("[data-hero-stage]");
      const stageH = stage?.offsetHeight || window.innerHeight;
      const total = Math.max(1, wrapper.offsetHeight - stageH);
      const rect = wrapper.getBoundingClientRect();
      const progress = Math.min(1, Math.max(0, -rect.top / total));
      const heroFade = Math.max(0, 1 - progress * 2.25);

      wrapper.style.setProperty("--iris", progress.toFixed(4));
      wrapper.style.setProperty("--hero-fade", heroFade.toFixed(4));

      if (scene1Ref.current) {
        scene1Ref.current.style.pointerEvents = progress >= 0.4 ? "none" : "auto";
      }
      if (scene2Ref.current) {
        scene2Ref.current.style.pointerEvents = progress >= 0.4 ? "auto" : "none";
      }
    };

    const schedule = () => {
      if (rafId === 0) {
        rafId = requestAnimationFrame(update);
      }
    };

    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });

    return () => {
      if (rafId !== 0) cancelAnimationFrame(rafId);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [reducedMotion]);

  if (reducedMotion) {
    return (
      <section ref={wrapperRef} data-hero-iris="" className="relative -mt-[var(--header-h)]">
        <div data-hero-dark="" className="relative overflow-hidden bg-ink pb-16 text-white sm:pb-24">
          <AsciiField className="absolute inset-0 h-full w-full" />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse 72% 76% at 28% 54%, rgba(10,10,10,0.86) 0%, rgba(10,10,10,0.52) 58%, rgba(10,10,10,0.22) 100%)",
            }}
          />
          <HeroDarkContent showScrollHint={false} />
        </div>

        <div className="aura-light relative overflow-hidden bg-paper py-20 text-ink sm:py-28">
          <ProblemLightContent insetHeader={false} />
        </div>
      </section>
    );
  }

  return (
    <section
      ref={wrapperRef}
      data-hero-iris=""
      className="relative -mt-[var(--header-h)] min-h-[190vh] bg-ink sm:min-h-[210vh]"
      style={{ ["--iris" as string]: "0", ["--hero-fade" as string]: "1" }}
    >
      <div data-hero-stage="" className="sticky top-0 h-[100svh] overflow-hidden">
        {/* Scene 1: Dark hero with AsciiField */}
        <div
          ref={scene1Ref}
          className="absolute inset-0 bg-ink text-white"
          style={{
            opacity: "var(--hero-fade, 1)",
            transform: "translateY(calc((1 - var(--hero-fade, 1)) * -14px))",
          }}
        >
          <AsciiField className="absolute inset-0 h-full w-full" />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse 72% 76% at 28% 54%, rgba(10,10,10,0.86) 0%, rgba(10,10,10,0.52) 58%, rgba(10,10,10,0.22) 100%)",
            }}
          />
          <HeroDarkContent showScrollHint />
        </div>

        {/* Scene 2: Light world revealed by circular iris */}
        <div
          ref={scene2Ref}
          className="iris-layer aura-light pointer-events-none absolute inset-0 overflow-hidden bg-paper text-ink"
        >
          <ProblemLightContent />
        </div>
      </div>
    </section>
  );
}
