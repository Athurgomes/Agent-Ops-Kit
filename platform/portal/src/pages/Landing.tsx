import { useAuth } from "../auth";
import { CONTACT_URL } from "../brand";
import { copy } from "../copy";
import { Reveal, SectionDivider } from "../Reveal";
import { LinkButton, Logo } from "../ui";
import { HeroIris } from "./HeroIris";
import {
  AudienceSection,
  HowItWorksSection,
  PermissionsSection,
  SceneEyebrow,
  WhatYouSeeSection,
} from "./LandingSections";

// ---- Cena 6: Honestidade ---------------------------------------------------------------------

function HonestySection() {
  return (
    <section id="limits">
      <div className="container-page grid grid-cols-12 gap-x-0 gap-y-8 py-20 lg:gap-x-12 lg:py-24">
        <div className="col-span-12 lg:col-span-4">
          <Reveal>
            <SceneEyebrow text={copy.honesty.eyebrow} />
            <h2 className="heading mt-4 text-3xl sm:text-4xl lg:text-5xl">{copy.honesty.title}</h2>
          </Reveal>
        </div>

        <div className="col-span-12 lg:col-span-8">
          <Reveal delayMs={50} className="flex flex-col gap-6">
            <p className="border-l-4 border-accent pl-6 text-2xl font-bold leading-snug text-ink lg:text-3xl">
              {copy.honesty.lead}
            </p>
            <ul className="m-0 flex list-none flex-col gap-3 pl-7 text-subtle">
              {copy.honesty.points.map((point) => (
                <li key={point} className="relative pl-4">
                  <span aria-hidden="true" className="absolute left-0 top-2.5 size-1.5 rounded-full bg-accent" />
                  {point}
                </li>
              ))}
            </ul>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 8: Perguntas frequentes ------------------------------------------------------------

function FaqSection() {
  return (
    <section id="faq">
      <div className="container-page grid grid-cols-12 gap-x-0 gap-y-10 py-20 lg:gap-x-12 lg:py-24">
        <div className="col-span-12 lg:col-span-4">
          <Reveal>
            <SceneEyebrow text={copy.faq.eyebrow} />
            <h2 className="heading mt-4 text-3xl sm:text-4xl lg:text-5xl">{copy.faq.title}</h2>
          </Reveal>
        </div>

        <div className="col-span-12 lg:col-span-8">
          <Reveal delayMs={40}>
            {copy.faq.items.map((item) => (
              <details key={item.q} className="faq rule-t first:border-t last:border-b last:border-line">
                <summary className="flex items-center justify-between gap-4 py-5 text-lg font-extrabold hover:text-accent">
                  {item.q}
                  <span aria-hidden="true" className="plus text-2xl font-normal leading-none">
                    +
                  </span>
                </summary>
                <p className="max-w-2xl pb-6 text-subtle">{item.a}</p>
              </details>
            ))}
          </Reveal>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 9: Fecho de assinatura -------------------------------------------------------------

function ClosingSection() {
  const { me } = useAuth();
  const hasContact = CONTACT_URL.trim().length > 0;

  return (
    <section id="closing" className="aura-light overflow-hidden">
      <div className="container-page relative z-10 py-24 sm:py-32">
        <Reveal>
          <span aria-hidden="true" className="closing-dot mb-6 block size-3.5 rounded-full bg-accent" />
          <Logo to={null} size="text-6xl sm:text-7xl lg:text-8xl" />
          <p className="heading mt-5 text-2xl sm:text-3xl lg:text-4xl">{copy.closing.tagline}</p>
          <p className="mt-4 max-w-lg text-subtle">{copy.closing.note}</p>

          <div className="mt-8 flex flex-wrap items-center gap-4">
            <LinkButton to={me ? "/app" : "/login"} variant="primary" size="lg">
              {me ? copy.nav.openPortal : copy.nav.login}
            </LinkButton>
            {hasContact && (
              <a href={CONTACT_URL} className="btn btn-secondary btn-lg">
                {copy.nav.contact}
              </a>
            )}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function Landing() {
  return (
    <>
      <HeroIris />
      <SectionDivider />
      <HowItWorksSection />
      <SectionDivider />
      <WhatYouSeeSection />
      <SectionDivider />
      <PermissionsSection />
      <SectionDivider />
      <HonestySection />
      <SectionDivider />
      <AudienceSection />
      <SectionDivider />
      <FaqSection />
      <SectionDivider />
      <ClosingSection />
    </>
  );
}
