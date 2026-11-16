import type { ReactNode } from "react";
import { BRAND, REPO_URL } from "../brand";

function Svg({ children, className = "size-5 shrink-0" }: { children: ReactNode; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}
const CheckIcon = () => (
  <Svg>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);
const CrossIcon = () => (
  <Svg>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
);

// ---- before / after --------------------------------------------------------------------------

const BEFORE = [
  "Test results spread across terminals and CI logs",
  "The people who decide never see them",
  "Caveats get lost on the way",
];
const AFTER = [
  "One versioned report per agent",
  "Organized by area, with access by area",
  "Caveats and the traffic light on every report page",
  "A log of every download",
];

export function BeforeAfter() {
  return (
    <section className="border-y border-line bg-soft">
      <div className="container-page py-24">
        <h2 className="heading max-w-3xl text-4xl lg:text-5xl">From scattered test runs to one clear picture</h2>
        <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="rounded-3xl border border-line bg-paper p-8">
            <p className="mb-6 text-sm font-semibold uppercase tracking-wide text-subtle">Before</p>
            <ul className="m-0 flex list-none flex-col gap-4 p-0 text-lg text-subtle">
              {BEFORE.map((t) => (
                <li key={t} className="flex items-start gap-3">
                  <span className="mt-1 text-[#94a3b8]">
                    <CrossIcon />
                  </span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-3xl border border-accent bg-paper p-8 shadow-[var(--shadow-soft)]">
            <p className="mb-6 text-sm font-semibold uppercase tracking-wide text-accent">With {BRAND}</p>
            <ul className="m-0 flex list-none flex-col gap-4 p-0 text-lg font-medium text-navy">
              {AFTER.map((t) => (
                <li key={t} className="flex items-start gap-3">
                  <span className="mt-1 text-accent">
                    <CheckIcon />
                  </span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

// ---- showcase: terminal + illustrative report card -------------------------------------------

function Terminal() {
  return (
    <div className="overflow-hidden rounded-2xl bg-navy text-[#dbeafe] shadow-[var(--shadow-soft)]">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3" aria-hidden="true">
        <span className="size-3 rounded-full bg-white/20" />
        <span className="size-3 rounded-full bg-white/20" />
        <span className="size-3 rounded-full bg-white/20" />
      </div>
      <pre className="m-0 overflow-x-auto p-6 font-mono text-sm leading-7">
        <span className="text-[#93b4f8]"># the agent token stays in the environment</span>
        {"\n"}$ export AOK_PLATFORM_TOKEN="&lt;agent token&gt;"
        {"\n\n"}
        <span className="text-[#93b4f8]"># test where the agent runs, then publish</span>
        {"\n"}$ aok check --config agent.yaml \{"\n"}    --publish https://&lt;your-platform&gt; \{"\n"}    --agent-id my-agent
      </pre>
    </div>
  );
}

function MockReportCard() {
  return (
    <figure className="m-0">
      <div className="card card-soft p-6">
        <div className="mb-4 flex items-center justify-between gap-4">
          <span className="rounded-full bg-tint px-3 py-1 text-sm font-semibold text-navy">Illustrative example</span>
          <span className="text-sm text-subtle">Version 2</span>
        </div>
        <p className="text-xl font-bold text-navy">Agent name</p>
        <p className="mb-4 text-sm text-subtle">Area · Sub-area</p>
        <dl className="m-0 mb-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-subtle">Generated</dt>
          <dd className="m-0">mm/dd/yyyy, hh:mm</dd>
          <dt className="text-subtle">Published</dt>
          <dd className="m-0">mm/dd/yyyy, hh:mm</dd>
        </dl>
        <div aria-hidden="true" className="mb-6 flex flex-col gap-2">
          <div className="h-3 w-full rounded-full bg-line" />
          <div className="h-3 w-5/6 rounded-full bg-line" />
          <div className="h-3 w-2/3 rounded-full bg-line" />
        </div>
        <div aria-hidden="true" className="flex gap-3">
          <span className="btn btn-secondary btn-sm">Download MD</span>
          <span className="btn btn-secondary btn-sm">Download HTML</span>
        </div>
      </div>
      <figcaption className="mt-4 text-sm text-subtle">Illustrative example: layout only, no real data.</figcaption>
    </figure>
  );
}

export function Showcase() {
  return (
    <section className="container-page py-24">
      <h2 className="heading max-w-3xl text-4xl lg:text-5xl">Reports from every agent, wherever it runs</h2>
      <p className="mt-6 max-w-2xl text-xl text-subtle">
        The kit tests your agent where it runs, on a laptop or in CI, and publishes the result. {BRAND} shows it to the
        people who need to read it.
      </p>
      <div className="mt-12 grid grid-cols-1 items-start gap-12 lg:grid-cols-2">
        <div className="flex flex-col gap-6">
          <Terminal />
          <ol className="m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-2 p-0 text-sm font-semibold text-navy">
            <li>Test where it runs</li>
            <li aria-hidden="true" className="text-accent">
              →
            </li>
            <li>
              <code className="font-mono">aok check --publish</code>
            </li>
            <li aria-hidden="true" className="text-accent">
              →
            </li>
            <li>Shows up in the portal</li>
          </ol>
        </div>
        <MockReportCard />
      </div>
    </section>
  );
}

// ---- proof -----------------------------------------------------------------------------------

const PROOF: { title: string; text: ReactNode }[] = [
  {
    title: "Open source",
    text: (
      <>
        The kit and this portal are MIT-licensed and public on{" "}
        <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="font-semibold text-accent">
          GitHub
        </a>
        . Read the code, not just the claims.
      </>
    ),
  },
  {
    title: "Reproducible numbers",
    text: "Results come from recorded runs with a fixed seed. The report commands read those runs without calling the model, so you can regenerate the same report.",
  },
  {
    title: "Hashes and a chained audit log",
    text: "Every report file has a SHA-256 hash, and the audit log is hash-chained. There is no signature: a chain only reveals edits if you kept the anchor hash somewhere else.",
  },
];

export function Proof() {
  return (
    <section className="border-t border-line bg-soft">
      <div className="container-page grid grid-cols-1 gap-x-0 gap-y-12 py-24 lg:grid-cols-2 lg:gap-x-12">
        <div>
          <h2 className="heading text-4xl lg:text-5xl">Don't take our word for it. Check it.</h2>
          <ul className="m-0 mt-12 flex list-none flex-col gap-8 p-0">
            {PROOF.map((p) => (
              <li key={p.title} className="flex gap-4">
                <span className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-tint-2 text-navy">
                  <CheckIcon />
                </span>
                <div>
                  <h3 className="heading text-xl">{p.title}</h3>
                  <p className="mt-1 text-subtle">{p.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-6">
          {/* TODO(Arthur): review and edit this founder's note before publishing. It is an honest DRAFT. */}
          <figure className="card m-0 p-8">
            <p className="mb-4 text-sm font-semibold uppercase tracking-wide text-accent">Founder's note</p>
            <blockquote className="m-0 text-lg text-navy">
              <p>
                AI agents are going into use faster than we can say what they did, or whether they hold up against
                simple attacks. I built {BRAND} so the people who decide can read that evidence next to its caveats, in
                plain language, and so the teams building agents have one honest place to publish it.
              </p>
              <p className="mt-4">It is a small open-source project, and it tries to tell you what it does not know.</p>
            </blockquote>
            <figcaption className="mt-6 text-sm font-semibold text-subtle">Founder, {BRAND}</figcaption>
          </figure>
          {/* Placeholder only: NOT a real customer quote. Replace with real feedback, with permission, when it exists. */}
          <figure className="m-0 rounded-[20px] border border-dashed border-[#94a3b8] bg-paper p-8">
            <span className="mb-4 inline-block rounded-full bg-[#fef3c7] px-3 py-1 text-sm font-semibold text-[#78350f]">
              Placeholder — not a real customer quote
            </span>
            <blockquote className="m-0 text-lg text-subtle">
              “One place to see how each of our agents was tested, and what those tests could not cover.”
            </blockquote>
            <figcaption className="mt-6 text-sm text-subtle">Sample text, no real person or company.</figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}
