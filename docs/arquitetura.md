# Arquitetura

O agent-ops-kit é uma camada de observabilidade, avaliação e segurança para agentes de IA. Este documento descreve só o que existe no repositório. O agente de referência (`examples/rag_agent/`) é um RAG sobre documentos fictícios, com modelo local via Ollama.

## Fluxo

```mermaid
flowchart LR
    U[Usuário] --> IF[Filtro de entrada<br/>guardrails]
    IF -->|bloqueado| R[Resposta de recusa]
    IF --> A[Loop do agente<br/>LLM local via Ollama]
    A <--> T1[search_docs<br/>índice Chroma]
    A <--> T2[calculator]
    A <--> T3[current_date]
    A --> OF[Filtro de saída]
    OF --> R2[Resposta]

    A -. spans .-> OT[OpenTelemetry] -- OTLP --> J[Jaeger]
    A -. eventos .-> AU[(Log de auditoria<br/>JSONL, hash encadeado)]
    AU --> AC[aok audit<br/>verify / report / anchor]

    subgraph H[Harnesses, rodam o agente com o modelo ou leem execuções gravadas]
        EV[aok eval<br/>dataset, checagens, juiz,<br/>A/B pareado, gate de CI]
        RT[aok redteam<br/>ataques, critérios, ASR com Wilson,<br/>falsos positivos]
    end
    EV --> A
    RT --> A
    EV --> G[evals/answers + manifesto]
    G --> CI[CI: reavalia respostas gravadas]
```

Os guardrails também atuam na allowlist de tools (antes de cada chamada) e marcam o texto recuperado como não confiável. No red team, o estágio que bloqueou (input, tool ou output) é registrado por ataque.

## Componentes

- **Agente** (`examples/rag_agent/agent.py`): loop simples com tool calling nativo do Ollama, no máximo 5 iterações. Cada passo gera spans e eventos de auditoria.
- **Tracing**: spans `agent.run`, `llm.call`, `tool.call` e `retrieval.query`, com atributos no estilo das convenções GenAI do OpenTelemetry, exportados por OTLP gRPC (padrão `localhost:4317`) para o Jaeger do `docker-compose.yml`. Desliga com `AOK_TRACING=off`.
- **Auditoria**: JSONL append-only; cada linha traz `prev_hash` e `hash` (sha256). `aok audit verify` recalcula a cadeia, `report` gera markdown, `anchor` imprime o último hash para guardar fora do arquivo. Não há assinatura (ver ADR-004).
- **Guardrails**: filtro de entrada (heurísticas PT/EN, mais classificador opcional fail-open), allowlist de tools, marcação de conteúdo não confiável, canary no prompt do sistema e filtro de saída. São heurísticas, contornáveis.
- **Avaliação**: dataset de 50 casos, checagens determinísticas, juiz opcional (mesmo modelo de 8B), A/B pareado (permutação e bootstrap, semente fixa) e gate de CI que reavalia respostas gravadas conferindo um manifesto.
- **Red team**: ataques em arquivos do repositório (`redteam/`), critérios de sucesso por categoria, ASR com intervalo de Wilson e medição de falsos positivos em perguntas legítimas.
- **Relatório** (`aok report build`, `aok check --publish`): resultados gravados (eval e red team, mais o resultado da verificação da auditoria, se houver) viram um pacote (`relatorio.md/html/json`, `pacote.json`) que `--publish` copia para uma pasta local versionada, `<pasta>/<agent-id>/<timestamp UTC>/`, com `index.json` listando as versões. Não roda modelo e o log de auditoria não entra no pacote (ADR-006).
- **Plataforma** (`platform/`, fases 2 e 3): serviço FastAPI que recebe o pacote por `POST /v1/reports` e, para pessoas com sessão, serve a leitura e o portal; ver abaixo, ADR-007 e ADR-008.
- **Template** (`aok new`): gera um agente já instrumentado a partir de `src/agent_ops_kit/templates/agent/`.

## Plataforma (`platform/`)

```mermaid
flowchart LR
    CK[aok check --publish URL<br/>token em AOK_PLATFORM_TOKEN] -->|POST /v1/reports<br/>pacote: agregados e hashes| API[API FastAPI]
    AD[Admin<br/>chave AOK_ADMIN_BOOTSTRAP_KEY] -->|/v1/admin: áreas, agentes, tokens| API
    API --> DB[(SQLite nos testes<br/>Postgres no Docker)]
    API --> FS[(Arquivos dos relatórios<br/>AOK_DATA_DIR)]
    PO[Portal React<br/>servido pela API] -->|cookie de sessão| API
    API --> DL[(download_log)]
    API --> AE[(admin_event)]
```

O admin cria área e agente e emite o token do agente (guardado como hash). O agente publica com `platform.agent_id` do `agent.yaml` (ou `--agent-id`), que deve ser o slug dono do token. A API valida o esquema fechado, o limite de 1 MiB e o sha256 de cada arquivo, e grava uma versão com `seq` por agente. O log de auditoria não sobe.

Fase 3 (ADR-008), fluxos:

- **Login**: `POST /v1/auth/login` (e-mail e senha, scrypt) cria uma sessão e devolve o cookie `aok_session` (HttpOnly, SameSite=Strict). O throttle por e-mail é em memória.
- **Leitura**: o portal chama `/v1/areas`, `/v1/areas/{id}/agents`, `/v1/agents/{id}/reports` e `/v1/reports/{id}`. O alcance vem da `membership`: `area_viewer` vê a área e as sub-áreas (CTE recursiva), `org_admin` vê tudo, o resto responde 404. O token de agente não lê.
- **Telas do portal** (interface em inglês; conteúdo dos relatórios vindo do backend em português): `/` (landing), `/login`, `/app` e `/app/areas/:areaId` (áreas), `/app/areas/:areaId/agents/:agentId` (relatórios do agente), `/app/reports/:reportId` (detalhe e download), `/app/downloads` e, só `org_admin`, `/app/admin/downloads`. Sign Up, Pricing, redes sociais e links de rodapé são placeholders "Soon", não clicáveis.
- **Administração** (ADR-009, só `org_admin`): telas `/app/admin/areas`, `agents`, `agents/:id` (tokens), `users` e `activity`. Rotas novas: `GET /v1/admin/areas`, `/agents`, `/agents/{id}/tokens`, `/users`, `/memberships` e `/events`. Leituras e escritas ficam na organização de quem chama (alvo de outra organização: 404). Bloqueios 409: não desativar a própria conta nem revogar o próprio `org_admin`; nunca o último `org_admin` ativo (vale também para a chave de bootstrap, que usa a primeira organização).
- **Trilha `admin_event`**: toda escrita administrativa grava quando, quem, ação e alvo, sem segredos, na mesma transação. Imutável pela API (e pelo ORM); quem opera o banco pode alterar. `GET /v1/admin/events` só aceita sessão de `org_admin`, com `limit` e `offset`. As demais listagens do admin não têm paginação.
- **Download com log**: `GET /v1/reports/{id}/download?format=md|html|json` confere o alcance, grava uma linha em `download_log` (baixado em, relatório gerado em) e devolve o arquivo. `/v1/me/downloads` mostra os do próprio usuário; `/v1/admin/downloads` (`org_admin` por sessão) mostra todos.

### Multi-organização e operador (ADR-010 e ADR-011)

- Tabelas novas: `platform_operator`, `operator_session`, `operator_event` (imutável pela API e pelo ORM). O operador não pertence a nenhuma organização.
- Rotas `/v1/ops/*`: só existem com `AOK_OPS_ENABLED=true`; sessão e cookie próprios. Nenhuma devolve conteúdo de relatório, ressalvas, arquivos, hashes de relatório, tokens ou download.
- Armazenamento de relatórios novos: `AOK_DATA_DIR/<org_id>/<slug>/<sha256>`.
- Chave de bootstrap: 1 organização, como antes; 2 ou mais exigem `X-Org-Slug`.

```mermaid
flowchart LR
  Op[Operador] -->|/ops, /v1/ops| OPS[ops.py]
  Adm[org_admin / viewer] -->|/app, /v1| API[API por organização]
  Ag[Token de agente] -->|POST /v1/reports| API
  OPS --> DB[(platform_operator, operator_session, operator_event, organization, ...)]
  API --> DB
  API --> FS[(AOK_DATA_DIR/org_id/slug/sha256)]
```

## Módulos

| Arquivo | Responsabilidade |
|---|---|
| `src/agent_ops_kit/cli.py` | CLI `aok`: `new`, `eval`, `redteam`, `audit` |
| `src/agent_ops_kit/config.py` | leitura e validação do `agent.yaml` |
| `src/agent_ops_kit/tracing.py` | setup do OpenTelemetry e helpers de span |
| `src/agent_ops_kit/audit.py` | log JSONL com hash encadeado, `verify`, `anchor` |
| `src/agent_ops_kit/metrics.py` | latência, tokens, erro de tool e custo estimado |
| `src/agent_ops_kit/guardrails/` | filtros de entrada e saída, allowlist, marcação de não confiável, canary |
| `src/agent_ops_kit/eval/dataset.py` | carga do dataset |
| `src/agent_ops_kit/eval/checks.py` | checagens determinísticas |
| `src/agent_ops_kit/eval/judge.py` | juiz por LLM (opcional) |
| `src/agent_ops_kit/eval/ab.py` | A/B pareado: permutação, bootstrap |
| `src/agent_ops_kit/eval/prompts.py` | carga de variantes de prompt |
| `src/agent_ops_kit/eval/runner.py` | execução, respostas gravadas e manifesto |
| `src/agent_ops_kit/redteam/attacks.py` | carga dos ataques |
| `src/agent_ops_kit/redteam/criteria.py` | critérios de sucesso de ataque |
| `src/agent_ops_kit/redteam/harness.py` | execução da suíte, com ou sem guardrails |
| `src/agent_ops_kit/redteam/testbed.py` | constantes do testbed (tools proibidas falsas, dados fictícios) |
| `src/agent_ops_kit/redteam/false_positives.py` | taxa de falsos positivos |
| `src/agent_ops_kit/redteam/report.py` | relatório (ASR, Wilson, atribuição por estágio) |
| `src/agent_ops_kit/report/` | pacote de relatório: `build` (agrega resultados gravados), `render` (md/html/json), `publish` (pasta local versionada) |
| `src/agent_ops_kit/templates/agent/` | template do `aok new` |
| `examples/rag_agent/` | agente de referência (agent, tools, indexer, corpus fictício) |
| `.github/workflows/` | `ci.yml` (ruff e pytest) e `eval.yml` (gate com respostas gravadas) |
| `docker-compose.yml` | Jaeger (all-in-one) |
| `platform/aok_platform/` | API da plataforma: `app`, `auth` (senha, token, papéis), `sessions` (login, sessão, throttle), `portal` (leitura, download, histórico), `models` (inclui `admin_event`), `reports`, `db`, `seed_demo` |
| `platform/aok_platform/ops.py` | rotas `/v1/ops/*` do operador (ADR-010): organizações com contagens, criar e desativar, criar admin e reset de senha, visão geral só de metadados, trilhas |
| `platform/aok_platform/create_org.py` | `python -m aok_platform.create_org`: cria organização (slug, nome) |
| `platform/aok_platform/create_operator.py` | `python -m aok_platform.create_operator`: cria operador com senha aleatória impressa uma vez; `--reset-password`, `--activate` |
| `platform/aok_platform/db.py` (`ensure_schema`) | no startup, adiciona colunas e tabelas novas e preenche valores, de forma idempotente (não é Alembic) |
| `platform/portal/src/pages/ops/` | console do operador em `/ops/*` (sem link no site; 404 comum com `AOK_OPS_ENABLED` desligado) |
| `platform/portal/` | front-end React, Vite, TypeScript e Tailwind, servido pela API |
| `platform/docker-compose.yml` | API e Postgres (`docker build` verificado localmente, antes do redesenho do visual e das telas de administração e não reverificado depois; o run de CI do commit c3ca947 (push no main, com as telas de administração) terminou com sucesso nos jobs test e portal; para os commits posteriores o CI ainda não foi verificado; Postgres real não verificado) |

## Decisões

As decisões e suas limitações estão em [decisoes.md](decisoes.md):

- ADR-001: como o CI roda sem modelo (respostas gravadas e manifesto).
- ADR-002: teste de permutação pareado e bootstrap com semente fixa.
- ADR-003: o juiz é o mesmo modelo de 8B.
- ADR-004: auditoria com hash encadeado (sem assinatura).
- ADR-005: template do `aok new` dentro do pacote, com cópia do núcleo do agente.
- ADR-006: relatório publicado em pasta local versionada, só agregados e hashes.
- ADR-007: plataforma em `platform/`, relatório autodeclarado, só agregados e hashes.
- ADR-008: portal e login (scrypt, cookie de sessão, CSRF só por SameSite, acesso por área, `download_log`).
- ADR-009: administração do portal e trilha `admin_event`.
- ADR-010: operador da plataforma (só metadados, desligado por padrão).
- ADR-011: isolamento multi-organização.

Os números medidos e as ressalvas estão em [resultados.md](resultados.md).

## O que NÃO existe ainda

- Kafka (eventos do agente em tópico, consumidores de auditoria e métricas).
- Adaptador para outro framework de agentes: só existe o loop do agente de referência.
- Prometheus e Grafana: as métricas são calculadas em Python, não exportadas.
- Na plataforma: SSO, Sign Up, recuperação de senha por e-mail, Alembic (migração formal), dark mode, PDF e paginação das listagens do admin. Trilha de login e de leitura também não existe (só download e escritas administrativas).
- Deploy em nuvem.
- Publicação em PyPI: o pacote se instala a partir do repositório.
- Validação do gate do eval em um PR real que piore um prompt: até agora só foi simulado localmente (ver README).
