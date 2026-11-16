import { BRAND } from "../brand";
import { LIMITS_TEXT, SELF_DECLARED_TEXT } from "../format";
import { Card, Chevron, cx, LinkButton, Section, SemaforoBadge, Tag, Title } from "../ui";
import type { Tone } from "../ui";

// ---- hero: mockup ilustrativo (sem dados reais) ------------------------------------------------

function MockReport() {
  return (
    <figure className="m-0">
      <div className="relative">
        <div aria-hidden="true" className="brutal absolute -bottom-4 -right-4 left-4 top-4 bg-pink" />
        <div className="brutal shadow-hard relative bg-paper p-6">
        <div className="mb-4 flex items-center justify-between gap-4">
          <Tag tone="yellow">Exemplo ilustrativo</Tag>
          <span className="text-sm font-semibold">Versão 2</span>
        </div>
        <p className="display text-xl">Nome do agente</p>
        <p className="mb-4 text-sm">Área · Sub-área</p>
        <SemaforoBadge value="yellow" size="lg" />
        <dl className="m-0 mt-6 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="font-bold">Gerado em</dt>
          <dd className="m-0">dd/mm/aaaa, hh:mm</dd>
          <dt className="font-bold">Publicado em</dt>
          <dd className="m-0">dd/mm/aaaa, hh:mm</dd>
        </dl>
        <div aria-hidden="true" className="mt-6 flex flex-col gap-2">
          <div className="h-3 w-full bg-muted-2" />
          <div className="h-3 w-11/12 bg-muted-2" />
          <div className="h-3 w-2/3 bg-muted-2" />
        </div>
        <div aria-hidden="true" className="mt-6 flex gap-4">
          <span className="btn btn-secondary btn-sm">Baixar MD</span>
          <span className="btn btn-secondary btn-sm">Baixar HTML</span>
        </div>
        </div>
      </div>
      <figcaption className="mt-6 text-sm font-semibold">
        Exemplo ilustrativo: só mostra o layout de um relatório. Nenhum dado real.
      </figcaption>
    </figure>
  );
}

function Hero() {
  return (
    <div className="container-page grid grid-cols-12 items-center gap-x-6 gap-y-12 py-24">
      <div className="col-span-12 flex flex-col items-start gap-6 lg:col-span-7">
        <Tag tone="mint">Relatórios de teste de agentes de IA</Tag>
        <h1 className="display text-5xl sm:text-6xl lg:text-7xl">
          Veja o que foi testado. Leia o que ficou de fora.
        </h1>
        <p className="max-w-xl text-lg">
          O {BRAND} reúne, por área, os relatórios que os times publicam sobre seus agentes de IA, com
          o resultado do teste e as ressalvas no mesmo lugar.
        </p>
        <div className="flex flex-wrap items-center gap-6 pt-2">
          <LinkButton to="/entrar" variant="primary" size="lg">
            Entrar
          </LinkButton>
          <a href="#como" className="font-bold">
            Ver como funciona
          </a>
        </div>
      </div>
      <div className="col-span-12 lg:col-span-5">
        <MockReport />
      </div>
    </div>
  );
}

// ---- como funciona ---------------------------------------------------------------------------

const STEPS = [
  {
    title: "O agente é testado",
    text: "O time responsável roda os testes na própria máquina: qualidade das respostas e ataques de red team, sem e com proteções.",
  },
  {
    title: "O relatório é publicado",
    text: "O kit monta o relatório (Markdown, HTML e JSON) com semáforo, números e ressalvas. O time o publica com um token que só publica.",
  },
  {
    title: "A liderança consulta no portal",
    text: "Quem tem acesso à área lê as versões publicadas, vê a mais recente em destaque e baixa os arquivos.",
  },
];

function HowItWorks() {
  return (
    <Section id="como" tone="mint">
      <Title as="h2" className="mb-12 text-4xl lg:text-5xl">
        Como funciona
      </Title>
      <ol className="m-0 grid list-none grid-cols-1 gap-6 p-0 md:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="relative">
            <Card shadow className="h-full">
              <p className="display mb-4 text-6xl">{i + 1}</p>
              <h3 className="display mb-2 text-xl">{s.title}</h3>
              <p>{s.text}</p>
            </Card>
          </li>
        ))}
      </ol>
    </Section>
  );
}

// ---- bento -----------------------------------------------------------------------------------

type Block = { span: string; tone: Tone; tag: string; title: string; text: string; extra?: "tree" };
const BLOCKS: Block[] = [
  {
    span: "lg:col-span-7",
    tone: "pink",
    tag: "Organização",
    title: "Organizado por área",
    text: "Cada pessoa vê só as áreas que lhe cabem, e o acesso a uma área vale para as sub-áreas abaixo dela. Nunca para cima.",
    extra: "tree",
  },
  {
    span: "lg:col-span-5",
    tone: "white",
    tag: "Histórico",
    title: "Versões por agente",
    text: "Cada publicação vira uma versão numerada. A mais recente fica em destaque e as anteriores continuam disponíveis, sem edição.",
  },
  {
    span: "lg:col-span-4",
    tone: "mint",
    tag: "Rastreio",
    title: "Histórico de downloads",
    text: "Cada download registra quem baixou, o formato e quando. Você vê o seu; administradores veem o da organização.",
  },
  {
    span: "lg:col-span-4",
    tone: "yellow",
    tag: "Honestidade",
    title: "Ressalvas sempre visíveis",
    text: "O tamanho do teste e as limitações do método aparecem junto do semáforo, não escondidas no fim de um anexo.",
  },
  {
    span: "lg:col-span-4",
    tone: "white",
    tag: "Acesso",
    title: "Token que só publica",
    text: "O token de um agente serve apenas para enviar relatórios daquele agente. Ele não consegue ler nada.",
  },
  {
    span: "lg:col-span-12",
    tone: "white",
    tag: "Privacidade",
    title: "Só agregados e hashes, nunca o log completo",
    text: "O kit monta o relatório só com o resumo, as ressalvas e as impressões digitais (hashes) dos arquivos. O log completo de auditoria, os textos dos ataques e os critérios internos de avaliação não entram no relatório.",
  },
];

function Bento() {
  return (
    <Section id="recursos">
      <Title as="h2" className="mb-12 text-4xl lg:text-5xl">
        O que o portal faz
      </Title>
      <div className="grid grid-cols-12 gap-6">
        {BLOCKS.map((b) => (
          <div key={b.title} className={cx("col-span-12", b.span)}>
            <Card tone={b.tone} className="flex h-full flex-col items-start gap-4">
              <Tag tone="white">{b.tag}</Tag>
              <h3 className="display text-xl lg:text-2xl">{b.title}</h3>
              <p className="max-w-3xl">{b.text}</p>
              {b.extra === "tree" && (
                <ul aria-label="Exemplo de hierarquia" className="m-0 mt-2 list-none bg-paper p-4 brutal text-sm font-semibold">
                  <li>Área</li>
                  <li className="ml-4">└ Sub-área</li>
                  <li className="ml-8">└ Agente</li>
                </ul>
              )}
            </Card>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ---- o que o relatório não garante -----------------------------------------------------------

function Limits() {
  return (
    <Section id="limites" tone="yellow">
      <div className="grid grid-cols-12 gap-x-6 gap-y-12">
        <div className="col-span-12 lg:col-span-5">
          <Title as="h2" className="text-4xl lg:text-5xl">
            O que o relatório não garante
          </Title>
        </div>
        <div className="col-span-12 lg:col-span-7">
          <Card shadow className="flex flex-col gap-6">
            <p className="text-2xl font-extrabold leading-snug">{LIMITS_TEXT}</p>
            <p className="border-t-[3px] border-ink pt-6">{SELF_DECLARED_TEXT}</p>
            <ul className="m-0 list-disc space-y-2 pl-6">
              <li>Os números sempre vêm com o tamanho do teste e as limitações do método.</li>
              <li>As regras do semáforo ainda são provisórias e estão escritas em cada relatório.</li>
            </ul>
          </Card>
        </div>
      </div>
    </Section>
  );
}

// ---- FAQ -------------------------------------------------------------------------------------

const FAQ = [
  {
    q: "O que o semáforo significa?",
    a: "É um resumo por regras provisórias, escritas em cada relatório. Vermelho: o gate de regressão disparou ou a auditoria informada é inválida. Amarelo: houve ataque bem-sucedido com proteções ligadas, falso positivo, queda não significativa ou falta de auditoria. Verde: nenhuma dessas condições ocorreu, e mesmo assim verde não significa seguro.",
  },
  {
    q: "O que vai para a plataforma?",
    a: "O kit monta o pacote só com resumo, ressalvas e hashes; o log completo, os textos dos ataques e os critérios internos não entram no relatório. O servidor aceita apenas os três arquivos do relatório (Markdown, HTML e JSON) e confere os hashes.",
  },
  {
    q: "Quem vê o quê?",
    a: "Cada pessoa vê as áreas a que tem acesso, incluindo as sub-áreas. O administrador da organização vê todas. O token de um agente só publica relatórios daquele agente e não lê nada.",
  },
  {
    q: "O relatório é verificado?",
    a: "Não. Ele é autodeclarado: gerado e publicado pelo time do agente. O portal recalcula os hashes dos arquivos recebidos e guarda cada versão sem edição, mas não repete os testes. Quem administra o servidor também poderia alterar os arquivos; o hash só ajuda quem guardou uma cópia fora do servidor.",
  },
  {
    q: "Posso baixar o relatório?",
    a: "Pode, em Markdown, HTML ou JSON. Cada download fica registrado com quem baixou e quando; você vê o seu histórico e os administradores veem o da organização.",
  },
];

function Faq() {
  return (
    <Section id="perguntas">
      <div className="grid grid-cols-12 gap-x-6 gap-y-12">
        <div className="col-span-12 lg:col-span-4">
          <Title as="h2" className="text-4xl lg:text-5xl">
            Perguntas
          </Title>
        </div>
        <div className="col-span-12 flex flex-col gap-4 lg:col-span-8">
          {FAQ.map((f) => (
            <details key={f.q} className="faq brutal bg-paper">
              <summary className="flex items-center justify-between gap-4 p-4 font-extrabold hover:bg-muted">
                {f.q}
                <Chevron />
              </summary>
              <p className="border-t-[3px] border-ink p-4">{f.a}</p>
            </details>
          ))}
        </div>
      </div>
    </Section>
  );
}

function FinalCta() {
  return (
    <Section tone="pink">
      <div className="flex flex-col items-start gap-6">
        <Title as="h2" className="max-w-3xl text-4xl lg:text-5xl">
          Já tem acesso? Abra o portal.
        </Title>
        <p className="max-w-xl">Entre com o e-mail e a senha que a administração da sua organização criou.</p>
        <LinkButton to="/entrar" variant="primary" size="lg">
          Entrar
        </LinkButton>
      </div>
    </Section>
  );
}

export function Landing() {
  return (
    <>
      <Hero />
      <HowItWorks />
      <Bento />
      <Limits />
      <Faq />
      <FinalCta />
    </>
  );
}
