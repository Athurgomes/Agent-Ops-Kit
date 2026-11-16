import { BRAND, BRAND_TAGLINE } from "../brand";
import { LIMITS_TEXT, SELF_DECLARED_TEXT } from "../format";
import { Card, LinkButton, Tag, Title } from "../ui";

const STEPS = [
  {
    n: "1",
    title: "Agente",
    tone: "yellow" as const,
    text: "O time responsável roda os testes do agente na própria máquina: qualidade das respostas e ataques de red team, sem e com proteções.",
  },
  {
    n: "2",
    title: "Relatório",
    tone: "mint" as const,
    text: "O kit agent-ops-kit monta o relatório (Markdown, HTML e JSON) com semáforo, números e ressalvas, e o time o publica com um token próprio.",
  },
  {
    n: "3",
    title: "Portal",
    tone: "pink" as const,
    text: "Quem tem acesso à área lê as versões publicadas, vê o resultado mais recente em destaque e baixa os arquivos. Cada download fica registrado.",
  },
];

export function Landing() {
  return (
    <div className="flex flex-col gap-12">
      <section className="flex flex-col items-start gap-6">
        <Tag>Relatórios de teste de agentes de IA</Tag>
        <Title className="max-w-4xl">
          Veja o que foi testado. Leia o que ficou de fora.
        </Title>
        <p className="max-w-2xl text-lg font-medium">
          {BRAND_TAGLINE} O {BRAND} reúne, por área, os relatórios que os times publicam sobre seus
          agentes, com o resultado do teste e as ressalvas no mesmo lugar.
        </p>
        <LinkButton to="/entrar" className="text-xl">
          Entrar
        </LinkButton>
      </section>

      <section aria-labelledby="como">
        <Title as="h2" className="mb-6">
          <span id="como">Como funciona</span>
        </Title>
        <ol className="grid list-none gap-6 p-0 md:grid-cols-3">
          {STEPS.map((s) => (
            <li key={s.n}>
              <Card tone={s.tone} className="h-full">
                <p className="title text-5xl">{s.n}</p>
                <Title as="h3" className="my-2">
                  {s.title}
                </Title>
                <p className="font-medium">{s.text}</p>
              </Card>
            </li>
          ))}
        </ol>
        <p className="mt-4 font-black uppercase" aria-hidden="true">
          Agente → Relatório → Portal
        </p>
      </section>

      <section aria-labelledby="limites">
        <Card tone="yellow">
          <Title as="h2" className="mb-4">
            <span id="limites">O que o relatório não garante</span>
          </Title>
          <p className="text-lg font-bold">{LIMITS_TEXT}</p>
          <p className="mt-4 font-medium">{SELF_DECLARED_TEXT}</p>
          <ul className="mt-4 list-disc space-y-1 pl-6 font-medium">
            <li>Os números sempre vêm com o tamanho do teste e as limitações do método.</li>
            <li>As regras do semáforo ainda são provisórias e estão escritas em cada relatório.</li>
            <li>Os textos dos ataques e os critérios internos de avaliação não aparecem aqui.</li>
          </ul>
        </Card>
      </section>

      <section className="flex flex-col items-start gap-4">
        <Title as="h2">Já tem acesso?</Title>
        <LinkButton to="/entrar">Entrar</LinkButton>
      </section>
    </div>
  );
}
