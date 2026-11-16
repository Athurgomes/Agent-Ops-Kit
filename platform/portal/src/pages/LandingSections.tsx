import type { ReactNode } from "react";
import { BRAND, REPO_URL } from "../brand";

function Mark({ children }: { children: ReactNode }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}
const CheckMark = () => (
  <Mark>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Mark>
);
const CrossMark = () => (
  <Mark>
    <path d="M6 6l12 12M18 6L6 18" />
  </Mark>
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
    <section className="rule-t">
      <div className="container-page py-24">
        <h2 className="heading max-w-3xl text-4xl lg:text-5xl">From scattered test runs to one clear picture</h2>
        <div className="box mt-12 grid grid-cols-1 md:grid-cols-2">
          <div className="p-8 lg:p-12">
            <p className="mb-8 text-sm font-extrabold text-subtle">Before</p>
            <ul className="m-0 flex list-none flex-col gap-5 p-0 text-lg text-subtle">
              {BEFORE.map((t) => (
                <li key={t} className="flex items-start gap-3">
                  <span className="mt-1.5">
                    <CrossMark />
                  </span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <div className="rule-t p-8 md:border-l md:border-t-0 md:border-ink lg:p-12">
            <p className="mb-8 inline-block border-b-2 border-accent text-sm font-extrabold">With {BRAND}</p>
            <ul className="m-0 flex list-none flex-col gap-5 p-0 text-lg font-semibold">
              {AFTER.map((t) => (
                <li key={t} className="flex items-start gap-3">
                  <span className="mt-1.5 text-accent">
                    <CheckMark />
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
    <div className="box">
      <p className="rule-b px-4 py-2 font-mono text-sm font-bold">terminal</p>
      <pre className="m-0 overflow-x-auto p-6 font-mono text-sm leading-7">
        <span className="text-subtle"># the agent token stays in the environment</span>
        {"\n"}$ export AOK_PLATFORM_TOKEN="&lt;agent token&gt;"
        {"\n\n"}
        <span className="text-subtle"># test where the agent runs, then publish</span>
        {"\n"}$ aok check --config agent.yaml \{"\n"}    --publish https://&lt;your-platform&gt; \{"\n"}    --agent-id my-agent
      </pre>
    </div>
  );
}

function MockReportCard() {
  return (
    <figure className="m-0">
      <div className="box p-6">
        <div className="mb-6 flex items-center justify-between gap-4">
          <span className="border border-ink px-2 py-0.5 text-sm font-semibold">Illustrative example</span>
          <span className="text-sm text-subtle">Version 2</span>
        </div>
        <p className="heading text-2xl">Agent name</p>
        <p className="mb-6 text-sm text-subtle">Area · Sub-area</p>
        <dl className="m-0 mb-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-subtle">Generated</dt>
          <dd className="m-0">mm/dd/yyyy, hh:mm</dd>
          <dt className="text-subtle">Published</dt>
          <dd className="m-0">mm/dd/yyyy, hh:mm</dd>
        </dl>
        <div aria-hidden="true" className="mb-6 flex flex-col gap-2">
          <div className="h-2.5 w-full bg-hair" />
          <div className="h-2.5 w-5/6 bg-hair" />
          <div className="h-2.5 w-2/3 bg-hair" />
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
    <section className="rule-t">
      <div className="container-page py-24">
        <h2 className="heading max-w-3xl text-4xl lg:text-5xl">Reports from every agent, wherever it runs</h2>
        <p className="mt-6 max-w-2xl text-xl text-subtle">
          The kit tests your agent where it runs, on a laptop or in CI, and publishes the result. {BRAND} shows it to
          the people who need to read it.
        </p>
        <div className="mt-12 grid grid-cols-1 items-start gap-12 lg:grid-cols-2">
          <div className="flex flex-col gap-6">
            <Terminal />
            <ol className="m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-2 p-0 text-sm font-bold">
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
        <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="link">
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
    <section className="rule-t">
      <div className="container-page grid grid-cols-1 gap-x-0 gap-y-12 py-24 lg:grid-cols-2 lg:gap-x-12">
        <div>
          <h2 className="heading text-4xl lg:text-5xl">Don't take our word for it. Check it.</h2>
          <ol className="m-0 mt-12 list-none p-0">
            {PROOF.map((p, i) => (
              <li key={p.title} className="rule-t grid grid-cols-[3rem_1fr] gap-4 py-6">
                <span className="font-mono text-sm font-bold text-subtle">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <h3 className="heading text-xl">{p.title}</h3>
                  <p className="mt-2 text-subtle">{p.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <div className="flex flex-col gap-6 lg:pt-3">
          {/* TODO(Arthur): review and edit this founder's note before publishing. It is an honest DRAFT. */}
          <figure className="box m-0 p-8">
            <p className="mb-4 text-sm font-extrabold">Founder's note</p>
            <blockquote className="m-0 text-lg">
              <p>
                AI agents are going into use faster than we can say what they did, or whether they hold up against
                simple attacks. I built {BRAND} so the people who decide can read that evidence next to its caveats, in
                plain language, and so the teams building agents have one honest place to publish it.
              </p>
              <p className="mt-4">It is a small open-source project, and it tries to tell you what it does not know.</p>
            </blockquote>
            <figcaption className="mt-6 text-sm font-bold">Founder, {BRAND}</figcaption>
          </figure>
          {/* Placeholder only: NOT a real customer quote. Replace with real feedback, with permission, when it exists. */}
          <figure className="m-0 border border-dashed border-ink p-8">
            <p className="mb-4 inline-block border border-ink px-2 py-0.5 text-sm font-bold">
              Placeholder — not a real customer quote
            </p>
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
