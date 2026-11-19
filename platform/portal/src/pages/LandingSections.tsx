import { useEffect, useRef, useState } from "react";
import { AsciiCompass, AsciiFresnel, AsciiSignalFlags, AsciiWaves } from "../AsciiArt";
import { copy } from "../copy";
import { Reveal } from "../Reveal";

export function SceneEyebrow({ text, dark = false }: { text: string; dark?: boolean }) {
  return (
    <p className={`eyebrow flex items-center gap-2.5 ${dark ? "!text-white/80" : ""}`}>
      <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
      {text}
    </p>
  );
}

export function CornerMarks({ dark = false }: { dark?: boolean }) {
  const tone = dark ? "text-white/75" : "text-ink";
  return (
    <>
      <span aria-hidden="true" className={`pointer-events-none absolute left-2 top-1.5 select-none font-mono text-xs leading-none ${tone}`}>
        +
      </span>
      <span aria-hidden="true" className={`pointer-events-none absolute right-2 top-1.5 select-none font-mono text-xs leading-none ${tone}`}>
        +
      </span>
      <span aria-hidden="true" className={`pointer-events-none absolute bottom-1.5 left-2 select-none font-mono text-xs leading-none ${tone}`}>
        +
      </span>
      <span aria-hidden="true" className={`pointer-events-none absolute bottom-1.5 right-2 select-none font-mono text-xs leading-none ${tone}`}>
        +
      </span>
    </>
  );
}

// ---- Cena 3: Rota de publicação (sticky desktop + numeral gigante + AsciiWaves) -------------

export function HowItWorksSection() {
  const [active, setActive] = useState(0);
  const stepRefs = useRef<(HTMLLIElement | null)[]>([]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const idx = Number((entry.target as HTMLElement).dataset.stepIndex);
            if (!Number.isNaN(idx)) setActive(idx);
          }
        }
      },
      { rootMargin: "-35% 0px -45% 0px", threshold: 0.05 },
    );

    for (const el of stepRefs.current) {
      if (el) io.observe(el);
    }
    return () => io.disconnect();
  }, []);

  const current = copy.howItWorks.steps[active] ?? copy.howItWorks.steps[0];

  return (
    <section id="how-it-works" className="border-b border-ink bg-paper text-ink">
      <div className="container-page py-20 lg:py-28">
        <Reveal className="max-w-4xl">
          <SceneEyebrow text={copy.howItWorks.eyebrow} />
          <h2 className="heading mt-4 text-4xl sm:text-5xl lg:text-6xl">{copy.howItWorks.title}</h2>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-12">
          <div className="lg:sticky lg:top-24 lg:col-span-5">
            <div className="relative border border-ink bg-paper p-6 sm:p-8">
              <CornerMarks />
              <div className="flex items-center justify-between gap-2 border-b border-ink pb-3 font-mono text-xs uppercase tracking-[0.08em] text-subtle">
                <span>{copy.howItWorks.stickyLabel}</span>
                <span className="font-semibold text-ink">{current.num} / 03</span>
              </div>

              <div className="py-6">
                <p
                  aria-hidden="true"
                  className="font-display text-[5.5rem] font-extrabold leading-none tracking-[-0.04em] text-ink sm:text-[7rem]"
                >
                  {current.num}
                  <span className="text-accent">.</span>
                </p>
                <p className="mt-4 font-mono text-xs font-semibold uppercase tracking-[0.08em] text-accent">
                  {current.meta}
                </p>
              </div>

              <div className="border-t border-ink pt-4">
                <AsciiWaves />
              </div>
            </div>
          </div>

          <ol className="m-0 list-none p-0 lg:col-span-7">
            {copy.howItWorks.steps.map((step, i) => {
              const isCurrent = i === active;
              return (
                <li
                  key={step.label}
                  data-step-index={i}
                  ref={(el) => {
                    stepRefs.current[i] = el;
                  }}
                  className="border-t border-ink py-10 first:pt-0 lg:py-14 lg:first:pt-0"
                >
                  <Reveal delayMs={i * 40} className="flex flex-col items-start gap-4">
                    <div className="flex w-full items-center justify-between gap-4">
                      <span className="font-mono text-xs font-semibold uppercase tracking-[0.1em] text-accent">
                        {step.label}
                      </span>
                      <span
                        className={`font-mono text-xs font-semibold uppercase tracking-[0.08em] ${
                          isCurrent ? "text-ink" : "text-subtle"
                        }`}
                      >
                        {step.meta}
                      </span>
                    </div>

                    <div className="flex items-baseline gap-5">
                      <span
                        aria-hidden="true"
                        className="font-display text-5xl font-extrabold leading-none tracking-[-0.04em] text-ink sm:text-6xl"
                      >
                        {step.num}
                      </span>
                      <h3 className="heading text-2xl sm:text-3xl lg:text-4xl">{step.title}</h3>
                    </div>

                    <p className="max-w-xl text-subtle">{step.text}</p>

                    {"command" in step && step.command && (
                      <code className="mt-2 inline-block border border-ink bg-surface px-4 py-2 font-mono text-sm font-semibold text-ink">
                        $ {step.command}
                      </code>
                    )}
                  </Reveal>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 4: Registro de bordo (#F7F7F5 + moldura 1px + + nos cantos + AsciiFresnel + tabela)

export function WhatYouSeeSection() {
  const h = copy.whatYouSee.headers;

  return (
    <section id="features" className="border-b border-ink bg-surface text-ink">
      <div className="container-page py-20 lg:py-28">
        <Reveal>
          <div className="relative border border-ink bg-paper">
            <CornerMarks />

            {/* Topo assimétrico: título grande + coordenada à esquerda | AsciiFresnel à direita */}
            <div className="grid grid-cols-1 border-b border-ink lg:grid-cols-12">
              <div className="flex flex-col justify-between gap-6 p-6 sm:p-10 lg:col-span-7">
                <div>
                  <SceneEyebrow text={copy.whatYouSee.eyebrow} />
                  <h2 className="heading mt-4 text-3xl sm:text-5xl lg:text-[3.5rem]">{copy.whatYouSee.title}</h2>
                </div>
                <div className="flex flex-col gap-3">
                  <div aria-hidden="true" className="ruler-x" />
                  <p className="font-mono text-xs font-medium uppercase tracking-[0.08em] text-subtle">
                    {copy.whatYouSee.coordinate}
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-center border-t border-ink bg-surface p-4 lg:col-span-5 lg:border-l lg:border-t-0">
                <AsciiFresnel />
              </div>
            </div>

            {/* Tabela de registro náutico (desktop: tabela tabular | mobile 375px: linhas estruturadas sem overflow) */}
            <div className="hidden md:block">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col" className="w-28">
                      {h.code}
                    </th>
                    <th scope="col" className="w-64">
                      {h.record}
                    </th>
                    <th scope="col">{h.delivery}</th>
                    <th scope="col" className="w-48">
                      {h.integrity}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {copy.whatYouSee.rows.map((row) => (
                    <tr key={row.code}>
                      <td className="font-mono text-xs font-semibold text-accent">{row.code}</td>
                      <th scope="row" className="font-display text-lg text-ink">
                        {row.record}
                      </th>
                      <td className="text-subtle">{row.delivery}</td>
                      <td className="font-mono text-xs font-semibold uppercase tracking-[0.06em] text-ink">
                        {row.integrity}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <ul className="m-0 list-none p-0 md:hidden">
              {copy.whatYouSee.rows.map((row) => (
                <li key={row.code} className="border-t border-ink p-5 first:border-t-0">
                  <div className="flex items-center justify-between gap-2 font-mono text-xs">
                    <span className="font-semibold text-accent">{row.code}</span>
                    <span className="font-semibold uppercase tracking-[0.05em] text-ink">{row.integrity}</span>
                  </div>
                  <p className="heading mt-2 text-xl">{row.record}</p>
                  <p className="mt-2 text-sm text-subtle">{row.delivery}</p>
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

// ---- Cena 5: Controle de alcance (#0A0A0A + árvore ASCII + AsciiCompass + 2 blocos regrados) -

export function PermissionsSection() {
  return (
    <section className="bg-ink text-white">
      <div className="container-page py-20 lg:py-28">
        <div className="grid grid-cols-1 gap-8 border-b border-white/25 pb-10 lg:grid-cols-12 lg:items-end">
          <div className="lg:col-span-8">
            <Reveal>
              <SceneEyebrow text={copy.permissions.eyebrow} dark />
              <h2 className="font-display mt-4 text-3xl font-extrabold leading-[1.03] tracking-[-0.035em] text-white sm:text-5xl lg:text-6xl">
                {copy.permissions.title}
              </h2>
              <p className="mt-5 max-w-2xl text-lg text-[#D4D4D4]">{copy.permissions.subtitle}</p>
            </Reveal>
          </div>

          <div className="lg:col-span-4 lg:text-right">
            <p className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-[#D4D4D4]">
              {copy.permissions.marginNote}
            </p>
          </div>
        </div>

        <div className="mt-12 grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-12">
          {/* Árvore ASCII sem cartões nem pílulas */}
          <div className="lg:col-span-6">
            <Reveal delayMs={40}>
              <div className="relative border border-white/30 bg-[#111111] p-6 sm:p-8">
                <CornerMarks dark />
                <p className="font-mono text-xs font-semibold uppercase tracking-[0.08em] text-[#D4D4D4]">
                  {copy.permissions.treeLabel}
                </p>

                <pre className="mt-6 overflow-x-auto border-y border-white/20 py-5 font-mono text-sm leading-7 text-white sm:text-base">
                  {copy.permissions.treeVisibleLines.join("\n")}
                  {"\n"}
                  <span className="text-[#A3A3A3] line-through">{copy.permissions.treeBlockedLine}</span>
                </pre>

                <p className="mt-4 font-mono text-xs text-[#D4D4D4]">{copy.permissions.treeCaption}</p>
              </div>
            </Reveal>
          </div>

          {/* Rosa dos ventos ASCII + 2 blocos regrados sem cartões */}
          <div className="flex flex-col gap-8 lg:col-span-6">
            <div className="border border-white/25 bg-[#0A0A0A] p-3">
              <AsciiCompass />
            </div>

            <div className="flex flex-col">
              {copy.permissions.roles.map((role, i) => (
                <Reveal key={role.title} delayMs={i * 50} className="border-t border-white/25 py-6 first:pt-2">
                  <p className="flex items-center gap-2.5 font-mono text-xs font-semibold uppercase tracking-[0.08em] text-white">
                    <span aria-hidden="true" className="size-2 shrink-0 bg-accent" />
                    {role.code}
                  </p>
                  <h3 className="font-display mt-2 text-2xl font-extrabold tracking-[-0.025em] text-white">
                    {role.title}
                  </h3>
                  <p className="mt-2 max-w-xl text-[#D4D4D4]">{role.text}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ---- Cena 7: Tripulação (#FFFFFF assimétrico + AsciiSignalFlags + numerais gigantes 01-03) ---

export function AudienceSection() {
  return (
    <section className="border-b border-ink bg-paper text-ink">
      <div className="container-page grid grid-cols-1 gap-10 py-20 lg:grid-cols-12 lg:gap-12 lg:py-28">
        <div className="flex flex-col justify-between gap-8 lg:col-span-4">
          <Reveal>
            <SceneEyebrow text={copy.audience.eyebrow} />
            <h2 className="heading mt-4 text-3xl sm:text-5xl">{copy.audience.title}</h2>
          </Reveal>

          <div className="border border-ink bg-paper p-4">
            <AsciiSignalFlags />
            <p className="mt-3 border-t border-line pt-2 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle">
              {copy.audience.caption}
            </p>
          </div>
        </div>

        <ol className="m-0 list-none p-0 lg:col-span-8">
          {copy.audience.items.map((item, i) => (
            <li key={item.num} className="border-t border-ink py-8 last:border-b">
              <Reveal
                delayMs={i * 45}
                className="grid grid-cols-1 items-baseline gap-4 sm:grid-cols-[7.5rem_1fr] sm:gap-8"
              >
                <span
                  aria-hidden="true"
                  className="font-display text-6xl font-extrabold leading-none tracking-[-0.04em] text-ink sm:text-7xl"
                >
                  {item.num}
                </span>
                <div>
                  <h3 className="heading text-2xl sm:text-3xl">{item.title}</h3>
                  <p className="mt-3 max-w-xl text-subtle">{item.text}</p>
                </div>
              </Reveal>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
