import type { ReactNode } from "react";
import { BRAND, BRAND_TAGLINE } from "../brand";
import { LIMITS_TEXT, SELF_DECLARED_TEXT } from "../format";
import { LinkButton, SoonButton } from "../ui";
import { BeforeAfter, Proof, Showcase } from "./LandingSections";

// ---- plain line icons (no containers) --------------------------------------------------------

function Icon({ children, className = "size-7" }: { children: ReactNode; className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}
const AgentIcon = () => (
  <Icon>
    <rect x="4" y="8" width="16" height="11" rx="2" />
    <path d="M12 8V4.5M10.5 4.5h3" />
    <circle cx="9" cy="13.5" r="1" />
    <circle cx="15" cy="13.5" r="1" />
    <path d="M9.5 16.5h5" />
  </Icon>
);
const TestIcon = () => (
  <Icon>
    <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
    <path d="M9 12l2 2 4-4" />
  </Icon>
);
const ReportIcon = () => (
  <Icon>
    <path d="M7 3h7l4 4v14H7z" />
    <path d="M14 3v4h4M10 12h5M10 16h5" />
  </Icon>
);

// ---- hero ------------------------------------------------------------------------------------

function FlowRow({ n, icon, title, text }: { n: string; icon: ReactNode; title: string; text: string }) {
  return (
    <li className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-4 py-5">
      <span className="font-mono text-sm font-bold text-subtle">{n}</span>
      <div>
        <p className="text-lg font-extrabold">{title}</p>
        <p className="text-sm text-subtle">{text}</p>
      </div>
      {icon}
    </li>
  );
}

function AgentFlow() {
  return (
    <figure className="m-0">
      <div className="box">
        <p className="rule-b px-6 py-4 text-sm font-extrabold">AI agent → tested → report</p>
        <ol className="m-0 list-none divide-y divide-ink p-0 px-6">
          <FlowRow n="01" icon={<AgentIcon />} title="Your AI agent" text="Runs where your team runs it." />
          <FlowRow n="02" icon={<TestIcon />} title="Tested" text="Quality evaluation and red-team attacks." />
          <FlowRow n="03" icon={<ReportIcon />} title="Report" text="Published here, with its caveats." />
        </ol>
      </div>
      <figcaption className="mt-4 text-sm text-subtle">
        Illustrative diagram. {BRAND} never runs your agent; it only stores and shows the report your team publishes.
      </figcaption>
    </figure>
  );
}

function Hero() {
  return (
    <div className="container-page grid grid-cols-12 items-end gap-x-0 gap-y-12 py-24 lg:gap-x-12">
      <div className="col-span-12 flex flex-col items-start gap-8 lg:col-span-7">
        <p className="text-sm font-extrabold">{BRAND_TAGLINE}</p>
        <h1 className="heading text-5xl sm:text-6xl lg:text-7xl">
          See what your AI agents were tested for. Read what was left out.
        </h1>
        <p className="max-w-xl text-xl text-subtle">
          {BRAND} gathers the test reports of your AI agents by area, with every result and every caveat in the same
          place.
        </p>
        <div className="flex flex-wrap items-center gap-4 pt-2">
          <LinkButton to="/login" variant="primary" size="lg">
            Log In
          </LinkButton>
          <a href="#how-it-works" className="btn btn-secondary btn-lg">
            How it works
          </a>
        </div>
      </div>
      <div className="col-span-12 lg:col-span-5">
        <AgentFlow />
      </div>
    </div>
  );
}

// ---- features: a ruled list, not a grid of cards ---------------------------------------------

const FEATURES = [
  {
    title: "An agent registry by area",
    text: "Every agent belongs to an area. Access to an area covers its sub-areas, and never the areas above it.",
  },
  {
    title: "Versioned agent reports",
    text: "Each publication becomes a numbered version that the API cannot edit or delete. The latest one is highlighted.",
  },
  {
    title: "A log of every download",
    text: "Each download records who took the report, in which format and when. You see yours; admins see the organization's.",
  },
  {
    title: "Caveats on every report page",
    text: "Every report page shows the caveats and the fixed statement of limits, with the traffic light on the same page.",
  },
  {
    title: "Summary and hashes only",
    text: "The kit builds each report with a summary, the caveats and file hashes. The full audit log, attack texts and judge criteria are not part of it.",
  },
  {
    title: "Agent tokens that only publish",
    text: "An agent's token can publish that agent's reports and nothing else. It cannot read, and it can be revoked.",
  },
];

function Features() {
  return (
    <section id="features" className="rule-t">
      <div className="container-page grid grid-cols-12 gap-x-0 gap-y-12 py-24 lg:gap-x-12">
        <div className="col-span-12 lg:col-span-4">
          <h2 className="heading text-4xl lg:text-5xl">Everything about your agents' reports, in one place</h2>
        </div>
        <ol className="col-span-12 m-0 list-none p-0 lg:col-span-8">
          {FEATURES.map((f, i) => (
            <li key={f.title} className="rule-t grid grid-cols-[3rem_1fr] gap-4 py-6 first:border-t-0 lg:first:pt-0">
              <span className="font-mono text-sm font-bold text-subtle">{String(i + 1).padStart(2, "0")}</span>
              <div>
                <h3 className="heading text-xl lg:text-2xl">{f.title}</h3>
                <p className="mt-2 max-w-xl text-subtle">{f.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ---- how it works ----------------------------------------------------------------------------

const STEPS = [
  {
    title: "Test the agent",
    text: "Your team runs the agent's tests where the agent runs (the kit works with a local Ollama model): a quality evaluation and red-team attacks, with and without guardrails.",
  },
  {
    title: "Publish the report",
    text: "The kit builds the report in Markdown, HTML and JSON and sends it with the agent's token.",
    code: "aok check --publish",
  },
  {
    title: "Read it in the portal",
    text: "People with access to the agent's area open the latest version, read the caveats and download the files.",
  },
];

function HowItWorks() {
  return (
    <section id="how-it-works" className="rule-t">
      <div className="container-page py-24">
        <h2 className="heading text-4xl lg:text-5xl">How it works</h2>
        <ol className="m-0 mt-12 grid list-none grid-cols-1 p-0 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="rule-t flex flex-col items-start gap-3 py-8 md:border-l md:border-t md:border-ink md:px-8 md:first:border-l-0 md:first:pl-0">
              <span className="heading text-7xl">{i + 1}</span>
              <h3 className="heading text-xl">{s.title}</h3>
              <p className="text-subtle">{s.text}</p>
              {s.code && <code className="border border-ink px-3 py-1 font-mono text-sm">{s.code}</code>}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ---- what green does not mean ----------------------------------------------------------------

function Limits() {
  return (
    <section id="limits" className="rule-t">
      <div className="container-page grid grid-cols-12 gap-x-0 gap-y-8 py-24 lg:gap-x-12">
        <div className="col-span-12 lg:col-span-4">
          <h2 className="heading text-4xl lg:text-5xl">What a green report does not mean</h2>
        </div>
        <div className="col-span-12 flex flex-col gap-6 lg:col-span-8">
          <p className="border-l-4 border-accent pl-6 text-2xl font-bold leading-snug lg:text-3xl">{LIMITS_TEXT}</p>
          <p className="pl-7 text-subtle">{SELF_DECLARED_TEXT}</p>
        </div>
      </div>
    </section>
  );
}

// ---- FAQ -------------------------------------------------------------------------------------

const FAQ: { q: string; a: ReactNode }[] = [
  {
    q: `What is ${BRAND}?`,
    a: `${BRAND} is a provisional, fictional name for the portal of agent-ops-kit, an open-source layer of observability, evaluation and security for AI agents. It stores the test reports that agent teams publish and shows them by area to the people who need to read them.`,
  },
  {
    q: `Does ${BRAND} run or host my agent?`,
    a: `No. Your agent is tested where it runs (the kit works with a local Ollama model). ${BRAND} only receives the report your team publishes and shows it.`,
  },
  {
    q: "What does the traffic light mean?",
    a: "It is a summary by provisional rules that are written into each report. Red: the evaluation regression gate fired, or the reported audit chain is invalid. Yellow: an attack succeeded with guardrails on, a legitimate question was blocked, the evaluation mean dropped without significance, or no audit log was reported. Green: none of these happened. Green still does not mean safe.",
  },
  {
    q: "What is sent to the platform, and what never is?",
    a: "The three report files (Markdown, HTML and JSON), the declared traffic light and the files' hashes. The kit builds the report with only a summary, the caveats and hashes: the full audit log, the attack texts and the judge criteria are not part of it. The server accepts only the three files and checks their hashes; it does not filter what is inside them.",
  },
  {
    q: "How does an agent publish a report?",
    a: (
      <>
        An admin registers the agent and issues a token, shown once. The team puts it in an environment variable and
        runs <code className="border border-ink px-1.5 font-mono text-sm">aok check --publish</code> with the platform
        URL. The token can only publish reports for that agent, and it can be revoked.
      </>
    ),
  },
  {
    q: "Who can see which agents' reports?",
    a: "People log in with email and password. An area viewer sees the agents of their area and its sub-areas, never the areas above. An organization admin sees everything. An area outside your reach simply looks like it does not exist.",
  },
  {
    q: "Can I download reports, and is it logged?",
    a: "Yes, as Markdown, HTML or JSON. Every download is logged with who, which format and when. You see your own history under My downloads; organization admins see everyone's, with emails.",
  },
  {
    q: `Are reports verified by ${BRAND}?`,
    a: `No. They are self-reported. ${BRAND} recalculates the hashes of the files it receives and keeps each version unedited through the API, but it does not rerun the tests. Whoever administers the server could still alter the files; a hash only helps someone who kept a copy elsewhere.`,
  },
  {
    q: "Does it work with any agent or model?",
    a: `Today the kit is built and tested around a reference RAG agent running on a local Ollama model, described in an agent.yaml file. ${BRAND} shows reports in the kit's format. Support for other frameworks or hosted models is not promised.`,
  },
];

function Faq() {
  return (
    <section id="faq" className="rule-t">
      <div className="container-page grid grid-cols-12 gap-x-0 gap-y-12 py-24 lg:gap-x-12">
        <div className="col-span-12 lg:col-span-4">
          <h2 className="heading text-4xl lg:text-5xl">Questions</h2>
        </div>
        <div className="col-span-12 lg:col-span-8">
          {FAQ.map((f) => (
            <details key={f.q} className="faq rule-t first:border-t last:border-b last:border-ink">
              <summary className="flex items-center justify-between gap-4 py-5 text-lg font-extrabold hover:text-accent">
                {f.q}
                <span aria-hidden="true" className="plus text-2xl font-normal leading-none">
                  +
                </span>
              </summary>
              <p className="max-w-2xl pb-6 text-subtle">{f.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="rule-t">
      <div className="container-page grid grid-cols-12 items-end gap-x-0 gap-y-8 py-24 lg:gap-x-12">
        <h2 className="heading col-span-12 text-5xl lg:col-span-8 lg:text-6xl">Ready to read your agents' reports?</h2>
        <div className="col-span-12 flex flex-col items-start gap-6 lg:col-span-4">
          <p className="text-subtle">Log in with the email and password your organization's admin created for you.</p>
          <div className="flex flex-wrap items-center gap-4">
            <LinkButton to="/login" variant="primary" size="lg">
              Log In
            </LinkButton>
            <SoonButton size="lg">Sign Up</SoonButton>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Landing() {
  return (
    <>
      <Hero />
      <Features />
      <BeforeAfter />
      <HowItWorks />
      <Showcase />
      <Limits />
      <Proof />
      <Faq />
      <FinalCta />
    </>
  );
}
