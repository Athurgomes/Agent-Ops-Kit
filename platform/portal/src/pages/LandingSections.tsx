import type { ReactNode } from "react";
import { copy } from "../copy";
import { Reveal } from "../Reveal";

export function SceneEyebrow({ text }: { text: string }) {
  return (
    <p className="eyebrow flex items-center gap-2.5">
      <span aria-hidden="true" className="size-2 rounded-full bg-accent" />
      {text}
    </p>
  );
}

// ---- Cena 3: Como funciona -------------------------------------------------------------------

const STEP_ART: ReactNode[] = [
  <>
    {"+-----------------------+\n"}
    {`| ${copy.howItWorks.art.step1Title.padEnd(21)} |\n`}
    {"| "}
    <span className="font-semibold text-accent">[eval]</span>
    {"  "}
    <span className="font-semibold text-accent">[red-team]</span>
    {"    |\n"}
    {"+-----------+-----------+\n"}
    {"            "}
    <span className="font-bold text-accent">v</span>
  </>,
  <>
    {"+-----------------------+\n"}
    {"| "}
    <span className="font-semibold text-ink">md</span>
    {"   "}
    <span className="font-semibold text-ink">html</span>
    {"   "}
    <span className="font-semibold text-ink">json</span>
    {"      |\n"}
    {"| "}
    <span className="font-semibold text-accent">sha256</span>
    {` + ${copy.howItWorks.art.step2Caveats.padEnd(13)}|\n`}
    {"+-----------+-----------+\n"}
    {"            "}
    <span className="font-bold text-accent">v</span>
  </>,
  <>
    {"+-----------------------+\n"}
    {"| "}
    <span className="font-semibold text-ink">{copy.brand.name}</span>
    <span className="font-bold text-accent">{copy.brand.dot}</span>
    {` / ${copy.howItWorks.art.step3Area.padEnd(13)}|\n`}
    {"| "}
    <span className="font-semibold text-accent">(o)</span>
    {` ${copy.howItWorks.art.step3TrafficLight.padEnd(18)}|\n`}
    {"| "}
    <span className="font-semibold text-ink">[v]</span>
    {` ${copy.howItWorks.art.step3Downloads.padEnd(18)}|\n`}
    {"+-----------------------+"}
  </>,
];

export function HowItWorksSection() {
  return (
    <section id="how-it-works">
      <div className="container-page py-20 lg:py-24">
        <Reveal className="max-w-3xl">
          <SceneEyebrow text={copy.howItWorks.eyebrow} />
          <h2 className="heading mt-4 text-3xl sm:text-4xl lg:text-5xl">{copy.howItWorks.title}</h2>
        </Reveal>

        <ol className="m-0 mt-12 grid list-none grid-cols-1 gap-8 p-0 md:grid-cols-3">
          {copy.howItWorks.steps.map((step, i) => (
            <li key={step.label}>
              <Reveal delayMs={i * 50} className="flex h-full flex-col items-start gap-4 border-t border-line pt-6">
                <span className="font-mono text-xs font-semibold uppercase tracking-[0.1em] text-accent">
                  {step.label}
                </span>
                <pre
                  aria-hidden="true"
                  className="m-0 w-full overflow-x-auto rounded-xl border border-line bg-surface px-4 py-3 font-mono text-xs leading-5 text-subtle"
                >
                  {STEP_ART[i]}
                </pre>
                <h3 className="heading text-xl lg:text-2xl">{step.title}</h3>
                <p className="text-subtle">{step.text}</p>
                {"command" in step && step.command && (
                  <code className="mt-auto rounded-lg border border-line bg-surface px-3 py-1.5 font-mono text-sm font-semibold text-ink">
                    {step.command}
                  </code>
                )}
              </Reveal>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ---- Cena 4: O que você vê (mockup + 4 pontos) -----------------------------------------------

const BLOCK_COLUMNS = [
  { label: copy.whatYouSee.mockup.chartColumns[0], baseBlocks: 4, guardBlocks: 4 },
  { label: copy.whatYouSee.mockup.chartColumns[1], baseBlocks: 2, guardBlocks: 4 },
  { label: copy.whatYouSee.mockup.chartColumns[2], baseBlocks: 3, guardBlocks: 3 },
  { label: copy.whatYouSee.mockup.chartColumns[3], baseBlocks: 3, guardBlocks: 4 },
];

function BlockStack({ count, tone }: { count: number; tone: "ink" | "accent" }) {
  const fill = tone === "accent" ? "bg-accent" : "bg-ink";
  return (
    <div className="flex w-3.5 flex-col-reverse gap-1">
      {Array.from({ length: 5 }).map((_, idx) => (
        <span
          key={idx}
          className={`block h-2 w-full rounded-[2px] ${idx < count ? fill : "bg-hair/70"}`}
        />
      ))}
    </div>
  );
}

function PortalMockup() {
  const m = copy.whatYouSee.mockup;
  return (
    <figure className="m-0">
      <div className="box overflow-hidden">
        <div className="rule-b flex flex-wrap items-center justify-between gap-2 bg-surface px-5 py-3">
          <div className="flex items-center gap-2 font-mono text-xs font-bold text-ink">
            <span aria-hidden="true" className="size-2 rounded-full bg-accent" />
            <span>{copy.brand.full}</span>
          </div>
          <span className="rounded-full border border-line bg-paper px-3 py-0.5 font-mono text-[11px] font-semibold text-subtle">
            {m.badge}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-[190px_1fr]">
          <div className="border-b border-line bg-surface/60 p-4 sm:border-b-0 sm:border-r">
            <p className="px-2 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle">
              {m.areaParent}
            </p>
            <div className="mt-1.5 rounded-lg bg-accent-soft px-3 py-1.5 text-sm font-bold text-accent">
              {m.areaActive}
            </div>
            <div className="mt-2 px-3 py-1 text-sm text-subtle">{m.areaOther}</div>
            <div aria-hidden="true" className="my-3 h-px bg-line" />
            <div className="px-3 py-1 text-sm font-medium text-subtle">{m.navDownloads}</div>
          </div>

          <div className="flex flex-col gap-5 p-5 sm:p-6">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-mono text-xs text-subtle">{m.breadcrumb}</p>
                <span className="inline-flex items-center rounded-full border border-amber-500/35 bg-amber-500/10 px-3 py-1 text-xs font-bold text-amber-900">
                  {m.trafficLight}
                </span>
              </div>
              <p className="heading mt-2 text-xl sm:text-2xl">{m.reportTitle}</p>
            </div>

            <div aria-hidden="true" className="rounded-xl border border-line bg-surface p-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-xs text-subtle">
                <span className="font-mono font-semibold">{m.chartLabel}</span>
                <div className="flex items-center gap-3">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-2.5 rounded-[2px] bg-ink" />
                    {m.legendBase}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-2.5 rounded-[2px] bg-accent" />
                    {m.legendGuardrails}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-4 gap-3">
                {BLOCK_COLUMNS.map((col) => (
                  <div key={col.label} className="flex flex-col items-center gap-2">
                    <div className="flex items-end gap-1.5">
                      <BlockStack count={col.baseBlocks} tone="ink" />
                      <BlockStack count={col.guardBlocks} tone="accent" />
                    </div>
                    <span className="font-mono text-[11px] text-subtle">{col.label}</span>
                  </div>
                ))}
              </div>
            </div>

            <p className="border-l-2 border-accent pl-3 text-xs leading-relaxed text-subtle">{m.caveatNote}</p>

            <div className="flex flex-wrap items-center gap-2.5">
              <span aria-disabled="true" className="btn btn-secondary btn-sm pointer-events-none select-none">
                {m.downloadHtml}
              </span>
              <span aria-disabled="true" className="btn btn-secondary btn-sm pointer-events-none select-none">
                {m.downloadMd}
              </span>
            </div>

            <p className="font-mono text-[11px] text-subtle">{m.downloadNote}</p>
          </div>
        </div>
      </div>
    </figure>
  );
}

export function WhatYouSeeSection() {
  return (
    <section id="features">
      <div className="container-page py-20 lg:py-24">
        <Reveal className="max-w-3xl">
          <SceneEyebrow text={copy.whatYouSee.eyebrow} />
          <h2 className="heading mt-4 text-3xl sm:text-4xl lg:text-5xl">{copy.whatYouSee.title}</h2>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-12">
          <div className="lg:col-span-7">
            <Reveal delayMs={40}>
              <PortalMockup />
            </Reveal>
          </div>

          <ol className="m-0 list-none p-0 lg:col-span-5">
            {copy.whatYouSee.points.map((pt, i) => (
              <li key={pt.title}>
                <Reveal
                  delayMs={i * 45}
                  className="rule-t grid grid-cols-[2.5rem_1fr] gap-3 py-5 first:border-t-0 lg:first:pt-0"
                >
                  <span className="font-mono text-sm font-bold text-accent">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <h3 className="heading text-lg lg:text-xl">{pt.title}</h3>
                    <p className="mt-1.5 text-subtle">{pt.text}</p>
                  </div>
                </Reveal>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 5: Quem enxerga o quê ---------------------------------------------------------------

export function PermissionsSection() {
  return (
    <section>
      <div className="container-page py-20 lg:py-24">
        <Reveal className="max-w-3xl">
          <SceneEyebrow text={copy.permissions.eyebrow} />
          <h2 className="heading mt-4 text-3xl sm:text-4xl lg:text-5xl">{copy.permissions.title}</h2>
          <p className="mt-4 max-w-2xl text-lg text-subtle">{copy.permissions.subtitle}</p>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-12">
          <div className="lg:col-span-5">
            <Reveal delayMs={40}>
              <div className="rounded-[var(--radius-panel)] border border-line bg-surface p-6">
                <p className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-subtle">
                  {copy.permissions.treeLabel}
                </p>

                <div className="mt-5 flex flex-col gap-2.5 font-mono text-sm">
                  <div className="flex items-center justify-between rounded-xl bg-accent-soft px-4 py-2.5 font-bold text-accent">
                    <span>{copy.permissions.treeAreas.root}</span>
                    <span className="text-xs font-semibold">{copy.permissions.visibleTag}</span>
                  </div>

                  <div className="ml-4 flex flex-col gap-2 border-l-2 border-accent/40 pl-4">
                    {copy.permissions.treeAreas.children.map((child) => (
                      <div
                        key={child}
                        className="flex items-center justify-between rounded-lg bg-accent-soft/70 px-3 py-2 font-semibold text-accent"
                      >
                        <span>{child}</span>
                        <span className="text-xs">{copy.permissions.visibleTag}</span>
                      </div>
                    ))}
                  </div>

                  <div className="mt-1 flex items-center justify-between rounded-xl border border-dashed border-line px-4 py-2.5 text-subtle">
                    <span>{copy.permissions.treeAreas.other}</span>
                    <span className="text-xs">{copy.permissions.hiddenTag}</span>
                  </div>
                </div>

                <p className="mt-5 text-xs text-subtle">{copy.permissions.treeCaption}</p>
              </div>
            </Reveal>
          </div>

          <div className="flex flex-col gap-6 lg:col-span-7">
            {copy.permissions.roles.map((role, i) => (
              <Reveal
                key={role.title}
                delayMs={i * 55}
                className="rule-t pt-6 first:border-t-0 lg:first:pt-0"
              >
                <h3 className="heading text-xl lg:text-2xl">{role.title}</h3>
                <p className="mt-2 max-w-xl text-subtle">{role.text}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 7: Para quem é ---------------------------------------------------------------------

export function AudienceSection() {
  return (
    <section>
      <div className="container-page py-20 lg:py-24">
        <Reveal className="max-w-3xl">
          <SceneEyebrow text={copy.audience.eyebrow} />
          <h2 className="heading mt-4 text-3xl sm:text-4xl lg:text-5xl">{copy.audience.title}</h2>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
          {copy.audience.cards.map((card, i) => (
            <Reveal
              key={card.title}
              delayMs={i * 50}
              className="flex h-full flex-col rounded-[var(--radius-panel)] border border-line bg-surface p-7"
            >
              <span className="font-mono text-xs font-bold text-accent">{String(i + 1).padStart(2, "0")}</span>
              <h3 className="heading mt-4 text-xl">{card.title}</h3>
              <p className="mt-3 text-subtle">{card.text}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
