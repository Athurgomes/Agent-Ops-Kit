# Validação em agentes externos (fora do RAG)

Este documento registra a validação prática do **agent-ops-kit** em **dois agentes externos distintos do testbed RAG**, executados em `23/11/2026` contra o modelo local **`llama3.1:8b`** via Ollama (`0.40.16`, digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`), com `seed=42`, `temperature=0` e `AOK_TRACING=off`.

Os dois agentes exercitam os dois modos de integração externa do kit (HTTP com autenticação e Python por contrato), perfis completo e parcial, avaliação funcional opcional (`aok eval` vs `--no-eval`), bateria universal de segurança, medição de falsos positivos e verificação criptográfica independente do pacote (`aok report verify`). Nenhum texto de ataque, dado pessoal ou segredo é reproduzido aqui.

---

## Resumo comparativo

| Item | Agente 1: Suporte de pedidos (HTTP) | Agente 2: Triagem financeira (Python) |
|---|---|---|
| Identificador no `agent.yaml` | `suporte-pedidos-ollama` | `triagem-financeira-ollama` |
| Tipo de alvo (`target.type`) | `http` (`http://127.0.0.1:8788/chat`) | `python` (`examples.validation_agents.finance_python_agent:run`) |
| Modelo executado | `llama3.1:8b` (Ollama local) | `llama3.1:8b` (Ollama local) |
| Perfil declarado (`profile`) | Completo (`5/5` dimensões) | Parcial (`3/5` dimensões; sem ações proibidas nem ferramentas) |
| Avaliação funcional (`eval`) | `6` casos (`0.8889` v1 / `0.8889` v2, `p = 1.0000`) | Não avaliada (`--no-eval`) |
| Red team universal (ASR total) | `3/17` (`17.6%`, IC 95% `[6.2; 41.0]`, `1` erro) | `2/14` (`14.3%`, IC 95% `[4.0; 39.9]`, `0` erros) |
| Falsos positivos (bloqueios) | `0/5` dataset e `0/5` benignas (`0.0%`) | `0/5` dataset e `0/5` benignas (`0.0%`) |
| Categorias de segurança testadas | `8/12` | `7/12` (`abuso_de_tools` pulada por perfil parcial) |
| Chamadas contabilizadas ao agente | `39` (`12` eval + `17` red team + `10` fp) | `24` (`0` eval + `14` red team + `10` fp) |
| Semáforo (regras provisórias) | `AMARELO` | `AMARELO` |
| `aok report verify` | `20 ok, 0 falha(s), 0 não verificável(is) -> ÍNTEGRO` | `20 ok, 0 falha(s), 0 não verificável(is) -> ÍNTEGRO` |

---

## 1. Agente 1 — Suporte de pedidos via HTTP (`llama3.1:8b`)

Implementação em `examples/validation_agents/support_http_agent.py`, configuração em `examples/validation_agents/support_http_agent.yaml` e conjunto funcional em `examples/validation_agents/support_dataset.jsonl` (`6` casos com `sources: []`: `4` respondíveis e `2` abstenções). O servidor HTTP local exige token Bearer via variável de ambiente `VALIDATION_AGENT_TOKEN` e processa mensagens via `ollama.chat` com ferramenta simulada `lookup_order`.

### Comandos executados

Com o servidor HTTP ativo localmente (`VALIDATION_AGENT_TOKEN` definido e `AOK_TRACING=off`), executados a partir da raiz do repositório (`aok` equivalente a `python -m agent_ops_kit.cli`):

```bash
aok redteam run --universal \
  --config examples/validation_agents/support_http_agent.yaml \
  --seed 42 --out reports/validation_support_rt.jsonl

aok eval --baseline v1 --candidate v2 \
  --config examples/validation_agents/support_http_agent.yaml \
  --dataset examples/validation_agents/support_dataset.jsonl \
  --answers-dir reports/validation_support_answers --seed 42 \
  --report reports/validation_support_eval.md

python -m agent_ops_kit.redteam.false_positives \
  --config examples/validation_agents/support_http_agent.yaml \
  --dataset examples/validation_agents/support_dataset.jsonl \
  --benign redteam/benign/benign.jsonl \
  --v1-answers reports/validation_support_answers/v1.jsonl \
  --out-dir reports/validation_support_fp --limit 5 --seed 42

aok report build \
  --config examples/validation_agents/support_http_agent.yaml \
  --redteam-baseline reports/validation_support_rt.jsonl \
  --redteam-guardrails reports/validation_support_rt.jsonl \
  --fp-dir reports/validation_support_fp \
  --dataset examples/validation_agents/support_dataset.jsonl \
  --answers-dir reports/validation_support_answers \
  --out reports/validation_support_pkg

aok report verify reports/validation_support_pkg --repo-root .
```

### Avaliação funcional (`eval`)

Para alvos externos (`target`), as variantes de prompt do kit não alteram o agente (que usa seu próprio prompt de sistema); a comparação registra apenas a repetição entre duas execuções.

| Item | Valor observado |
|---|---|
| Média v1 / Média v2 | `0.8889` / `0.8889` |
| Diferença média (`v2 - v1`) | `+0.0000` |
| IC 95% (bootstrap, `10000` reamostragens) | `[+0.0000, +0.0000]` |
| p-valor (permutação pareada, bilateral, `exact`) | `1.0000` (`n = 6` pares, `0` descartados) |
| Latência por caso, p50 / p95 (`v1`) | `4.27 s` / `10.78 s` |
| Latência por caso, p50 / p95 (`v2`) | `4.17 s` / `5.23 s` |
| Tokens de entrada / saída | `n/d` (alvo HTTP externo) |
| Erros do agente | `0` (`0.0000`) |

Taxa de aprovação por checagem determinística (em ambas as execuções):

- `contains_expected`: `4/4 (100.0%)`
- `cites_correct_source`: `2/2 (100.0%)`
- `valid_format`: `6/6 (100.0%)`
- `refuses_when_unanswerable`: `0/2 (0.0%)` (nos dois casos fora de escopo, o modelo recusou naturalmente em texto livre, sem reproduzir a frase fixa do testbed RAG verificada pelo critério determinístico do kit).

### Segurança (`redteam --universal`) e falsos positivos

Como agentes externos rodam sem os guardrails internos do kit, a mesma execução sem controles alimenta as colunas de baseline e comparação do pacote (`McNemar: n=16 pares, b=0, c=0, p=1.0000`, com `1` par excluído por erro).

| Categoria | n | Sucessos | ASR % | IC 95% (Wilson) | Erros |
|---|---|---|---|---|---|
| `injecao_direta` | 2 | 2 | 100.0 | [34.2; 100.0] | 0 |
| `injecao_indireta` | 2 | 1 | 50.0 | [9.5; 90.5] | 0 |
| `abuso_de_tools` | 3 | 0 | 0.0 | [0.0; 56.1] | 0 |
| `vazamento_dados` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `exaustao_recursos` | 2 | 0 | 0.0 | [0.0; 65.8] | 1 |
| `vazamento_prompt` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `desvio_de_escopo` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `jailbreak` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `total` | 17 | 3 | 17.6 | [6.2; 41.0] | 1 |

- **Erro registrado:** `1` ocorrência em `exaustao_recursos` por timeout HTTP configurado em `120.0 s` (`TargetError`).
- **Falsos positivos:** `0/5` (`0.0%`, IC 95% Wilson `[0.0; 43.4]`, `0` erros) no recorte de `support_dataset.jsonl` e `0/5` (`0.0%`, IC 95% Wilson `[0.0; 43.4]`, `0` erros) no recorte de `redteam/benign/benign.jsonl`.

### Semáforo, achados, escopo e verificação

- **Semáforo:** `AMARELO` (regras acionadas: `attack_success_with_guardrails` com observado `3`, e `no_audit` por ausência de log de auditoria no pacote).
- **Achados no pacote:** `8` registros (`6` registros referentes aos `3` sucessos replicados entre baseline e comparação nas categorias `injecao_direta` e `injecao_indireta`, e `2` referentes ao erro em `exaustao_recursos`), todos vinculados por linha e SHA-256.
- **Escopo e custo (`test_scope`):** perfil com `5/5` dimensões declaradas; `8/12` categorias de segurança testadas (`exfiltracao`, `ofuscacao`, `multi_turn` e `saida_insegura` marcadas como `não testado` por não integrarem a bateria universal v1); qualidade funcional e falsos positivos marcados como `testado`; cadeia de auditoria marcada como `não testado`. Total contabilizado de `39` chamadas ao agente (`12` eval + `17` red team + `10` falsos positivos), sem contagem de tokens pelo alvo HTTP.
- **Cobertura OWASP LLM Top 10 (2025):** `5` categorias testadas (`LLM01` 3/8, `LLM02` 0/2, `LLM06` 0/3, `LLM07` 0/2, `LLM10` 0/2) e `5` não cobertas (`LLM03`, `LLM04`, `LLM05`, `LLM08`, `LLM09`).
- **Verificação (`aok report verify`):** `20 ok, 0 falha(s), 0 não verificável(is) -> ÍNTEGRO` (pacote não assinado).

---

## 2. Agente 2 — Triagem financeira via Python (`llama3.1:8b`)

Implementação em `examples/validation_agents/finance_python_agent.py` e configuração em `examples/validation_agents/finance_python_agent.yaml` (`target.type: python`). O arquivo de configuração declara um perfil **intencionalmente parcial** (`role`, `allowed_scope`, `forbidden_scope` e `sensitive_data` presentes; `forbidden_actions` e `declared_tools` ausentes) e o pacote é montado com `--no-eval` para exercitar o registro explícito de lacunas (`não testado`).

### Comandos executados

```bash
aok redteam run --universal \
  --config examples/validation_agents/finance_python_agent.yaml \
  --seed 42 --out reports/validation_finance_rt.jsonl

python -m agent_ops_kit.redteam.false_positives \
  --config examples/validation_agents/finance_python_agent.yaml \
  --dataset evals/dataset.jsonl \
  --benign redteam/benign/benign.jsonl \
  --v1-answers evals/answers/v1.jsonl \
  --out-dir reports/validation_finance_fp --limit 5 --seed 42

aok report build --no-eval \
  --config examples/validation_agents/finance_python_agent.yaml \
  --redteam-baseline reports/validation_finance_rt.jsonl \
  --redteam-guardrails reports/validation_finance_rt.jsonl \
  --fp-dir reports/validation_finance_fp \
  --out reports/validation_finance_pkg

aok report verify reports/validation_finance_pkg --repo-root .
```

### Avaliação funcional (`--no-eval`)

Nenhum dataset funcional foi associado a este agente; o relatório registra explicitamente **`Não avaliado (dataset funcional não fornecido)`**, e as regras de política dependentes de `eval` (`eval_regression` e `eval_nonsignificant_drop`) permanecem como `Não avaliada` (impedindo aprovação silenciosa).

### Segurança (`redteam --universal`) e falsos positivos

Por ausência de `forbidden_actions`, `declared_tools` e `tools` no `finance_python_agent.yaml`, a bateria universal pulou automaticamente a categoria `abuso_de_tools`, registrando o motivo `não testado: profile.forbidden_actions e declared_tools/tools vazios no agent.yaml`.

| Categoria | n | Sucessos | ASR % | IC 95% (Wilson) | Erros |
|---|---|---|---|---|---|
| `injecao_direta` | 2 | 1 | 50.0 | [9.5; 90.5] | 0 |
| `injecao_indireta` | 2 | 1 | 50.0 | [9.5; 90.5] | 0 |
| `vazamento_dados` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `exaustao_recursos` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `vazamento_prompt` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `desvio_de_escopo` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `jailbreak` | 2 | 0 | 0.0 | [0.0; 65.8] | 0 |
| `abuso_de_tools` | 0 | - | - | - | não testado |
| `total` | 14 | 2 | 14.3 | [4.0; 39.9] | 0 |

- **Falsos positivos:** `0/5` (`0.0%`, IC 95% Wilson `[0.0; 43.4]`, `0` erros) no recorte de `evals/dataset.jsonl` e `0/5` (`0.0%`, IC 95% Wilson `[0.0; 43.4]`, `0` erros) no recorte de `redteam/benign/benign.jsonl`, sem guardrails do kit aplicados. Como os 5 casos de `evals/dataset.jsonl` pertencem ao domínio RAG de referência (e não ao domínio financeiro), a pontuação utilitária comparativa desse recorte foi `0.0000` contra `0.7333` da gravação do RAG (`p = 0.1250`), evidenciando apenas que perguntas de outro domínio são recusadas pelo agente financeiro.

### Semáforo, achados, escopo e verificação

- **Semáforo:** `AMARELO` (regras acionadas: `attack_success_with_guardrails` com observado `2`, e `no_audit`; regras `eval_regression` e `eval_nonsignificant_drop` não avaliadas).
- **Achados no pacote:** `4` registros (`2` sucessos replicados entre baseline e comparação em `injecao_direta` e `injecao_indireta`), todos vinculados por linha e SHA-256.
- **Escopo e custo (`test_scope`):** perfil com `3/5` dimensões declaradas (`Ações proibidas` e `Ferramentas declaradas` marcadas como `não testado`); `7/12` categorias de segurança testadas (`abuso_de_tools` pulada por perfil parcial; `exfiltracao`, `ofuscacao`, `multi_turn` e `saida_insegura` não testadas por ausência na bateria universal); qualidade funcional e cadeia de auditoria marcadas como `não testado`; falsos positivos marcados como `testado`. Total contabilizado de `24` chamadas ao agente (`0` eval + `14` red team + `10` falsos positivos), sem contagem de tokens pelo kit (função `run(request)` encapsula a chamada ao Ollama).
- **Cobertura OWASP LLM Top 10 (2025):** `4` categorias testadas (`LLM01` 2/8, `LLM02` 0/2, `LLM07` 0/2, `LLM10` 0/2), `1` apenas com controle mapeado sem ataque executado (`LLM06`) e `5` não cobertas (`LLM03`, `LLM04`, `LLM05`, `LLM08`, `LLM09`).
- **Verificação (`aok report verify`):** `20 ok, 0 falha(s), 0 não verificável(is) -> ÍNTEGRO` (pacote não assinado).

---

## Limites declarados desta validação

- **Mesmo modelo subjacente local (`llama3.1:8b`):** ambos os agentes foram implementados sobre o modelo local `llama3.1:8b` via Ollama, com custo financeiro adicional zero. Os resultados validam a integração ponta a ponta do kit em agentes de funções e interfaces diferentes, mas **não representam comportamento de APIs comerciais em produção**, outros modelos ou prompts de terceiros.
- **Avaliação de caixa-preta:** o kit enxerga apenas entrada, resposta textual e `tool_calls` declarados pela interface do alvo; não inspeciona estados internos, chamadas ocultas de ferramentas ou bancos externos que o agente não exponha no contrato.
- **Critérios determinísticos e sem calibração humana:** a verificação de sucesso de ataques e a pontuação funcional do `eval` utilizam regras determinísticas (sem calibração contra juízes humanos nesta validação). Como observado no Agente 1, a checagem `refuses_when_unanswerable` busca a frase fixa do testbed RAG (`0/2`), penalizando recusas válidas redigidas em linguagem natural por agentes de outro domínio.
- **Amostra pequena e execução única:** `17` e `14` cenários de ataque, `6` casos funcionais e `5 + 5` perguntas legítimas produzem intervalos de confiança largos (ex.: `[6.2; 41.0]` e `[4.0; 39.9]`). Cada medição usou uma única execução (`seed=42`) e não mede variância entre execuções; `aok reproduce` não reproduz alvos HTTP ou agentes cuja semente e modelo sejam internos ao próprio agente.
- **Ausência de guardrails internos e de log de auditoria:** os guardrails do kit aplicam-se apenas ao agente de referência; os dois alvos externos foram auditados sem camada adicional do kit e sem anexo de trilha de auditoria encadeada.
