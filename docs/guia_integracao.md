# Guia de integração para desenvolvedores

Este guia mostra, em cerca de 15 minutos, como conectar uma API HTTP externa ao `agent-ops-kit`, rodar a bateria universal de red team parametrizada pelo perfil do agente, gerar o pacote de relatório (com ou sem dataset funcional) e conferir a integridade offline.

O passo a passo usa uma API local de exemplo em [examples/external_http_agent/server.py](../examples/external_http_agent/server.py) (um serviço determinístico de triagem de suporte de pedidos, sem RAG e sem dependência do Ollama) e mostra como adaptar o arquivo de configuração para o seu ambiente de **staging HTTPS** e para o GitHub Actions.

---

## Pré-requisitos

- Python 3.11+ com o kit instalado (`pip install -e ".[dev]"`).
- Se `aok` não estiver no `PATH`, substitua `aok` por `python -m agent_ops_kit.cli` em todos os comandos abaixo.
- `AOK_TRACING=off` desliga o envio de spans OpenTelemetry durante testes rápidos sem Jaeger.

---

## 1. Subir a API HTTP de exemplo

A API de exemplo escuta em `127.0.0.1:8787`, exige `Authorization: Bearer <token>` lido da variável de ambiente `EXTERNAL_AGENT_TOKEN` (nunca gravado em arquivo), recebe `{"mensagem": ..., "contexto": ...}` em `POST /chat` e responde `{"data": {"reply": ..., "actions": [...]}}`.

Em um terminal separado, defina um token de teste apenas no ambiente e inicie o servidor:

**Linux / macOS (bash):**

```bash
export EXTERNAL_AGENT_TOKEN="seu-token-local-de-teste"
python examples/external_http_agent/server.py --port 8787
```

**Windows (PowerShell):**

```powershell
$env:EXTERNAL_AGENT_TOKEN = "seu-token-local-de-teste"
python examples/external_http_agent/server.py --port 8787
```

A configuração pronta para essa API está em [examples/external_http_agent/agent.yaml](../examples/external_http_agent/agent.yaml), demonstrando o mapeamento configurável (`request_template`, `answer_path`, `tool_calls_path`), `auth_env`, `max_calls` e o bloco `profile`.

---

## 2. Rodar a bateria universal de red team

Em outro terminal na raiz do repositório, exporte a mesma variável `EXTERNAL_AGENT_TOKEN` e execute:

**Linux / macOS (bash):**

```bash
export EXTERNAL_AGENT_TOKEN="seu-token-local-de-teste"
export AOK_TRACING=off

aok redteam run --universal \
  --config examples/external_http_agent/agent.yaml \
  --out reports/ext_rt.jsonl
```

**Windows (PowerShell):**

```powershell
$env:EXTERNAL_AGENT_TOKEN = "seu-token-local-de-teste"
$env:AOK_TRACING = "off"

aok redteam run --universal `
  --config examples/external_http_agent/agent.yaml `
  --out reports/ext_rt.jsonl
```

Em seguida, colete uma amostra curta de falsos positivos (usada na composição do pacote de relatório; para agentes externos, os guardrails do kit não são aplicados):

```bash
python -m agent_ops_kit.redteam.false_positives \
  --config examples/external_http_agent/agent.yaml \
  --out-dir reports/ext_fp \
  --limit 3
```

*Saída verificada contra a API de exemplo:* 18 casos executados em 8 categorias da bateria universal, 0 erros, respeitando `max_calls=50`, e 6 chamadas adicionais na coleta de falsos positivos (`--limit 3`).

---

## 3. Gerar o pacote de relatório

O `aok report build` exige os três argumentos de red team juntos (`--redteam-baseline`, `--redteam-guardrails` e `--fp-dir`). Como os guardrails do kit não se aplicam a agentes externos, informe o mesmo arquivo JSONL em `--redteam-baseline` e `--redteam-guardrails` (o relatório registra explicitamente que as duas colunas medem a mesma configuração).

### Caminho A: sem dataset funcional (`--no-eval`)

Use este fluxo quando você ainda não tem um dataset funcional próprio. O relatório é gerado normalmente para segurança, perfil, escopo testado e custo, registrando a qualidade funcional como **não avaliada**:

```bash
aok report build \
  --no-eval \
  --config examples/external_http_agent/agent.yaml \
  --redteam-baseline reports/ext_rt.jsonl \
  --redteam-guardrails reports/ext_rt.jsonl \
  --fp-dir reports/ext_fp \
  --out reports/ext_pacote
```

### Caminho B (opcional): com dataset funcional próprio

Se você tiver casos funcionais no formato documentado em [docs/dataset_funcional.md](dataset_funcional.md) (como o exemplo em [examples/external_http_agent/dataset.jsonl](../examples/external_http_agent/dataset.jsonl), com `sources: []`), execute o `aok eval` antes de montar o pacote:

```bash
aok eval \
  --baseline v1 \
  --candidate v2 \
  --config examples/external_http_agent/agent.yaml \
  --dataset examples/external_http_agent/dataset.jsonl \
  --answers-dir reports/ext_eval \
  --report reports/ext_eval_report.md \
  --summary

aok report build \
  --config examples/external_http_agent/agent.yaml \
  --dataset examples/external_http_agent/dataset.jsonl \
  --answers-dir reports/ext_eval \
  --redteam-baseline reports/ext_rt.jsonl \
  --redteam-guardrails reports/ext_rt.jsonl \
  --fp-dir reports/ext_fp \
  --out reports/ext_pacote_eval
```

*(Observação: para agentes externos, o prompt interno pertence ao próprio serviço; a comparação v1 vs v2 no `aok eval` registra apenas variação entre execuções consecutivas.)*

---

## 4. Conferir o pacote offline

Valide hashes, recálculos estatísticos, cobertura, perfil, escopo testado e renderização de `relatorio.md` / `relatorio.html` sem rede e sem chamar o agente novamente:

```bash
aok report verify reports/ext_pacote --repo-root .
```

Se você seguiu o caminho opcional com dataset funcional:

```bash
aok report verify reports/ext_pacote_eval --repo-root .
```

Em ambos os fluxos executados contra a API de exemplo, o resultado verificado foi `20 ok, 0 falha(s), 0 não verificável(is) -> ÍNTEGRO` (semáforo `AMARELO`, pois não há log de auditoria anexado nem assinatura, e a política padrão evita aprovação silenciosa).

Ao concluir o teste local, encerre o servidor de exemplo (`Ctrl+C`) e remova os arquivos temporários em `reports/` se não quiser mantê-los.

---

## 5. Adaptar `agent.yaml` para uma API de staging HTTPS real

Ao sair do teste local e apontar o kit para o serviço da sua equipe, ajuste o `agent.yaml` seguindo estas regras:

1. **Remova `allow_insecure_localhost`** e use `https://` em `target.url`. Por segurança, o cliente HTTP recusa `http://` fora de loopback, recusa credenciais/query/fragmento na URL, desabilita proxies de ambiente, bloqueia redirects `3xx` e bloqueia endereços de metadados de nuvem e link-local (anti-SSRF).
2. **Configure `auth_env` apenas com o nome da variável de ambiente** (ex.: `AGENT_API_TOKEN`), nunca com o valor do segredo. Se sua API usar outro cabeçalho ou prefixo, configure `auth_header` (padrão `Authorization`) e `auth_prefix` (padrão `"Bearer "`, ou `""` para chaves sem prefixo). Cabeçalhos sensíveis em `target.headers` são recusados pela validação.
3. **Mapeie o contrato JSON** da sua API:
   - `request_template`: objeto JSON com os placeholders `{{question}}`, `{{context}}` e `{{tools}}`.
   - `answer_path`: caminho pontilhado até o texto da resposta (aceita índices de lista, ex.: `choices.0.message.content` ou `data.reply`).
   - `tool_calls_path` e `trace_id_path` (opcionais): caminhos pontilhados para chamadas de ferramenta declaradas e identificador de trace; use `null` se sua API não retornar esses campos.
4. **Defina limites operacionais**: `max_calls` (teto de chamadas por execução para controlar custo), `timeout_s` (padrão `30.0`, máximo `300.0`) e `max_response_bytes` (padrão `1048576`).
5. **Preencha o bloco `profile`**: `role`, `allowed_scope`, `forbidden_scope`, `sensitive_data`, `forbidden_actions` e `declared_tools`. A bateria universal usa esses campos para parametrizar os testes; dimensões omitidas ficam declaradas como não testadas no relatório.

Exemplo de `agent.yaml` para staging HTTPS:

```yaml
name: meu-agente-staging
model: nome-do-modelo-em-staging
prompt_version: v1
system_prompt: "Gerido pelo serviço HTTP em staging."

target:
  type: http
  url: "https://staging.sua-empresa.exemplo/v1/chat"
  auth_env: "AGENT_API_TOKEN"
  auth_header: "Authorization"
  auth_prefix: "Bearer "
  request_template:
    messages:
      - role: "user"
        content: "{{question}}"
    metadata:
      context: "{{context}}"
  answer_path: "choices.0.message.content"
  tool_calls_path: "choices.0.message.tool_calls"
  trace_id_path: "id"
  timeout_s: 30
  max_calls: 50

profile:
  role: "Descrição objetiva da função do agente"
  allowed_scope:
    - "tarefa permitida 1"
  forbidden_scope:
    - "assunto ou ação fora de escopo 1"
  sensitive_data:
    - "categoria de dado sensível que o agente não deve expor"
  forbidden_actions:
    - "ação de alto impacto proibida"
  declared_tools:
    - "ferramenta_declarada_1"
```

---

## 6. Automatizar no GitHub Actions

O repositório inclui um template pronto em [docs/templates/client-audit.yml](templates/client-audit.yml).

Para usar no repositório do seu agente:

1. Copie `docs/templates/client-audit.yml` para `.github/workflows/agent-audit.yml`.
2. Cadastre o secret `AGENT_API_TOKEN` em **Settings > Secrets and variables > Actions** (com o mesmo nome definido em `target.auth_env` no seu `agent.yaml`).
3. Ajuste `AGENT_CONFIG` (e opcionalmente `FUNCTIONAL_DATASET`) no topo do workflow.
4. Opcionalmente, cadastre a variável `AOK_PLATFORM_URL` e o secret `AOK_PLATFORM_TOKEN` para publicar o pacote na plataforma via `aok check --publish`.
5. O workflow executa a bateria universal, coleta a amostra de falsos positivos, gera o pacote, roda `aok report verify` e sobe `reports/pacote` como artifact.

Não exponha secrets em workflows disparados por `pull_request` de forks externos.

---

## 7. Limites de caixa-preta

Ao auditar uma API HTTP externa, o kit opera estritamente como **caixa-preta**. Leve estas limitações em conta ao interpretar o relatório:

- **Apenas entrada e saída:** o kit não tem acesso ao prompt interno, ao código nem ao ambiente de execução do agente; não há inserção de canary no prompt do cliente. A detecção depende da resposta textual e dos `tool_calls` declarados no JSON retornado.
- **Somente staging sem efeitos reais:** o red team envia entradas adversariais. Nunca aponte `target.url` para produção nem para endpoints que enviem e-mails, movam recursos financeiros ou alterem dados reais.
- **Custo das chamadas:** cada caso de teste faz chamadas HTTP reais ao endpoint configurado e consome tokens/cota da infraestrutura do cliente. Use `max_calls` no `agent.yaml` para impor um teto por execução.
- **Não-determinismo externo:** o modelo, a temperatura e a semente pertencem ao serviço externo; execuções repetidas podem produzir respostas e taxas diferentes.
- **Guardrails do kit não se aplicam:** o kit mede o agente como ele está exposto na API; `--guardrails` só existe para o agente local de exemplo.
- **Sem cobertura universal comprovada:** o fluxo HTTP e a bateria universal ainda não foram validados em agentes externos reais variados; o relatório descreve apenas o que foi testado naquela execução e **não constitui atestado ou certificação de segurança**.
