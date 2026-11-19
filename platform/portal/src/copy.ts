import { BRAND, BRAND_DOT, BRAND_NAME, BRAND_SUBTITLE, BRAND_TAGLINE } from "./brand";

export const copy = {
  brand: {
    name: BRAND_NAME,
    dot: BRAND_DOT,
    full: BRAND,
    tagline: BRAND_TAGLINE,
    subtitle: BRAND_SUBTITLE,
  },
  hero: {
    eyebrow: "/ 00 FAROL.",
    titlePrefix: "Enxergue ",
    titleHighlight: "seus agentes",
    titleDot: ".",
    subtitle: "Relatórios de teste dos seus agentes de IA, com as limitações à vista.",
    ctaSecondary: "Ver como funciona",
    scrollHint: "Role para ver",
  },
  problem: {
    eyebrow: "/ 01 O PROBLEMA",
    titlePrefix: "Quem decide ",
    titleHighlight: "só enxerga",
    titleSuffix: " o que o time técnico consegue explicar.",
    subtitle: "O Farol. reúne, por área, o que foi testado nos seus agentes — e deixa claro o que ficou de fora.",
  },
  common: {
    loading: "Carregando…",
    errorFallback: "Erro.",
    genericError: "Algo deu errado.",
    cancel: "Cancelar",
    working: "Processando…",
    copy: "Copiar",
    copied: "Copiado",
    copyFailed: "Não foi possível copiar; selecione o valor e copie manualmente.",
    skipToContent: "Ir para o conteúdo",
    menu: "Menu",
    close: "Fechar",
  },
  nav: {
    features: "Recursos",
    howItWorks: "Como funciona",
    faq: "Perguntas frequentes",
    login: "Entrar",
    openPortal: "Abrir portal",
    contact: "Contato",
  },
  footer: {
    description:
      "Relatórios de teste e segurança de agentes de IA organizados por área, com limitações à vista e histórico de downloads.",
    productHeading: "Produto",
    portalHeading: "Portal",
    disclaimer: "Relatórios são autodeclarados pelo time do agente e não garantem segurança.",
  },
  dialogs: {
    secretAnnouncement: "Segredo gerado. Exibido uma única vez; guarde agora.",
    secretWarning: "Guarde agora; ele não será mostrado novamente.",
    secretStored: "Já guardei",
  },
  aria: {
    brandHome: `${BRAND}, início`,
    mainNav: "Navegação principal",
    mobileMenu: "Menu",
    breadcrumbs: "Você está aqui",
    trafficLightPrefix: "Semáforo: ",
  },
  opsBar: {
    subtitle: "Console do operador",
  },
  howItWorks: {
    eyebrow: "/ 02 COMO FUNCIONA",
    title: "Do teste no agente à leitura por área.",
    art: {
      step1Title: "agente + modelo local",
      step2Caveats: "ressalvas",
      step3Area: "área",
      step3TrafficLight: "semáforo + limites",
      step3Downloads: "log de downloads",
    },
    steps: [
      {
        label: "/ 01 Agente",
        title: "Teste onde o agente roda",
        text: "O time executa a avaliação de qualidade e os ataques simulados, com e sem guardrails — inclusive com modelo local via Ollama.",
      },
      {
        label: "/ 02 Relatório",
        title: "Empacote e publique",
        text: "O kit monta o pacote em Markdown, HTML e JSON só com resumo, ressalvas e hashes SHA-256, e envia usando o token restrito do agente.",
        command: "aok check --publish",
      },
      {
        label: "/ 03 Portal",
        title: "Leia por área com as ressalvas",
        text: `Quem tem acesso à área abre a versão mais recente no ${BRAND}, lê o semáforo junto das limitações e baixa o documento.`,
      },
    ],
  },
  whatYouSee: {
    eyebrow: "/ 03 O QUE VOCÊ VÊ",
    title: "Versões claras para quem decide e trilha completa para auditoria.",
    mockup: {
      badge: "Exemplo ilustrativo — sem dados reais",
      areaParent: "Operações",
      areaActive: "Atendimento",
      areaOther: "Finanças",
      navDownloads: "Meus downloads",
      breadcrumb: "Operações › Atendimento",
      reportTitle: "Assistente de Atendimento · Versão 2",
      trafficLight: "◐ Amarelo",
      chartLabel: "Comparativo ilustrativo de blocos (sem valores numéricos)",
      chartColumns: ["Qualidade", "Defesa", "Precisão", "Trilha"],
      legendBase: "Base",
      legendGuardrails: "Com guardrails",
      caveatNote: "Ressalva: resultado válido apenas para este recorte de teste, com esta suíte e este modelo.",
      downloadHtml: "Baixar HTML (ABNT / PDF)",
      downloadMd: "Baixar Markdown",
      downloadNote: "Cada download grava usuário, formato e data no histórico.",
    },
    points: [
      {
        title: "Versões imutáveis pela API",
        text: "Cada publicação gera uma nova versão numerada que a API não edita nem apaga. A versão mais recente fica em destaque.",
      },
      {
        title: "Relatório executivo ABNT para auditoria",
        text: "Exportação em HTML formatada segundo a norma ABNT NBR 10719 para impressão ou PDF, além de Markdown e JSON.",
      },
      {
        title: "Registro de downloads",
        text: "Todo download grava quem baixou, em qual formato e quando. Você acompanha os seus; a administração vê o registro da organização.",
      },
      {
        title: "Hashes SHA-256",
        text: "Cada arquivo recebido tem o hash SHA-256 recalculado e exibido ao lado da versão publicada.",
      },
    ],
  },
  permissions: {
    eyebrow: "/ 04 QUEM ENXERGA O QUÊ",
    title: "Visibilidade por área, sem expor o resto da organização.",
    subtitle:
      "Cada agente pertence a uma área. O acesso cobre a própria área e suas sub-áreas, e nunca sobe para áreas paralelas ou superiores.",
    treeLabel: "Recorte visível · leitor de Operações",
    treeCaption: "Endereços de áreas fora do alcance respondem 404.",
    treeAreas: {
      root: "Operações",
      children: ["Atendimento", "Cobrança"],
      other: "Finanças",
    },
    visibleTag: "visível",
    hiddenTag: "404",
    roles: [
      {
        title: "Leitor de área",
        text: "Vê e baixa apenas relatórios da própria área e das suas sub-áreas (por exemplo, Operações › Atendimento e Cobrança). Fora do alcance responde 404.",
      },
      {
        title: "Administração da organização",
        text: "Gerencia áreas e sub-áreas, cadastra agentes, emite ou revoga tokens que só publicam, administra usuários e consulta toda a trilha de downloads.",
      },
    ],
  },
  honesty: {
    eyebrow: "/ 05 HONESTIDADE",
    title: "O que um relatório verde não significa",
    lead: "Verde não significa seguro. Indica apenas que nada reprovou neste teste, com estes ataques e estas ressalvas.",
    points: [
      "Não cobre outros modelos, ataques fora da suíte aplicada nem mudanças de comportamento em produção.",
      "Relatórios são autodeclarados pelo time do agente: o portal armazena versões e recalcula hashes, mas não reexecuta os testes.",
      "O log completo de auditoria, os textos de ataque e as rubricas do juiz nunca sobem para o portal.",
    ],
  },
  audience: {
    eyebrow: "/ 06 PARA QUEM É",
    title: "Para times B2B com agentes de IA em operação.",
    cards: [
      {
        title: "Liderança de negócio e produto",
        text: "Acompanha o estado dos agentes da sua área em linguagem direta, com o semáforo sempre ao lado das limitações declaradas.",
      },
      {
        title: "Auditoria interna e riscos",
        text: "Consulta relatório executivo no padrão ABNT NBR 10719, histórico imutável de versões, hashes SHA-256 e trilha de downloads.",
      },
      {
        title: "Engenharia e segurança",
        text: "Publica resultados direto do fluxo de CI com aok check --publish usando token restrito por agente que só envia relatórios e pode ser revogado.",
      },
    ],
  },
  faq: {
    eyebrow: "/ 07 PERGUNTAS FREQUENTES",
    title: "Perguntas frequentes",
    items: [
      {
        q: `O que é o ${BRAND}?`,
        a: `O ${BRAND} é o portal do agent-ops-kit, uma camada open-source de observabilidade, avaliação e segurança para agentes de IA. Ele armazena os relatórios publicados pelos times e organiza a leitura por área.`,
      },
      {
        q: `O ${BRAND} executa ou hospeda meu agente?`,
        a: "Não. Os testes rodam onde o agente já opera (o kit trabalha com modelo local via Ollama). O portal recebe apenas os relatórios publicados pelo time e não reexecuta os testes.",
      },
      {
        q: "O que sobe para o portal e o que nunca sobe?",
        a: "Sobem apenas os três arquivos do relatório (Markdown, HTML e JSON), o semáforo declarado e os hashes SHA-256. O log completo de auditoria, os textos de ataque e as rubricas do juiz não integram o pacote e nunca sobem.",
      },
      {
        q: "O que significa o semáforo?",
        a: "É um resumo pelas regras gravadas em cada relatório. Vermelho: o gate de regressão disparou ou a cadeia de auditoria declarada é inválida. Amarelo: um ataque passou com guardrails, houve falso positivo, queda sem significância estatística ou ausência de trilha. Verde: nenhuma dessas ocorrências neste recorte — e verde não significa seguro.",
      },
      {
        q: "Quem pode ver e baixar relatórios?",
        a: "Pessoas autenticadas da organização. Leitores de área veem e baixam apenas relatórios da própria área e sub-áreas (o restante responde 404); administradores gerenciam áreas, agentes e tokens e veem todas as áreas. Cada download registra usuário, formato e data.",
      },
    ],
  },
  closing: {
    tagline: BRAND_TAGLINE,
    note: "Entre com o e-mail e a senha configurados pela administração da sua organização.",
  },
} as const;
