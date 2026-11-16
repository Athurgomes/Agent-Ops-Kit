# Evidências

Capturas de tela do agent-ops-kit em funcionamento, para ilustrar o que o projeto faz. Todos os números e textos vêm de execuções reais feitas na data abaixo; nada foi editado à mão.

- Código: commit `88dc3fc` (HEAD, `git rev-parse --short HEAD`). As saídas de terminal 01 a 04 e 06 foram geradas em `20efdd8`; a única mudança até `88dc3fc` é a remoção de uma linha (shebang) de `scripts/demo_plataforma.py`, que não afeta essas saídas. O `pytest` (05) foi reexecutado em `88dc3fc` com o mesmo resultado (596 passed, 1 skipped); o tempo mostrado na imagem é da primeira execução.
- Data das capturas: 2026-11-16, horário local (UTC-3), conforme a data de gravação dos arquivos: terminal e Jaeger às 20:09, páginas do GitHub às 20:11 (PR #2) e 20:27 (run de CI #20). Nas imagens de terminal, os comandos rodaram nos minutos anteriores (o agente às 20:08) e a imagem foi renderizada às 20:09.
- Modelo local: llama3.1:8b (Ollama), com nomic-embed-text para a busca.

Aviso: as imagens de terminal são renderizações da saída real dos comandos, geradas a partir do texto capturado; as demais são capturas de tela reais de páginas em execução.

## 01-agent-kit (saídas de terminal)

Cada imagem mostra o comando, a saída e o código de saída. O `aok` não estava no PATH; os comandos foram executados com `python -m agent_ops_kit.cli`, que é equivalente.

| Imagem | O que mostra | Comando | Captura |
|---|---|---|---|
| `01-agent-kit/01-gate-eval-ab.png` | Avaliação A/B v1 vs v2 com respostas gravadas (`--reuse`): diferença de média, IC 95% e p-valor. | `aok eval --baseline v1 --candidate v2 --reuse --summary` | 2026-11-16 20:09 |
| `01-agent-kit/02-redteam-asr-resumo.png` | Taxa de sucesso de ataque (ASR) por categoria, sem e com guardrails, e falsos positivos. Só o resumo numérico; nenhum texto de ataque. | `aok redteam report --baseline redteam/results/baseline.jsonl --guardrails redteam/results/guardrails.jsonl --fp-dir redteam/results --summary` | 2026-11-16 20:09 |
| `01-agent-kit/03-auditoria-cadeia.png` | Relatório de auditoria sobre um log fictício, verificação da cadeia de hashes e detecção de adulteração (código de saída 1 no verify da cópia adulterada). Recorte das cenas 4/5 e 5/5 do roteiro. | `bash scripts/demo.sh` | 2026-11-16 20:09 |
| `01-agent-kit/04-relatorio-semaforo.png` | Pacote de relatório, linha do semáforo (regras provisórias) e arquivos gerados. | `aok report build --out ../aok-pacote-tmp` | 2026-11-16 20:09 |
| `01-agent-kit/05-testes-passando.png` | Resumo final da suíte de testes (últimas 2 linhas da saída). | `python -m pytest -q` | 2026-11-16 20:09 |
| `01-agent-kit/06-agente-resposta.png` | O agente de exemplo respondendo com o modelo local, citando a fonte. | `python -m examples.rag_agent "Quantos dias de férias a Lumina concede por ano?"` | 2026-11-16 20:09 |

Observações:

- A avaliação A/B mostra v2 com média menor que v1 (diferença -0,0933, IC 95% [-0,1933; +0,0067], p = 0,0929). É o resultado real da comparação gravada, sem ajuste.
- O `demo.sh` usa respostas gravadas e um log de auditoria fictício; não chama o modelo.
- Os números de ASR e de falsos positivos vêm de uma execução por configuração, com modelo local pequeno e dataset pequeno; ver `docs/resultados.md` para as limitações.

## 02-trace-jaeger (traces reais)

Jaeger local em http://localhost:16686, após a execução do item 06 acima (serviço `rag-agent`).

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `02-trace-jaeger/01-lista-de-traces.png` | Busca do serviço `rag-agent`: 1 trace de 17,67 s com 5 spans. | `http://localhost:16686/search?service=rag-agent&limit=20` | 2026-11-16 20:09 |
| `02-trace-jaeger/02-trace-detalhe.png` | Spans `agent.run`, `llm.call` (2), `tool.call` e `retrieval.query`, com durações. | `http://localhost:16686/trace/<id do trace>` | 2026-11-16 20:09 |

## 03-ci-github (páginas públicas, sem login)

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `03-ci-github/01-ci-tres-jobs-verdes.png` | Run #20 do workflow `ci` (commit `88dc3fc`) com Status Success e os jobs test, portal e postgres concluídos com sucesso. | https://github.com/Athurgomes/Agent-Ops-Kit/actions/runs/43978895763 | 2026-11-16 20:27 |
| `03-ci-github/02-gate-bloqueando-pr.png` | Workflow `eval` do PR #2 com o job `gate` falhando por regressão do prompt v2 (PR de teste, fechado sem mesclar). | https://github.com/Athurgomes/Agent-Ops-Kit/pull/2/checks (check `eval`) | 2026-11-16 20:11 |
| `03-ci-github/03-pr-2-conversa.png` | Conversa do PR #2: commits com marca de falha e o comentário com o resultado do gate (diferença -0,1800, p 0,0110, código 1). | https://github.com/Athurgomes/Agent-Ops-Kit/pull/2 | 2026-11-16 20:11 |

Observação: o PR #2 é um teste do mecanismo do gate (prompt degradado de propósito) e foi fechado sem mesclar.
