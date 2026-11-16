import type { ReactNode } from "react";
import { BRAND } from "../brand";
import { LIMITS_TEXT, SELF_DECLARED_TEXT } from "../format";
import { Chevron, LinkButton, SoonButton } from "../ui";
import { BeforeAfter, Proof, Showcase } from "./LandingSections";

// ---- icons (simple stroke SVGs) --------------------------------------------------------------

function Icon({ children, className = "size-6" }: { children: ReactNode; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}
const AgentIcon = ({ className }: { className?: string }) => (
  <Icon className={className}>
    <rect x="4" y="8" width="16" height="11" rx="3" />
    <path d="M12 8V4.5M10.5 4.5h3" />
    <circle cx="9" cy="13.5" r="1" />
    <circle cx="15" cy="13.5" r="1" />
    <path d="M9.5 16.5h5" />
  </Icon>
);
const TestIcon = ({ className }: { className?: string }) => (
  <Icon className={className}>
    <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
    <path d="M9 12l2 2 4-4" />
  </Icon>
);
const ReportIcon = ({ className }: { className?: string }) => (
  <Icon className={className}>
    <path d="M7 3h7l4 4v14H7z" />
    <path d="M14 3v4h4M10 12h5M10 16h5" />
  </Icon>
);
const TreeIcon = () => (
  <Icon>
    <rect x="3" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="10" width="7" height="5" rx="1.5" />
    <rect x="14" y="17" width="7" height="4" rx="1.5" />
    <path d="M6.5 8v10h7.5M6.5 12.5H14" />
  </Icon>
);
const LayersIcon = () => (
  <Icon>
    <path d="M12 4l9 5-9 5-9-5z" />
    <path d="M3 14l9 5 9-5" />
  </Icon>
);
const DownloadIcon = () => (
  <Icon>
    <path d="M12 4v11M7.5 11l4.5 4.5 4.5-4.5M5 20h14" />
  </Icon>
);
const NoteIcon = () => (
  <Icon>
    <path d="M12 3l9.5 17h-19z" />
    <path d="M12 10v4.5M12 17.5v.01" />
  </Icon>
);
const HashIcon = () => (
  <Icon>
    <path d="M5 9h15M4 15h15M10 4L8 20M16 4l-2 16" />
  </Icon>
);
const KeyIcon = () => (
  <Icon>
    <circle cx="8" cy="15" r="4" />
    <path d="M11 12l9-9M16 7l3 3" />
  </Icon>
);

// ---- hero ------------------------------------------------------------------------------------

function FlowNode({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <li className="flex items-center gap-4 rounded-2xl border border-line bg-paper p-4 shadow-[var(--shadow-soft)]">
      <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-tint text-accent">{icon}</span>
      <div>
        <p className="font-bold text-navy">{title}</p>
        <p className="text-sm text-subtle">{text}</p>
      </div>
    </li>
  );
}

function Arrow() {
  return (
    <li aria-hidden="true" className="flex justify-center text-accent">
      <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 4v15M6 13l6 6 6-6" />
      </svg>
    </li>
  );
}

function AgentFlow() {
  return (
    <figure className="rounded-3xl bg-tint p-6 sm:p-8">
      <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-paper px-4 py-2 text-sm font-semibold text-navy shadow-[var(--shadow-soft)]">
        <AgentIcon className="size-5 text-accent" />
        AI agent → tested → report
      </div>
      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        <FlowNode icon={<AgentIcon />} title="Your AI agent" text="Runs where your team runs it." />
        <Arrow />
        <FlowNode icon={<TestIcon />} title="Tested" text="Quality evaluation and red-team attacks." />
        <Arrow />
        <FlowNode icon={<ReportIcon />} title="Report" text="Published here, with its caveats." />
      </ol>
      <figcaption className="mt-6 text-sm text-subtle">
        Illustrative diagram. {BRAND} never runs your agent; it only stores and shows the report your team publishes.
      </figcaption>
    </figure>
  );
}

function Hero() {
  return (
    <div className="container-page grid grid-cols-12 items-center gap-x-0 lg:gap-x-12 gap-y-12 py-24">
      <div className="col-span-12 flex flex-col items-start gap-6 lg:col-span-7">
        <p className="rounded-full bg-tint px-4 py-1 text-sm font-semibold text-navy">Reports for AI agents</p>
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

// ---- features --------------------------------------------------------------------------------

const FEATURES = [
  {
    icon: <TreeIcon />,
    title: "An agent registry by area",
    text: "Every agent belongs to an area. Access to an area covers its sub-areas, and never the areas above it.",
  },
  {
    icon: <LayersIcon />,
    title: "Versioned agent reports",
    text: "Each publication becomes a numbered version that the API cannot edit or delete. The latest one is highlighted.",
  },
  {
    icon: <DownloadIcon />,
    title: "A log of every download",
    text: "Each download records who took the report, in which format and when. You see yours; admins see the organization's.",
  },
  {
    icon: <NoteIcon />,
    title: "Caveats on every report page",
    text: "Every report page shows the caveats and the fixed statement of limits, with the traffic light on the same page.",
  },
  {
    icon: <HashIcon />,
    title: "Summary and hashes only",
    text: "The kit builds each report with a summary, the caveats and file hashes. The full audit log, attack texts and judge criteria are not part of it.",
  },
  {
    icon: <KeyIcon />,
    title: "Agent tokens that only publish",
    text: "An agent's token can publish that agent's reports and nothing else. It cannot read, and it can be revoked.",
  },
];

function Features() {
  return (
    <section id="features" className="container-page py-24">
      <h2 className="heading max-w-2xl text-4xl lg:text-5xl">Everything about your agents' reports, in one place</h2>
      <ul className="m-0 mt-12 grid list-none grid-cols-1 gap-x-0 lg:gap-x-12 gap-y-12 p-0 md:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f) => (
          <li key={f.title} className="flex flex-col gap-3 border-t border-line pt-6">
            <span className="flex size-11 items-center justify-center rounded-xl bg-tint text-accent">{f.icon}</span>
            <h3 className="heading text-xl">{f.title}</h3>
            <p className="text-subtle">{f.text}</p>
          </li>
        ))}
      </ul>
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
    <section id="how-it-works" className="border-y border-line bg-tint">
      <div className="container-page py-24">
        <h2 className="heading text-4xl lg:text-5xl">How it works</h2>
        <ol className="m-0 mt-12 grid list-none grid-cols-1 gap-12 p-0 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex flex-col items-start gap-3">
              <span className="flex size-10 items-center justify-center rounded-full bg-navy font-bold text-white">
                {i + 1}
              </span>
              <h3 className="heading text-xl">{s.title}</h3>
              <p className="text-subtle">{s.text}</p>
              {s.code && (
                <code className="rounded-lg bg-paper px-3 py-1 font-mono text-sm text-navy">{s.code}</code>
              )}
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
    <section id="limits" className="container-page py-24">
      <div className="grid grid-cols-12 gap-x-0 lg:gap-x-12 gap-y-6">
        <div className="col-span-12 lg:col-span-4">
          <h2 className="heading text-4xl lg:text-5xl">What a green report does not mean</h2>
        </div>
        <div className="col-span-12 flex flex-col gap-6 lg:col-span-8">
          <p className="border-l-4 border-accent pl-6 text-2xl font-semibold leading-snug text-navy lg:text-3xl">
            {LIMITS_TEXT}
          </p>
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
        runs <code className="rounded bg-soft px-1.5 font-mono text-sm">aok check --publish</code> with the platform URL.
        The token can only publish reports for that agent, and it can be revoked.
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
    <section id="faq" className="border-t border-line">
      <div className="container-page grid grid-cols-12 gap-x-0 lg:gap-x-12 gap-y-12 py-24">
        <div className="col-span-12 lg:col-span-4">
          <h2 className="heading text-4xl lg:text-5xl">Questions</h2>
        </div>
        <div className="col-span-12 lg:col-span-8">
          {FAQ.map((f) => (
            <details key={f.q} className="faq border-b border-line first:border-t">
              <summary className="flex items-center justify-between gap-4 py-6 text-lg font-semibold text-navy hover:text-accent">
                {f.q}
                <Chevron />
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
    <section className="container-page py-24">
      <div className="flex flex-col items-start gap-6 rounded-3xl bg-navy p-12 text-white lg:p-24">
        <h2 className="max-w-3xl text-4xl font-extrabold leading-tight tracking-tight lg:text-5xl">
          Ready to read your agents' reports?
        </h2>
        <p className="max-w-xl text-lg text-[#c7d7fe]">
          Log in with the email and password your organization's admin created for you.
        </p>
        <div className="flex flex-wrap items-center gap-4">
          <LinkButton to="/login" size="lg" className="!bg-white !text-navy hover:!bg-tint">
            Log In
          </LinkButton>
          <SoonButton variant="secondary" size="lg" className="!border-[#4a63a6] !bg-transparent !text-white">
            Sign Up
          </SoonButton>
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
