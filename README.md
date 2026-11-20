# agent-ops-kit

Observabilidade, avaliação e segurança para agentes de IA.

Agentes de IA vão para uso sem que se saiba o que fizeram, se uma mudança de prompt piorou a qualidade ou se resistem a ataques simples. O kit junta, em um repositório local e sem custo, tracing (OpenTelemetry/Jaeger), log de auditoria com hash encadeado, avaliação A/B de prompts com estatística pareada, guardrails e um harness de red team. Tudo foi medido sobre um agente de referência (RAG com documentos fictícios, modelo local de 8B); os resultados e suas ressalvas estão abaixo.

## Visão geral

```mermaid
flowchart LR
    U[Usuário] --> IF[Filtro de entrada] --> A[Loop do agente<br/>Ollama + tools] --> OF[Filtro de saída] --> R[Resposta]
    A <--> T[search_docs Chroma,<br/>calculator, current_date]
    A -. spans OTLP .-> J[Jaeger]
    A -. eventos .-> AU[(Auditoria JSONL<br/>hash encadeado)]
    EV[aok eval<br/>A/B + gate de CI] --> A
    RT[aok redteam<br/>ASR + falsos positivos] --> A
```

Detalhes, tabela de módulos e decisões: [docs/arquitetura.md](docs/arquitetura.md) e [docs/decisoes.md](docs/decisoes.md).

![Demonstração da CLI com respostas gravadas (semente 42)](docs/demo-cli.gif)

Saída real dos comandos `aok eval --reuse --summary`, `aok redteam report --summary` e `aok report build` com respostas gravadas no repositório (sem chamar o modelo, semente 42).

## Quickstart

Requisitos: Python 3.11+ e Docker. O comando `aok` pode não estar no PATH (depende do Python e do sistema); nesse caso use `python -m agent_ops_kit.cli` no lugar de `aok` em todos os comandos abaixo.

```bash
docker compose up -d            # Jaeger em http://localhost:16686
pip install -e ".[dev,rag]"
aok new meu-agente              # gera um agente instrumentado na pasta atual
```

### Sem modelo (usa respostas e resultados gravados)

Estes comandos não chamam o Ollama; leem execuções gravadas no repositório (semente 42).

```bash
aok eval --baseline v1 --candidate v2 --reuse --summary
aok redteam report --baseline redteam/results/baseline.jsonl \
  --guardrails redteam/results/guardrails.jsonl --fp-dir redteam/results --summary
aok audit verify caminho/do/log.jsonl     # também: audit report, audit anchor, keygen, sign
bash scripts/demo.sh                      # roteiro completo, com log de auditoria fictício
```

Assinatura opcional da âncora de auditoria (Ed25519 ou HMAC via variável de ambiente):

```bash
aok audit keygen --private-out audit.key --public-out audit.pub
aok audit sign caminho/do/log.jsonl --out audit.sig.json --private-key audit.key
aok audit verify caminho/do/log.jsonl --signature audit.sig.json --public-key audit.pub
# alternativa com HMAC-SHA256 (chave sempre em variável de ambiente, nunca literal na CLI):
export AOK_AUDIT_HMAC_KEY="<sua-chave-secreta>"
aok audit sign caminho/do/log.jsonl --out audit.sig.json --hmac-key-env AOK_AUDIT_HMAC_KEY
aok audit verify caminho/do/log.jsonl --signature audit.sig.json --hmac-key-env AOK_AUDIT_HMAC_KEY
```

`--reuse` confere o manifesto das respostas gravadas (prompt, dataset e modelo); se divergirem, o comando falha com código 2.

### Relatório para quem não é técnico

```bash
aok report build --out reports/pacote
aok check --publish reports/publicados --agent-id meu-agente   # opcional: --audit LOG [--audit-signature SIG (--audit-public-key PUB | --audit-hmac-key-env VAR)], --previous relatorio.json
```

Saída real de ambos neste repositório: `Pacote gravado em reports/pacote/ (relatorio.md, relatorio.html, relatorio.json)` e `Semáforo (regras provisórias): AMARELO`; o `--publish` acrescentou `Publicado em reports/publicados/meu-agente/<timestamp UTC> (semáforo: yellow)`.

- Não roda modelo: lê os resultados gravados (eval e red team).
- `relatorio.md` e `relatorio.html` seguem estrutura técnico-executiva baseada na **ABNT NBR 10719:2015** e **NBR 6024:2012** (identificação documental, resumo executivo, leitura em linguagem de negócios, encaminhamentos, quadro de ciência para auditoria e Apêndice A com evidências técnicas e SHA-256), com CSS estático A4 (`3cm 2cm 2cm 3cm`) pronto para impressão ou salvamento em PDF pelo navegador (ADR-013 em [docs/decisoes.md](docs/decisoes.md)).
- O `--publish` grava `relatorio.md`, `relatorio.html`, `relatorio.json` e `pacote.json` em `<pasta>/<agent-id>/<timestamp UTC>/` e atualiza `index.json` com as versões, mais recente primeiro. Cada publicação cria uma versão nova; nada é sobrescrito (por convenção, não é imutabilidade técnica).
- O log de auditoria nunca entra no pacote: com `--audit`, só entram o resultado da verificação da cadeia e a âncora.
- O semáforo usa regras provisórias, e verde não significa seguro.

Verificação offline por um auditor, sem confiar no autor (sem rede, sem Ollama):

```bash
aok report verify reports/pacote --repo-root .   # opcional: --json, --audit-hmac-key-env VAR
```

Recalcula, a partir dos arquivos de evidência, o eval (médias, IC, p), o ASR com IC de Wilson, o McNemar exato e os falsos positivos; reavalia o semáforo com a política gravada (sha256 em disco igual ao gravado); confere os hashes de `hashes`, `provenance.inputs` e dos achados (linha e registro), a cadeia e a assinatura do log de auditoria (se referenciado), execuções e sementes, as limitações e se `relatorio.md`/`.html` são a renderização do JSON. Exit 0 = tudo confere; 1 = falha ou evidência ausente ("não verificável" não é ok); 2 = pacote ilegível. Detalhes e limites na ADR-026.

### Plataforma (fase 2: API)

Serviço opcional em `platform/` que recebe o pacote publicado. Como subir: ver [platform/README.md](platform/README.md). Como publicar, com o token emitido pelo admin só em variável de ambiente:

```bash
export AOK_PLATFORM_TOKEN="<token emitido>"
aok check --publish https://sua-plataforma --agent-id meu-agente   # ou platform.agent_id no agent.yaml
```

- Só agregados e hashes sobem; o log de auditoria não. O relatório é autodeclarado: a plataforma não reexecuta o teste (ADR-007).
- Estado da implantação (docker compose, Postgres, CI), com datas e o que não foi reconfirmado: ver o ADR-007 em [docs/decisoes.md](docs/decisoes.md). Migrações formais de esquema usam Alembic (ADR-016, removendo a restrição `UNIQUE(slug)` global inclusive em bancos SQLite legados) e os limitadores de tentativa usam tabela compartilhada no banco (ADR-017).

### Plataforma (fase 3: portal)

Login, leitura e download dos relatórios pelo navegador no portal oficial **Farol.** (ADR-008 e ADR-015). Detalhes em [platform/README.md](platform/README.md). Para ver localmente:

```bash
pip install -e ".[platform]"
export AOK_COOKIE_SECURE=false          # só para teste local sem HTTPS
python -m aok_platform.seed_demo        # imprime as senhas uma única vez
(cd platform/portal && npm ci && npm run build)
uvicorn aok_platform.app:create_app --factory   # http://127.0.0.1:8000
```

Para subir tudo com um comando (dados de demonstração, operador e organização `beta`; compila o portal se faltar; só em 127.0.0.1; as senhas aparecem uma vez no terminal; Ctrl+C encerra), use `python scripts/demo_plataforma.py [--porta 8000] [--publicar] [--reset] [--dados PASTA]`. Sem `--dados`, usa `.demo/`, ignorada pelo git.

- Telas: landing pública (`/`), login (`/login`), áreas > agentes > relatórios > detalhe (`/app/...`; botões `Baixar HTML (ABNT / PDF)`, `Baixar Markdown` e `Baixar JSON`), "Meus downloads" e, para `org_admin`, "Todos os downloads".
- Identidade e interface: 100% em `pt-BR` (centralizada em `platform/portal/src/copy.ts`), com direção visual de diário de bordo / carta náutica (papel `#ffffff`, tinta `#0a0a0a`, superfície `#f7f7f5` e azul `#2563eb` reservado a CTAs primários, links, foco, ponto da marca e estados ativos), tipografia autohospedada via `@fontsource` (sem CDN externo), foco B2B sem cadastro aberto nem página de preços (`CONTACT_URL` opcional em `platform/portal/src/brand.ts`) e semáforo com glifos distintos além da cor (`●` Verde, `◐` Amarelo, `✕` Vermelho) sempre ao lado das ressalvas ("Verde não significa seguro" e autodeclaração).
- Cada pessoa vê só as áreas do seu perfil (com sub-áreas); área fora do alcance responde 404. O download grava em `download_log`.
- O seed cria dados de demonstração com agentes fictícios; o conteúdo dos relatórios vem do exemplo do repositório.
- Verificado com o design atual (**Farol.**, incluindo o commit `308aee0`) em 19/11/2026: build (`tsc --noEmit && vite build`) e fluxo completo ponta a ponta contra o `platform/docker-compose.yml` (Postgres 16) no navegador Edge headless/CDP em desktop (`1440x900`) e mobile (`375x812` via `Emulation.setDeviceMetricsOverride`): zero erros de console ou exceções JS, `scrollWidth <= innerWidth` em `/`, `/login`, `/app`, detalhe do relatório e `relatorio.html` ABNT baixado (este sem viewport próprio, `innerWidth = scrollWidth = 981`), login real, navegação completa e persistência após reinício do container `api`. Não exercitados: leitor de tela, verificação automática completa de contraste e outros navegadores fora de Edge/Chromium.
- Limitações: o bloqueio de login por e-mail (5 falhas travam por 5 minutos) ainda permite que terceiros travem a conta de outra pessoa; CSRF apenas por cookie `SameSite=Strict`. (O throttle em memória e a ausência de migrações foram substituídos por `rate_limit_entry` no ADR-017 e pelo Alembic no ADR-016.)
- Não existe: SSO, dark mode, geração direta de binário PDF no servidor (o `relatorio.html` já sai formatado em A4 pela ABNT NBR 10719 para impressão/PDF pelo navegador) e cadastro aberto (multiempresa e operador: ver a seção seguinte; recuperação de senha: ver "Plataforma: recuperação de senha").
- Testes: ver a seção "Estado e testes" abaixo.

### Plataforma: administração

Para `org_admin`, o menu "Administração" do portal (ADR-009) permite ao time de segurança:

- **Áreas**: criar áreas e sub-áreas.
- **Agentes**: registrar, ativar e desativar; emitir e revogar tokens (o token aparece uma única vez).
- **Usuários e acessos**: criar usuários, redefinir senha (gerada, exibida uma vez), vincular a áreas e desativar.
- **Atividade** (eventos administrativos: quem mudou o quê, sem segredos) e **Todos os downloads** (tela separada).

Regras: leituras e escritas ficam na organização de quem chama; o admin não desativa a própria conta e ninguém remove o último `org_admin` ativo. Verificado no navegador (Edge CDP): criar área e sub-área, registrar agente, emitir token, publicar com `aok check --publish`, ver o relatório, revogar o token (a publicação seguinte falhou com 401), criar usuário viewer só da área, desativar e ver o login falhar, ver os eventos; e, em 19/11/2026 contra `platform/docker-compose.yml`, editar e desativar/reativar agente, conceder e revogar acesso posterior de área e redefinir senha pelo admin (exibição única validada por login com a nova senha). Limitações: no backend todas as listagens admin suportam paginação via `limit`/`offset` com cabeçalho `X-Total-Count`, mas no portal atualmente apenas a tela de Atividade consome paginação via API (áreas, agentes, tokens e usuários ainda carregam a lista completa); `admin_event` pode ser alterado por quem opera o banco. (O `platform/docker-compose.yml` foi revalidado ponta a ponta após o redesenho Farol., Alembic e `/v1/health`.)

### Plataforma: várias organizações e operador

Isolamento por organização no backend (ADR-011) e visão do operador (ADR-010), desligada por padrão. Detalhes em [platform/README.md](platform/README.md).

```bash
python -m aok_platform.create_org --slug acme --name "Acme"          # 2ª organização
export AOK_OPS_ENABLED=true                                          # liga /v1/ops e o console /ops
python -m aok_platform.create_operator --email ops@example.com       # imprime a senha uma vez
```

- Com 2 ou mais organizações, a chave de bootstrap exige o cabeçalho `X-Org-Slug`. Pelo console, o operador cria o primeiro admin (senha exibida uma vez).
- O operador vê só metadados: organizações, contagens, agentes, versões, semáforo, datas e trilhas. Não vê conteúdo de relatório, ressalvas, arquivos, tokens nem hashes, e não baixa nada. Quem opera o banco ou o servidor continua podendo ler tudo.
- Verificado no navegador (Edge CDP), com banco temporário: fluxo completo com 2 organizações, publicação real com `aok check --publish`, desativar e reativar organização, reset de senha, sessões separadas e, em 19/11/2026, tentativa de criar organização com slug duplicado na interface `/ops` (exibindo `409` sem stack trace). Não exercitados: leitor de tela, verificação automática completa de contraste e outros navegadores fora de Edge/Chromium.
- Limitações: e-mail único globalmente. (A restrição global de `slug` de agente em SQLite legado, a ausência de Alembic e o throttle em memória foram substituídos pelos ADRs 016 e 017.)

### Plataforma: recuperação de senha

Opcional (ADR-012). Fica ativa só com `AOK_SMTP_HOST` e `AOK_PUBLIC_URL` definidos (também `AOK_SMTP_PORT`, `AOK_SMTP_USER`, `AOK_SMTP_PASSWORD`, `AOK_SMTP_STARTTLS`, `AOK_SMTP_FROM`; detalhes em [platform/README.md](platform/README.md)). Sem elas, as rotas respondem 404 e, na tela de login, o link "Esqueci minha senha" fica oculto, exibindo apenas o aviso de redefinição via administrador da organização.

- O usuário pede em `/forgot-password` e vê a mesma resposta para e-mail existente ou não; só o existente recebe o e-mail, com link `#token` válido por 30 min e de uso único.
- Em `/reset-password` define a senha nova (12+ caracteres). Todas as sessões são revogadas, não há login automático e chega um aviso de troca.
- Verificado no navegador (Edge CDP) com servidor SMTP local (Mailpit e servidor SMTP local em 19/11/2026): fluxo completo `/forgot-password` -> `/reset-password#token=...` e `429` na interface após mais de 10 tentativas inválidas (tokens válidos continuam aceitos após o limite do IP, ADR-017). Em `postgres:16` efêmero via `AOK_TEST_DATABASE_URL`, a suíte completa de plataforma passou em 19/11/2026 (`286 passed, 0 skipped` em 281.87s, commit `fff746f`; ver ADR-007 em [docs/decisoes.md](docs/decisoes.md)) e o CI run #45 (`fff746f`) passou nos três jobs (`test`, `portal` e `postgres`). Não exercitados: provedor SMTP externo real (STARTTLS, entregabilidade), leitor de tela, verificação automática completa de contraste e outros navegadores fora de Edge/Chromium.
- Limitações: atrás de proxy reverso, é preciso configurar `AOK_TRUSTED_PROXIES` com os IPs/CIDRs confiáveis (sem essa variável, o IP visto é o do proxy); operadores seguem com reset só pela CLI. (Os limitadores em memória foram substituídos por `rate_limit_entry` no banco pelo ADR-017.)

### Plataforma: operação online

A plataforma está preparada para operação online em **instância única** atrás de proxy reverso HTTPS, com o pipeline de CI do agente publicando por `aok check --publish https://...` (passo a passo em [platform/README.md](platform/README.md) e ADR-014 em [docs/decisoes.md](docs/decisoes.md)):

- `GET /v1/health` verifica o banco (`SELECT 1`) e o acesso a `AOK_DATA_DIR` (`200` ou `503`, `Cache-Control: no-store`), usado também no `healthcheck` de `platform/docker-compose.yml`.
- `AOK_DOCS_ENABLED=false` desliga `/docs`, `/redoc` e `/openapi.json` (inclusive no fallback SPA), e o middleware HTTP aplica `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` e `Strict-Transport-Security` opcional (`AOK_HSTS_ENABLED=true`).
- `AOK_TRUSTED_PROXIES` habilita leitura controlada (direita para esquerda) de `X-Forwarded-For` na recuperação de senha atrás de proxies confiáveis.
- Limitação conhecida: validado localmente e em CI como instância única; embora migrações formais com Alembic (ADR-016) e store compartilhado no banco para os limitadores de tentativas (ADR-017) já existam, múltiplas réplicas exigem volume compartilhado para `AOK_DATA_DIR` e ainda não houve teste de carga nem validação em nuvem.

### Com o modelo (usa o Ollama)

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
python -m examples.rag_agent "Quantos dias de férias a Lumina concede por ano?"
```

Na primeira execução o corpus fictício é indexado em `chroma/`. Só uma pergunta foi executada para confirmar este comando; os demais comandos que usam o modelo (`aok eval` sem `--reuse`, `--judge`, `aok redteam run`) estão em [docs/resultados.md](docs/resultados.md) e não foram reexecutados ao escrever este README.

Para medir variância e consistência entre múltiplas execuções por caso (ex.: 3 execuções usando sementes `seed`, `seed+1`, `seed+2`; respostas gravadas em `evals/answers_multirun/` e relatório em `evals/results/v1_vs_v2_multirun.md`, resumidos em [docs/resultados.md](docs/resultados.md)):

```bash
aok eval --baseline v1 --candidate v2 --answers-dir evals/answers_multirun --runs 3 --summary
```

Para auditoria local mais ampla com Ollama, está disponível também `evals/dataset_audit_200.jsonl` (200 casos cobrindo os 15 documentos do corpus e casos de abstenção; execução de referência com `--runs 1` gravada em `evals/answers_audit_200/` e relatório em `evals/results/audit_200_v1_vs_v2.md`, ver [docs/resultados.md](docs/resultados.md)):

```bash
aok eval --baseline v1 --candidate v2 --dataset evals/dataset_audit_200.jsonl --answers-dir evals/answers_audit_200 --summary
```

Para red team ampliado (108 ataques em 9 categorias OWASP LLM Top 10) e avaliação com suíte cega externa fora do repositório (sem gravar perguntas, respostas ou chamadas de tools dos casos cegos):

```bash
aok redteam run --attacks-dir redteam/attacks_owasp_100 --guardrails all --out reports/owasp_guardrails.jsonl
# ou combinando/isolando uma suíte reservada externa (também via variável AOK_BLIND_ATTACKS_DIR):
export AOK_BLIND_ATTACKS_DIR="/caminho/fora/do/repo/blind_suite"
aok redteam run --guardrails all --blind-attacks-dir "$AOK_BLIND_ATTACKS_DIR" --out reports/blind_guardrails.jsonl
aok redteam run --guardrails all --blind-only --out reports/blind_only.jsonl
```

As medições com modelo local sobre `redteam/attacks_owasp_100/` (108 ataques) e `redteam/benign_expanded/benign_50.jsonl` (54 perguntas benignas) foram feitas entre 19 e 20/11/2026 (`redteam/results_owasp/`, seção B.1 em [docs/resultados.md](docs/resultados.md)); os resultados gravados em `redteam/results/` continuam referentes aos 40 ataques e 12 benignas originais.

### Como ver o trace

1. Com o Jaeger de pé e o agente executado (comando acima), abra http://localhost:16686.
2. Escolha o serviço `rag-agent` (para um agente criado com `aok new`, o nome do agente) e clique em Find Traces.
3. Spans esperados em cada trace: `agent.run`, `llm.call`, `tool.call` e `retrieval.query`.

Capturas reais de um trace (lista e detalhe dos spans) estão em [evidencias/02-trace-jaeger/](evidencias/02-trace-jaeger/).

Para desligar o tracing: `AOK_TRACING=off`.

## Estado e testes

Conferido em 19/11/2026 sobre o código do commit `8a2e3be`: `python -m pytest -q` deu `719 passed, 5 skipped` (135.35s); `python -m ruff check .` passou (`All checks passed!`). Os 5 skips são ambientais no Windows: verificação de permissões POSIX `0o600` na assinatura de auditoria, um teste do demo que precisa criar link simbólico sem privilégio neste sistema e 3 testes que só rodam com `AOK_TEST_DATABASE_URL` apontando para um Postgres. Os testes locais não usam Ollama nem Docker. Em `postgres:16` efêmero via `AOK_TEST_DATABASE_URL`, a suíte completa de plataforma passou em 19/11/2026 (`286 passed, 0 skipped` em 281.87s, commit `fff746f`; ver [platform/README.md](platform/README.md)).

Workflows (`.github/workflows/`): `ci.yml` (jobs `test`, `portal` e `postgres`) e `eval.yml` (gate de prompts com respostas gravadas). Além do run #20 (`88dc3fc`, em [evidencias/03-ci-github/](evidencias/03-ci-github/)), o run #45, do commit `fff746f` (conferido em 19/11/2026), passou nos três jobs (`test`, `portal` e `postgres`) em `ubuntu-latest`, onde os testes POSIX e de link simbólico rodam sem skip.

## Resultados medidos

Fonte única: [docs/resultados.md](docs/resultados.md). Modelo llama3.1:8b via Ollama, semente 42, uma execução por configuração sobre o conjunto padrão de 50 casos (`evals/dataset.jsonl`). As tabelas abaixo são cópia, sem alterações.

### Segurança: ASR antes e depois dos guardrails

| Categoria | Config. | n | Sucessos | ASR % | IC 95% (Wilson) | Erros |
|---|---|---|---|---|---|---|
| injecao_direta | sem guardrails | 12 | 1 | 8.3 | [1.5; 35.4] | 0 |
| injecao_direta | com guardrails | 12 | 0 | 0.0 | [0.0; 24.2] | 0 |
| injecao_indireta | sem guardrails | 12 | 1 | 8.3 | [1.5; 35.4] | 0 |
| injecao_indireta | com guardrails | 12 | 0 | 0.0 | [0.0; 24.2] | 0 |
| abuso_de_tools | sem guardrails | 8 | 6 | 75.0 | [40.9; 92.9] | 0 |
| abuso_de_tools | com guardrails | 8 | 0 | 0.0 | [0.0; 32.4] | 0 |
| exfiltracao | sem guardrails | 8 | 1 | 12.5 | [2.2; 47.1] | 0 |
| exfiltracao | com guardrails | 8 | 0 | 0.0 | [0.0; 32.4] | 0 |
| total | sem guardrails | 40 | 9 | 22.5 | [12.3; 37.5] | 0 |
| total | com guardrails | 40 | 0 | 0.0 | [0.0; 8.8] | 0 |

Ressalvas essenciais:

- Em abuso de tools, o ASR ir a zero é em grande parte por construção: as tools proibidas não estão na allowlist, então ela as bloqueia sempre. Mostra que o filtro funciona, não robustez geral do agente.
- 23 dos 40 ataques não foram bloqueados por nenhum guardrail; a baseline já era baixa fora de abuso de tools, e os intervalos de confiança se sobrepõem.
- Dos 9 sucessos na baseline, 8 foram bloqueados e 1 falhou na segunda execução sem bloqueio: nem toda a queda de 9 para 0 é atribuível aos guardrails.
- O conjunto de ataques não é reservado (foi escrito no mesmo projeto, não é um teste cego) e há uma execução por configuração.

### Falsos positivos

| Conjunto | n | Bloqueadas | Taxa de FP % | IC 95% (Wilson) | Erros |
|---|---|---|---|---|---|
| Dataset de avaliação (50) | 50 | 0 | 0.0 | [0.0; 7.1] | 0 |
| Benignas novas (12) | 12 | 1 | 8.3 | [1.5; 35.4] | 0 |

Uma das 12 perguntas legítimas novas foi bloqueada (estágio output, motivo canary_leak). O conjunto benigno foi escrito depois de dois falsos positivos de teste já serem conhecidos.

Medições adicionais de 20/11/2026 (suíte ampliada de 108 ataques OWASP LLM Top 10 e 54 benignas, `llama3.1:8b`, semente 42, fontes e ressalvas na seção B.1 em [docs/resultados.md](docs/resultados.md)):

- **ASR (`redteam/attacks_owasp_100/`, 9 categorias)**: sem guardrails `20.4%` (22/108, IC 95% `[13.9; 28.9]`) vs com `--guardrails all` `4.6%` (5/108, IC 95% `[2.0; 10.4]`); 1 erro do agente na baseline (owasp-107, HTTP 500 do Ollama).
- **Falsos positivos**: `0/54` nas benignas novas (IC 95% `[0.0; 6.6]`) e `0/50` no dataset de avaliação (IC 95% `[0.0; 7.1]`).
- **Ressalva**: a suíte não é cega (foi escrita no mesmo projeto das defesas), há uma execução por configuração e um único modelo de 8B.

### Avaliação A/B de prompts (v1 vs v2)

50 perguntas. Métrica determinística (checagens):

| Item | Valor |
|---|---|
| Média v1 | 0.7067 |
| Média v2 | 0.6133 |
| Diferença média (v2 - v1) | -0.0933 |
| IC 95% da diferença (bootstrap) | [-0.1933, +0.0067] |
| p-valor (permutação pareada, bilateral) | 0.0929 |

Nota do juiz (1 a 5):

| Item | Valor |
|---|---|
| Média v1 | 4.1933 |
| Média v2 | 3.4267 |
| Diferença média (v2 - v1) | -0.7667 |
| IC 95% da diferença (bootstrap) | [-1.3600, -0.1800] |
| p-valor (permutação pareada, bilateral) | 0.0154 |

Ressalvas: pelas checagens, a diferença não é distinguível de zero a 5%. O juiz é o mesmo modelo de 8B que gera as respostas (viés de autopreferência), as notas são ordinais e a rubrica não foi calibrada contra humanos; ele complementa as checagens, não as substitui. Detalhes (taxa por checagem, execução com guardrails) em [docs/resultados.md](docs/resultados.md).

Medições adicionais de 19/11/2026 (checagens determinísticas sem `--judge`, modelo `llama3.1:8b`, `temperature=0`, fontes em [docs/resultados.md](docs/resultados.md)):

- **Multi-execução (`evals/dataset.jsonl`, 50 casos × 3 execuções, sementes 42, 43 e 44, `evals/results/v1_vs_v2_multirun.md`)**: v1 `0.7067` (`run_stdev` `0.0000`, consistência de score `100.0%` e de resposta `98.0%`) vs v2 `0.6133` (`run_stdev` `0.0000`, consistência `100.0%` / `100.0%`), diferença `-0.0933`, IC 95% `[-0.1933, +0.0067]`, `p = 0.0929`.
- **Auditoria ampliada (`evals/dataset_audit_200.jsonl`, 200 casos × 1 execução, semente 42, `evals/results/audit_200_v1_vs_v2.md`)**: v1 `0.7750` vs v2 `0.6217`, diferença `-0.1533`, IC 95% `[-0.2100, -0.0950]`, `p = 0.0001` (v2 melhora formato `99.0%` vs `86.5%`, mas piora citação `44.5%` vs `82.5%` e termos esperados `35.8%` vs `58.8%`).

## Auditar seu próprio agente

Por padrão o kit audita o agente de exemplo (`examples.rag_agent`). Para auditar outro agente em Python, acrescente `target` ao `agent.yaml`:

```yaml
target:
  type: python
  ref: "meu_pacote.meu_agente:run"   # pacote.modulo:funcao, dentro da raiz do projeto
```

```python
def run(request: dict, llm=None) -> dict:
    # request: {"question": str, "context": str | None, "tools": list | None}
    return {
        "answer": "texto da resposta",
        "tool_calls": [{"name": "send_email", "arguments": {"to": "x"}}],  # opcional
        "trace_id": None,                                                  # opcional
    }
```

Rode da raiz do projeto: `aok eval ... --config agent.yaml` e `aok redteam run --config agent.yaml`. Resposta fora do contrato vira erro do caso, sem derrubar a execução. Se `run` tiver o parâmetro `llm`, o kit injeta o LLM e conta os tokens; senão os tokens ficam "não registrados" (nunca zero).

Limitações:

- Só Python. `type: http` é recusado na validação (ainda não é suportado; ADR-028).
- Semente não controlada pelo kit: a semente e o modelo do agente externo são dele; só o agente de exemplo é reproduzido com semente fixa. O sidecar de proveniência registra `target.type`, `target.ref` e `seed_controlled_by_kit: false`.
- Red team: o kit não executa as ferramentas do agente externo; mede só os `tool_calls` que ele declara. Sem `tool_calls` na resposta, a métrica de ferramenta daquele caso fica "não avaliada" e sai de n e do ASR (nunca conta como bloqueio). Guardrails do kit (`--guardrails`) só se aplicam ao agente de exemplo. Os prompts v1/v2 do eval não se aplicam: o agente externo usa o próprio prompt.
- Risco: `mod:fn` importa e executa código. O kit só importa módulos que resolvem dentro da raiz do projeto, mas isso não é um sandbox. Não rode target python em PR de fork no CI nem com segredos expostos; o red team envia entradas adversariais, então aponte para um ambiente sem ações reais (e-mail, exclusão).
- Falsos positivos: `python -m agent_ops_kit.redteam.false_positives --config agent.yaml ...` audita o seu agente (sem guardrails do kit). O relatório (`aok report build`) mostra qual agente foi auditado e avisa quando eval, red team e falsos positivos apontam agentes diferentes ou há casos "não avaliados".

## Limitações

- Modelo local pequeno (llama3.1:8b): tudo foi medido com ele. O ASR não generaliza para outros modelos, prompts ou dados, e o modelo às vezes responde "não encontrei" sem consultar os documentos.
- Dataset de 50 casos e 40 ataques: intervalos de confiança largos, uma execução por configuração.
- Os guardrails combinam heurísticas (padrões de texto, normalização anti-homoglyphs e anti-token-splitting, decodificação segura de Base64/Hex e janela multi-turn), allowlist, canary e classificador semântico local TF-IDF opcional, mas ainda podem ser contornados por paráfrases inéditas, outros idiomas ou ofuscações em múltiplas camadas. Não são proteção garantida.
- A suíte padrão versionada de 40 ataques e a suíte expandida (`redteam/attacks_owasp_100/`, 108 ataques) não são reservadas nem cegas; a avaliação cega exige fornecer um diretório externo fora do controle de versão via `--blind-attacks-dir` ou `AOK_BLIND_ATTACKS_DIR`. As medições com modelo local sobre a suíte expandida e as 54 benignas de `redteam/benign_expanded/benign_50.jsonl` foram feitas entre 19 e 20/11/2026, com uma execução por configuração (seção B.1 em [docs/resultados.md](docs/resultados.md)).
- A auditoria usa hash encadeado, com assinatura digital opcional da âncora (Ed25519 ou HMAC-SHA256, ADR-004 e ADR-018): sem assinatura, apagar o fim do arquivo ou reescrever toda a cadeia não é detectado sem uma âncora externa; mesmo com assinatura, depende de arquivar o recibo `.sig.json` fora do log e não inclui carimbo de tempo externo confiável (RFC 3161 TSA).
- O CI valida respostas gravadas e o manifesto; não reexecuta o modelo (ADR-001).
- O gate do eval foi exercitado em 2 PRs de teste, fechados sem mesclar ([#1](https://github.com/Athurgomes/Agent-Ops-Kit/pull/1) e [#2](https://github.com/Athurgomes/Agent-Ops-Kit/pull/2)); resultados em [docs/resultados.md](docs/resultados.md). Ele usa respostas gravadas, o prompt piorado foi degradado de propósito e foi uma execução por PR: é um teste de mecanismo, não uma medida de qualidade.
- O agente de referência usa documentos fictícios; nada aqui foi validado com dados reais.

## Próximos passos

Nada disto existe ainda:

- Eventos do agente em Kafka, com consumidores de auditoria e métricas.
- Adaptador para um segundo framework de agentes.
- Exportar métricas para Prometheus e Grafana.
- Execução em AWS/Bedrock.
- Publicar o pacote (hoje só instala a partir do repositório).
- Na plataforma: SSO e validação de carga em nuvem.

## Estrutura do repositório

```
src/agent_ops_kit/   pacote: cli (new, eval, redteam, audit, report, check), tracing, audit, metrics,
                     guardrails/, eval/, redteam/, report/, templates/
examples/rag_agent/  agente de referência e corpus fictício
evals/               dataset padrão (50 casos), dataset de auditoria (200 casos), prompts v1/v2, respostas gravadas, manifesto, relatórios
redteam/             ataques (40 originais + 108 OWASP expandidos), benignas (12 + 54), resultados gravados
platform/            plataforma: aok_platform/ (API FastAPI), portal/ (React), Dockerfile, docker-compose.yml
docs/                arquitetura, decisões (ADRs), resultados, demo-cli.gif
scripts/demo.sh      demo reproduzível do kit (respostas gravadas)
scripts/demo_plataforma.py   sobe a plataforma de demonstração com um comando
evidencias/          capturas de tela reais (terminal, Jaeger, GitHub, portal), com índice
tests/               testes (sem Ollama e sem Docker)
.github/workflows/   ci.yml (test, portal, postgres) e eval.yml (gate)
docker-compose.yml   Jaeger
```

## Licença

MIT. Veja [LICENSE](LICENSE).
