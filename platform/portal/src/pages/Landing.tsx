import { AsciiHorizon, AsciiMorse, AsciiSounding } from "../AsciiArt";
import { useAuth } from "../auth";
import { CONTACT_URL } from "../brand";
import { copy } from "../copy";
import { Reveal } from "../Reveal";
import { LinkButton, Logo } from "../ui";
import { HeroIris } from "./HeroIris";
import {
  AudienceSection,
  HowItWorksSection,
  PermissionsSection,
  SceneEyebrow,
  WhatYouSeeSection,
} from "./LandingSections";

// ---- Cena 6: Sinal e Limite (faixa full-bleed #2563EB com texto branco e AsciiMorse) --------

function HonestySection() {
  return (
    <section id="limits" className="bg-accent text-white">
      <div className="container-page py-20 lg:py-28">
        <AsciiMorse />
        <div aria-hidden="true" className="ruler-x-light mt-2" />

        <div className="mt-10 grid grid-cols-1 gap-10 lg:grid-cols-12 lg:gap-12">
          <div className="lg:col-span-5">
            <Reveal>
              <p className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-white">
                {copy.honesty.eyebrow}
              </p>
              <h2 className="font-display mt-4 text-4xl font-extrabold leading-[1.02] tracking-[-0.035em] text-white sm:text-5xl lg:text-6xl">
                {copy.honesty.title}
              </h2>
            </Reveal>
          </div>

          <div className="lg:col-span-7">
            <Reveal delayMs={45} className="flex flex-col gap-8">
              <p className="border-l-2 border-white pl-6 text-xl font-bold leading-snug text-white sm:text-2xl lg:text-3xl">
                {copy.honesty.lead}
              </p>

              <ul className="m-0 list-none p-0">
                {copy.honesty.points.map((point) => (
                  <li
                    key={point.code}
                    className="grid grid-cols-1 gap-2 border-t border-white/45 py-5 last:border-b sm:grid-cols-[4.5rem_1fr] sm:items-baseline sm:gap-6"
                  >
                    <span className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-white">
                      {point.code}
                    </span>
                    <span className="text-base font-medium leading-relaxed text-white sm:text-lg">{point.text}</span>
                  </li>
                ))}
              </ul>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 8: Diário de dúvidas (#F7F7F5 + AsciiSounding + Q-01..Q-05 em linhas 1px) ----------

function FaqSection() {
  return (
    <section id="faq" className="bg-surface text-ink">
      <div className="container-page grid grid-cols-1 gap-10 py-20 lg:grid-cols-12 lg:gap-12 lg:py-28">
        <div className="flex flex-col justify-between gap-8 lg:col-span-4">
          <Reveal>
            <SceneEyebrow text={copy.faq.eyebrow} />
            <h2 className="heading mt-4 text-3xl sm:text-5xl">{copy.faq.title}</h2>
          </Reveal>

          <div className="border border-ink bg-surface p-4">
            <AsciiSounding />
            <p className="mt-3 border-t border-ink/25 pt-2 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle">
              {copy.faq.caption}
            </p>
          </div>
        </div>

        <div className="lg:col-span-8">
          <Reveal delayMs={40}>
            {copy.faq.items.map((item) => (
              <details key={item.code} className="faq border-t border-ink last:border-b">
                <summary className="grid grid-cols-[3.5rem_1fr_auto] items-baseline gap-4 py-5 text-lg font-bold hover:text-accent">
                  <span className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-accent">
                    {item.code}
                  </span>
                  <span className="font-display text-xl font-extrabold">{item.q}</span>
                  <span aria-hidden="true" className="plus font-mono text-2xl font-normal leading-none">
                    +
                  </span>
                </summary>
                <p className="max-w-2xl pb-6 pl-[4.5rem] text-subtle">{item.a}</p>
              </details>
            ))}
          </Reveal>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 9: Ponto de referência (#0A0A0A + AsciiHorizon + wordmark gigante) -----------------

function ClosingSection() {
  const { me } = useAuth();
  const hasContact = CONTACT_URL.trim().length > 0;

  return (
    <section id="closing" className="overflow-hidden bg-ink text-white">
      <div className="container-page grid grid-cols-1 items-end gap-12 py-24 lg:grid-cols-12 lg:py-32">
        <div className="lg:col-span-7">
          <Reveal>
            <SceneEyebrow text={copy.closing.eyebrow} dark />
            <span aria-hidden="true" className="closing-dot mt-6 mb-6 block size-4 rounded-full bg-accent" />
            <Logo to={null} inverted size="text-6xl sm:text-8xl lg:text-[7.5rem]" />
            <p className="font-display mt-5 text-2xl font-extrabold leading-[1.06] tracking-[-0.03em] text-white sm:text-4xl">
              {copy.closing.tagline}
            </p>
            <p className="mt-4 max-w-lg text-[#D4D4D4]">{copy.closing.note}</p>

            <div className="mt-8 flex flex-wrap items-center gap-4">
              <LinkButton to={me ? "/app" : "/login"} variant="primary" size="lg">
                {me ? copy.nav.openPortal : copy.nav.login}
              </LinkButton>
              {hasContact && (
                <a href={CONTACT_URL} className="btn btn-ghost-dark btn-lg">
                  {copy.nav.contact}
                </a>
              )}
            </div>
          </Reveal>
        </div>

        <div className="border border-white/25 bg-[#0A0A0A] p-4 lg:col-span-5">
          <AsciiHorizon />
          <div aria-hidden="true" className="ruler-x-light mt-3" />
        </div>
      </div>
    </section>
  );
}

export function Landing() {
  return (
    <>
      <HeroIris />
      <HowItWorksSection />
      <WhatYouSeeSection />
      <PermissionsSection />
      <HonestySection />
      <AudienceSection />
      <FaqSection />
      <ClosingSection />
    </>
  );
}
