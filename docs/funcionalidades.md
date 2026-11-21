# Funcionalidades

Inventário do que está implementado no repositório em 21/11/2026 (commit `f31c42f`), para quem nunca viu o projeto. O agent-ops-kit é uma camada de observabilidade, avaliação e segurança para agentes de IA. Este arquivo só lista o que existe; números medidos e ressalvas estão em [resultados.md](resultados.md), a estrutura em [arquitetura.md](arquitetura.md) e o porquê de cada escolha em [decisoes.md](decisoes.md). Na coluna "Ref", ADR e arquivo de teste em `tests/`.

## 1. CLI `aok`

O comando pode não estar no PATH; use `python -m agent_ops_kit.cli` no lugar.

| Comando | O que faz | Ref |
|---|---|---|
| `aok new NOME [--dir]` | gera um agente RAG já instrumentado (tracing, auditoria, guardrails) | ADR-005, `test_new.py` |
| `aok eval --baseline V --candidate V` | compara duas variantes de prompt, com A/B pareado | ADR-002, `test_ab.py`, `test_runner.py` |
| `aok eval --reuse [--no-verify]` | relê respostas gravadas, sem modelo, e confere o manifesto (prompt, dataset, modelo) | ADR-001, `test_manifest.py` |
| `aok eval --judge` | acrescenta a nota do juiz por LLM (usa o modelo) | ADR-003, `test_judge.py` |
| `aok eval --runs N` | N execuções por caso, para medir variância | ADR-019, `test_eval_multirun.py` |
| `aok eval --dataset`, `--prompts-dir`, `--answers-dir`, `--config`, `--limit`, `--seed`, `--prices` | escolhe dataset, prompts, pasta de respostas, agente, subconjunto, semente (padrão 42) e tabela de preços | `test_cli.py` |
| `aok eval --fail-on-regression` | código 1 se a diferença média é menor que 0 e p menor que 0,05 (gate de CI) | ADR-001, `test_cli.py` |
| `aok eval --report`, `--summary` | grava o markdown completo ou imprime só o placar | `test_cli.py` |
| `aok redteam run --guardrails none\|all\|lista --out ARQ.jsonl` | roda a suíte de ataques (usa o modelo local), com ou sem guardrails | `test_redteam_harness.py` |
| `aok redteam run --attacks-dir`, `--limit`, `--seed`, `--config` | escolhe suíte, subconjunto, semente e agente a auditar | `test_redteam_attacks.py`, `test_target.py` |
| `aok redteam run --blind-attacks-dir`, `--blind-only` | suíte cega fora do repositório (também `AOK_BLIND_ATTACKS_DIR`) | ADR-021, `test_redteam_owasp_and_blind.py` |
| `aok redteam run --evidence-root` | pasta de evidências fora do repositório (`@evidence/...`) | ADR-030, `test_target_report.py` |
| `aok redteam report --baseline --guardrails [--fp-dir] [--summary]` | relatório do red team a partir dos JSONL gravados, sem modelo | `test_redteam_report.py` |
| `python -m agent_ops_kit.redteam.false_positives` | mede falsos positivos em perguntas legítimas (`--out-dir`, `--dataset`, `--benign`, `--config`, `--seed`) | `test_redteam_harness.py`, `test_target.py` |
| `aok audit verify LOG [--anchor] [--expected-n] [--signature] [--public-key\|--hmac-key-env]` | recalcula a cadeia de hashes; opcionalmente confere âncora e assinatura (código 1 se quebrada) | ADR-004, ADR-018, `test_audit.py`, `test_audit_signing.py` |
| `aok audit report LOG`, `aok audit anchor LOG` | relatório markdown do log; imprime o último hash | ADR-004, `test_audit.py` |
| `aok audit keygen`, `aok audit sign` | gera par Ed25519 em PEM; assina a âncora e grava o recibo `.sig.json` (Ed25519 ou HMAC por variável de ambiente) | ADR-018, `test_audit_signing.py` |
| `aok report build --out PASTA` | gera o pacote do relatório sem rodar modelo | ADR-006, ADR-013, `test_report.py` |
| `aok report build --policy`, `--coverage-map` | troca a política do semáforo ou o mapa OWASP | ADR-023, ADR-027, `test_policy.py`, `test_coverage.py` |
| `aok report build --audit`, `--audit-signature`, `--audit-public-key`, `--audit-hmac-key-env` | inclui o resultado da verificação do log de auditoria (o log não entra no pacote) | ADR-018, `test_report.py` |
| `aok report build --previous`, `--redteam-baseline`, `--redteam-guardrails`, `--fp-dir`, `--evidence-root` | compara com relatório anterior; aponta os resultados do red team (os três juntos ou nenhum); evidências externas | ADR-028, ADR-030, `test_target_report.py` |
| `aok report verify PASTA [--repo-root] [--json]` | confere o pacote offline contra os arquivos de evidência | ADR-026, `test_report_verify.py` |
| `aok report verify --public-key`, `--require-signature`, `--audit-hmac-key-env`, `--evidence-root` | confere `relatorio.json.sig`; torna a falta de assinatura uma falha; chave HMAC do log; raiz das evidências | ADR-029, ADR-030, `test_report_signature.py`, `test_report_verify.py` |
| `aok check [--publish PASTA\|URL] [--agent-id]` | gera o pacote (mesmos argumentos do `report build`) e publica em pasta local versionada ou na plataforma (token em `AOK_PLATFORM_TOKEN`) | ADR-006, ADR-007, `test_publish.py`, `test_platform_reports.py` |

## 2. Relatório

`aok report build` e `aok check` leem resultados gravados e produzem um pacote determinístico (mesma entrada, mesmos bytes), sem modelo.

| Item | O que é | Ref |
|---|---|---|
| `relatorio.json` | dados completos e fonte dos outros arquivos | ADR-006, `test_report.py` |
| `relatorio.md` e `relatorio.html` | estrutura técnico-executiva baseada na ABNT NBR 10719:2015 e NBR 6024:2012, com CSS A4 para impressão ou PDF pelo navegador | ADR-013, `test_report.py` |
| `pacote.json` | manifesto com hashes sha256 dos arquivos | ADR-006, `test_publish.py` |
| `relatorio.json.sig` | assinatura Ed25519 dos bytes do `relatorio.json`, só quando há chave em `AOK_SIGNING_KEY_FILE` ou `AOK_SIGNING_KEY_PEM` | ADR-029, `test_report_signature.py` |
| Sidecars `.meta.json` | gravados junto dos resultados do red team e dos falsos positivos (`fp.meta.json`) e lidos pelo build; guardam proveniência da execução | ADR-022, `test_provenance.py` |
| Semáforo e política | cor pela pior severidade entre as regras que falharam; regras em `policies/default.yaml`, com limiar, valor observado e resultado por regra, e sha256 da política no relatório. Métrica ausente vira "não avaliada" e nunca dá verde. Os limiares são provisórios | ADR-023, `test_policy.py` |
| Proveniência | versão do kit, commit e árvore com mudanças, ambiente, modelo, digest e versão do Ollama, comando, sementes, limites de geração e sha256 das entradas; campos de execuções antigas ficam "não registrado" | ADR-022, `test_provenance.py` |
| Achados | `findings[]` por ataque com sucesso, erro do red team, benigna bloqueada e caso do eval que piorou; cada um aponta arquivo, linha, sha256 do registro, `run_id` e `trace_id`. Severidade é tabela provisória por categoria. Sem texto de ataque | ADR-024, `test_findings.py` |
| Estatística | teste de McNemar exato (baseline contra guardrails), efeito mínimo detectável e ressalvas geradas dos dados (n, IC, suíte cega ou não, commits diferentes) | ADR-025, `test_stats.py` |
| Cobertura OWASP | mapa do OWASP LLM Top 10 (2025) com status "testado", "só controle" ou "não coberto", em `policies/coverage/owasp_llm_2025.yaml`. Não é certificação | ADR-027, `test_coverage.py` |
| Agente auditado | mostra qual agente foi medido e avisa quando eval, red team e falsos positivos apontam agentes diferentes ou há casos "não avaliados" | ADR-028, `test_target_report.py` |
| `aok report verify` | recalcula médias, IC, p-valor, ASR com Wilson, McNemar, falsos positivos, semáforo, hashes, achados, cobertura, cadeia e assinatura do log, sementes e a renderização do md e do html. Exit 0 só se tudo confere; 1 se falha ou evidência ausente; 2 se o pacote é ilegível | ADR-026, `test_report_verify.py` |
| Assinatura | prova quem publicou e que os bytes não mudaram; não prova que o eval e o red team rodaram | ADR-029, `test_report_signature.py` |

O relatório é autodeclarado: nem o `verify` nem a assinatura reexecutam a medição.

## 3. Auditoria

| Item | O que é | Ref |
|---|---|---|
| Log JSONL append-only | cada linha traz `prev_hash` e `hash` (sha256); o agente grava eventos de cada passo | ADR-004, `test_audit.py`, `test_audit_integration.py` |
| Verificação | recalcula a cadeia; sem âncora externa, apagar o fim do arquivo não é detectado | ADR-004, `test_audit.py` |
| Âncora e assinatura | último hash guardado fora do arquivo; recibo assinado com Ed25519 ou HMAC-SHA256 (chave HMAC só por variável de ambiente). Sem carimbo de tempo externo | ADR-018, `test_audit_signing.py` |
| No relatório | só o resultado da verificação e a âncora entram; o log não | ADR-006, `test_report.py` |

## 4. Avaliação (eval)

| Item | O que é | Ref |
|---|---|---|
| Datasets | `evals/dataset.jsonl` (50 casos) e `evals/dataset_audit_200.jsonl` (200 casos) | ADR-019, `test_dataset.py`, `test_eval_dataset_audit.py` |
| Checagens determinísticas | formato, citação, termos esperados e outras, sem modelo | `test_checks.py` |
| A/B pareado | diferença média, IC por bootstrap e p-valor por permutação pareada, semente fixa | ADR-002, `test_ab.py` |
| Juiz | nota de 1 a 5 pelo mesmo modelo que gera as respostas (viés de autopreferência), opcional | ADR-003, `test_judge.py` |
| Variantes de prompt | v1 e v2 em `evals/prompts` | `test_prompts.py` |
| Multi-execução | `--runs N` com sementes `seed`, `seed+1`, ...; desvio entre execuções e consistência | ADR-019, `test_eval_multirun.py` |
| Respostas gravadas e manifesto | o gate de CI reavalia o que foi gravado e recusa se prompt, dataset ou modelo divergem | ADR-001, `test_manifest.py`, `test_runner.py` |
| Métricas | latência, tokens, erro de tool e custo estimado (`n/d` quando tokens não são registrados) | ADR-028, `test_metrics.py` |
| Limite de geração | chamadas ao Ollama com no máximo 2048 tokens gerados e timeout de 180 s; estouro vira `error` do caso | ADR-028, `test_ollama_chat.py` |

## 5. Guardrails e red team

| Item | O que é | Ref |
|---|---|---|
| Filtro de entrada | heurísticas PT/EN, normalização contra homoglyphs e token splitting, decodificação segura de Base64 e Hex, janela multi-turn e classificador semântico local TF-IDF opcional | ADR-020, `test_guardrails.py`, `test_guardrails_advanced.py` |
| Allowlist de tools, marcação de conteúdo não confiável, canary e filtro de saída | camadas restantes dos guardrails | `test_guardrails.py`, `test_guardrails_integration.py` |
| Suítes | 40 ataques originais, 108 ataques em 9 categorias OWASP LLM Top 10 (`redteam/attacks_owasp_100/`), 12 e 54 perguntas legítimas, todos em arquivos do repositório | ADR-021, `test_redteam_attacks.py`, `test_redteam_owasp_and_blind.py` |
| Medidas | ASR com intervalo de Wilson por categoria, atribuição por estágio (entrada, tool, saída) e taxa de falsos positivos | `test_redteam_report.py` |
| Suíte cega | diretório externo ao repositório (`--blind-attacks-dir` ou `AOK_BLIND_ATTACKS_DIR`); os registros cegos não gravam pergunta, resposta nem tools | ADR-021, `test_redteam_owasp_and_blind.py` |
| Evidências externas | `--evidence-root` grava `@evidence/...` em vez de caminho absoluto | ADR-030, `test_report_verify.py` |

Os guardrails são heurísticas e podem ser contornados. As suítes versionadas não são reservadas.

## 6. Adaptador de agente

O `agent.yaml` aceita `target: {type: python, ref: "pacote.modulo:funcao"}` (ADR-028, `test_target.py`, `test_target_report.py`). Sem `target`, vale o agente de referência.

- Entrada: `{"question": str, "context": str | None, "tools": list | None}`. Saída: `{"answer": str, "tool_calls": opcional, "trace_id": opcional}`.
- Se a função tem o parâmetro `llm`, o kit injeta o LLM e conta os tokens; sem o parâmetro, tokens "não registrados" e custo `n/d`.
- Saída fora do contrato vira `error` do caso e a execução segue.
- Red team: o kit não executa as ferramentas do agente externo e mede só os `tool_calls` declarados; sem eles o caso fica "não avaliado" e sai de n e do ASR. Guardrails do kit só valem para o agente de exemplo.
- O `ref` só importa módulos que resolvem dentro da raiz do projeto; isso não é sandbox, pois `mod:fn` executa código. `type: http` é recusado.
- A proveniência registra `target.type`, `target.ref` e `seed_controlled_by_kit: false`.

## 7. Plataforma (`platform/`)

API FastAPI que recebe o pacote publicado e serve o portal. Instância única, SQLite nos testes e Postgres no `platform/docker-compose.yml`.

| Grupo | Rotas | Quem acessa | Ref |
|---|---|---|---|
| Publicação | `POST /v1/reports` (esquema fechado, limite de 1 MiB, sha256 de cada arquivo, campo opcional `signature`) | token do agente | ADR-007, ADR-029, `test_platform_reports.py`, `test_platform_signature.py` |
| Sessão | `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/auth/me` | pessoa com e-mail e senha | ADR-008, `test_platform_portal.py` |
| Recuperação de senha | `GET /v1/auth/capabilities`, `POST /v1/auth/password/forgot`, `POST /v1/auth/password/reset` (só com SMTP configurado) | qualquer pessoa | ADR-012, `test_platform_recovery.py` |
| Leitura | `GET /v1/areas`, `/v1/areas/{id}/agents`, `/v1/agents/{id}/reports`, `/v1/reports/{id}` | `org_admin` e `area_viewer` (dentro do alcance) | ADR-008, `test_platform_portal.py` |
| Download | `GET /v1/reports/{id}/download?format=md\|html\|json`, `GET /v1/me/downloads`, `GET /v1/admin/downloads` | quem tem alcance; a última só `org_admin` | ADR-008, `test_platform_portal.py` |
| Admin: cadastro | `POST` e `PATCH` em `/v1/admin/areas`, `/agents`, `/users`; `POST` e `DELETE` em `/memberships` | `org_admin` | ADR-009, `test_platform_admin.py` |
| Admin: tokens | `GET` e `POST /v1/admin/agents/{id}/tokens`, `DELETE .../tokens/{token_id}` | `org_admin` | ADR-009, `test_platform_admin.py` |
| Admin: chaves | `GET` e `POST /v1/admin/agents/{id}/keys`, `DELETE .../keys/{key_id}` (chave pública Ed25519; chave privada e PEM inválido são recusados) | `org_admin` | ADR-029, `test_platform_signature.py` |
| Admin: listas | `GET /v1/admin/areas`, `/agents`, `/users`, `/memberships`, `/events` | `org_admin` | ADR-009, `test_platform_admin_lists.py` |
| Operador | `/v1/ops/auth/*`, `/v1/ops/organizations` (listar, criar, desativar, criar admin, reset de senha, detalhe), `/v1/ops/organizations/{id}/events`, `/v1/ops/events`; só com `AOK_OPS_ENABLED=true`; só metadados | operador | ADR-010, `test_platform_ops.py` |
| Saúde | `GET /v1/health` (banco e `AOK_DATA_DIR`; 200 ou 503) | qualquer | ADR-014, `test_platform_online_readiness.py` |

- **Papéis**: `org_admin` (toda a organização), `area_viewer` (a área e as sub-áreas), token de agente (só publica), operador (só metadados, fora de qualquer organização) e chave de bootstrap (`AOK_ADMIN_BOOTSTRAP_KEY`; com 2 ou mais organizações exige `X-Org-Slug`). Área fora do alcance responde 404. ADR-008 a ADR-011, `test_platform_multiorg.py`.
- **Assinatura**: com chave ativa cadastrada, assinatura ausente ou inválida é 422; chave revogada ou de outro agente também; `require_signature` por agente (padrão falso) exige assinatura válida; sem chave, o relatório fica "não assinado". A plataforma confere só os bytes do `relatorio.json`. ADR-029, `test_platform_signature.py`.
- **Migrações**: Alembic em `platform/aok_platform/migrations/versions/` (`0001_initial_schema`, `0002_rate_limit_entry`, `0003_report_signature`). ADR-016, `test_platform_migrations.py`.
- **Rate limit**: bloqueio de login por e-mail (5 falhas, 5 minutos) e limites da recuperação de senha, em tabela compartilhada no banco (`rate_limit_entry`). ADR-017, `test_platform_rate_limit.py`.
- **Paginação**: `limit` (1 a 500) e `offset` nas listagens do admin e do operador, com `X-Total-Count`. `test_platform_pagination.py`.
- **Trilhas**: `admin_event`, `operator_event` e `download_log`, imutáveis pela API. Login e leitura não têm trilha. ADR-009, ADR-010.
- **Operação online**: `AOK_DOCS_ENABLED`, `AOK_HSTS_ENABLED`, `AOK_TRUSTED_PROXIES` e headers de segurança. ADR-014, `test_platform_online_readiness.py`.

## 8. Portal Farol.

React, Vite, TypeScript e Tailwind, em `pt-BR`, servido pela API (ADR-015, `test_platform_seed_spa.py`).

| Tela | Rota | Quem |
|---|---|---|
| Landing pública | `/` | todos |
| Login, esqueci e redefinir senha | `/login`, `/forgot-password`, `/reset-password` | todos |
| Áreas e sub-áreas | `/app`, `/app/areas/:areaId` | autenticado |
| Relatórios do agente | `/app/areas/:areaId/agents/:agentId` | autenticado |
| Detalhe do relatório: semáforo com glifos, regras, ressalvas, selo "Assinado" ou "Não assinado" e downloads HTML, Markdown e JSON | `/app/reports/:reportId` | autenticado |
| Meus downloads | `/app/downloads` | autenticado |
| Todos os downloads | `/app/admin/downloads` | `org_admin` |
| Administração: áreas, agentes, detalhe do agente (tokens), usuários, atividade | `/app/admin/areas`, `agents`, `agents/:agentId`, `users`, `activity` | `org_admin` |
| Console do operador: login, organizações, detalhe, atividade | `/ops/login`, `/ops/organizations`, `/ops/organizations/:orgId`, `/ops/activity` | operador (sem link no site) |
| Não encontrado | qualquer outra | todos |

Não há tela de gestão de chaves públicas: elas são cadastradas pela API admin.

## 9. CI e scripts

| Item | O que faz | Ref |
|---|---|---|
| `.github/workflows/ci.yml` | jobs `test` (ruff e pytest), `portal` (build do front-end) e `postgres` (testes de plataforma em Postgres 16, com 3 testes que só rodam com `AOK_TEST_DATABASE_URL`) | ADR-007, `test_platform_pg_legacy.py` |
| `.github/workflows/eval.yml` | gate de regressão com respostas gravadas (`aok eval --reuse --fail-on-regression`), sem modelo | ADR-001, `test_manifest.py` |
| `scripts/demo.sh` | demo do kit com respostas gravadas e log de auditoria fictício, sem modelo, semente 42 | sem teste automatizado dedicado |
| `scripts/demo_plataforma.py` | sobe a plataforma de demonstração com um comando (SQLite, só em 127.0.0.1; `--porta`, `--publicar`, `--reset`, `--dados`) | `test_demo_plataforma.py` |
| `docker-compose.yml` | Jaeger para ver os traces | sem teste automatizado |
| Tracing | spans `agent.run`, `llm.call`, `tool.call` e `retrieval.query` por OTLP; desliga com `AOK_TRACING=off` | `test_tracing.py` |

## 10. O que não existe

- Adaptador de agente por HTTP e adaptador de framework; só o agente Python (ADR-028).
- `aok reproduce` (reexecução registrada no log assinado).
- Mapa NIST AI RMF e ISO/IEC 42001; só OWASP LLM Top 10 (ADR-027).
- A plataforma rodar `report verify` ou reexecutar eval e red team; ela só confere a assinatura (ADR-029).
- Tela de chaves públicas no portal.
- SSO, cadastro aberto, dark mode, PDF gerado no servidor e recuperação de senha por e-mail para operadores.
- Kafka, Prometheus e Grafana, deploy automatizado em nuvem e publicação em PyPI.
- Suíte de ataques reservada dentro do repositório: as suítes versionadas são públicas; a cega depende de uma pasta externa.
- Validação de carga e de mais de uma réplica da plataforma.
- Medições com mais de um modelo ou mais de uma execução por configuração.
