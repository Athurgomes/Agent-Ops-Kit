# Relatório de avaliação A/B

- Comando: `aok eval --baseline v1 --candidate v2 --dataset evals/dataset_audit_200.jsonl --prompts-dir evals/prompts --config examples/rag_agent/agent.yaml --answers-dir evals/answers_audit_200 --seed 42 --report evals/results/audit_200_v1_vs_v2.md`
- Modelo: llama3.1:8b
- Semente: 42
- Casos: 200
- Respostas: geradas nesta execução
- Data: 2026-11-19T17:43:40-03:00

## Métrica determinística

### Comparação A/B: v2 vs v1 (checagens determinísticas)

| Item | Valor |
|---|---|
| Média v1 | 0.7750 |
| Média v2 | 0.6217 |
| Diferença média (v2 - v1) | -0.1533 |
| IC 95% da diferença (bootstrap) | [-0.2100, -0.0950] |
| p-valor (permutação pareada, bilateral, monte_carlo) | 0.0001 |
| n (pares usados) | 200 |
| Descartados | 0 |
| Semente / reamostragens | 42 / 10000 |

Diferença estatisticamente distinguível de zero a 5%.

Aviso: p-valor não é prova de causalidade, e n pequeno limita o poder do teste.

## Taxa de aprovação por checagem

Aprovados/aplicáveis (a checagem não se aplica a todos os casos).

| Checagem | v1 | v2 |
|---|---|---|
| contains_expected | 97/165 (58.8%) | 59/165 (35.8%) |
| cites_correct_source | 165/200 (82.5%) | 89/200 (44.5%) |
| valid_format | 173/200 (86.5%) | 198/200 (99.0%) |
| refuses_when_unanswerable | 30/35 (85.7%) | 27/35 (77.1%) |

## Métricas operacionais

| Métrica | v1 | v2 |
|---|---|---|
| Casos | 200 | 200 |
| Latência por caso, p50 (s) | 4.93 | 8.07 |
| Latência por caso, p95 (s) | 8.04 | 11.70 |
| Tokens de entrada, média por caso | 1169.27 | 1396.85 |
| Tokens de saída, média por caso | 76.72 | 127.03 |
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
