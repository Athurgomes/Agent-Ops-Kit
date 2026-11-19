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
} as const;
