# Relatório de avaliação A/B

- Comando: `aok eval --baseline v1 --candidate v2 --dataset evals/dataset_audit_200.jsonl --prompts-dir evals/prompts --config examples/rag_agent/agent.yaml --answers-dir evals/answers_audit_200_runs3 --runs 3 --seed 42 --report evals/results/audit_200_v1_vs_v2_runs3.md`
- Modelo: llama3.1:8b
- Semente: 42
- Casos: 200
- Execuções por configuração: 3
- Respostas: geradas nesta execução
- Data: 2026-11-21T16:59:45-03:00

## Métrica determinística

### Comparação A/B: v2 vs v1 (checagens determinísticas)

| Item | Valor |
|---|---|
| Média v1 | 0.7544 |
| Média v2 | 0.6206 |
| Diferença média (v2 - v1) | -0.1339 |
| IC 95% da diferença (bootstrap) | [-0.1911, -0.0756] |
| p-valor (permutação pareada, bilateral, monte_carlo) | 0.0002 |
| n (pares usados) | 200 |
| Descartados | 0 |
| Semente / reamostragens | 42 / 10000 |

Diferença estatisticamente distinguível de zero a 5%.

Aviso: p-valor não é prova de causalidade, e n pequeno limita o poder do teste.

## Variância entre execuções

| Variante | Execuções | Média | Desvio-padrão (execuções) | Desvio médio por caso | Consistência exata (score / resposta) |
|---|---|---|---|---|---|
| v1 | 3 | 0.7544 | 0.0025 | 0.0067 | 98.0% / 97.0% |
| v2 | 3 | 0.6206 | 0.0010 | 0.0010 | 99.5% / 99.5% |

- Médias por execução (v1): [0.7567, 0.7517, 0.7550]
- Médias por execução (v2): [0.6217, 0.6200, 0.6200]

## Taxa de aprovação por checagem

Aprovados/aplicáveis (a checagem não se aplica a todos os casos).

| Checagem | v1 | v2 |
|---|---|---|
| contains_expected | 292/495 (59.0%) | 177/495 (35.8%) |
| cites_correct_source | 476/600 (79.3%) | 265/600 (44.2%) |
| valid_format | 503/600 (83.8%) | 594/600 (99.0%) |
| refuses_when_unanswerable | 87/105 (82.9%) | 81/105 (77.1%) |

## Métricas operacionais

| Métrica | v1 | v2 |
|---|---|---|
| Casos | 600 | 600 |
| Latência por caso, p50 (s) | 5.31 | 8.23 |
| Latência por caso, p95 (s) | 7.95 | 11.88 |
| Tokens de entrada, média por caso | 1154.70 | 1394.12 |
| Tokens de saída, média por caso | 75.17 | 127.03 |
| Taxa de erro do agente | 0.0000 | 0.0000 |
| Taxa de erro de tool | n/d (o runner não registra tools por caso) | n/d (o runner não registra tools por caso) |
| Custo estimado | 0.0000 | 0.0000 |

- Valores por caso (soma das chamadas de LLM do caso), não por chamada.
- A latência depende do hardware e da carga do modelo (a 1ª execução inclui a carga a frio). Com `--reuse`, a latência vem das respostas gravadas (não é medida no CI).
- Custo (llama3.1:8b): Custo estimado e configurável: preço por 1 milhão de tokens (entrada e saída) por modelo. O padrão traz só modelos locais do Ollama, a 0.0. Local = 0.0.

## Erros

| Variante | Erros do agente | Erros do juiz |
|---|---|---|
| v1 | 0 | n/a |
| v2 | 0 | n/a |
