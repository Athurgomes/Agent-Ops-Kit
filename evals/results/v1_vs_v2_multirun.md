# Relatório de avaliação A/B

- Comando: `aok eval --baseline v1 --candidate v2 --dataset evals/dataset.jsonl --prompts-dir evals/prompts --config examples/rag_agent/agent.yaml --answers-dir evals/answers_multirun --runs 3 --seed 42 --report evals/results/v1_vs_v2_multirun.md`
- Modelo: llama3.1:8b
- Semente: 42
- Casos: 50
- Execuções por configuração: 3
- Respostas: geradas nesta execução
- Data: 2026-11-19T16:54:46-03:00

## Métrica determinística

### Comparação A/B: v2 vs v1 (checagens determinísticas)

| Item | Valor |
|---|---|
| Média v1 | 0.7067 |
| Média v2 | 0.6133 |
| Diferença média (v2 - v1) | -0.0933 |
| IC 95% da diferença (bootstrap) | [-0.1933, +0.0067] |
| p-valor (permutação pareada, bilateral, monte_carlo) | 0.0929 |
| n (pares usados) | 50 |
| Descartados | 0 |
| Semente / reamostragens | 42 / 10000 |

Aviso: p-valor não é prova de causalidade, e n pequeno limita o poder do teste.

## Variância entre execuções

| Variante | Execuções | Média | Desvio-padrão (execuções) | Desvio médio por caso | Consistência exata (score / resposta) |
|---|---|---|---|---|---|
| v1 | 3 | 0.7067 | 0.0000 | 0.0000 | 100.0% / 98.0% |
| v2 | 3 | 0.6133 | 0.0000 | 0.0000 | 100.0% / 100.0% |

- Médias por execução (v1): [0.7067, 0.7067, 0.7067]
- Médias por execução (v2): [0.6133, 0.6133, 0.6133]

## Taxa de aprovação por checagem

Aprovados/aplicáveis (a checagem não se aplica a todos os casos).

| Checagem | v1 | v2 |
|---|---|---|
| contains_expected | 63/120 (52.5%) | 51/120 (42.5%) |
| cites_correct_source | 105/150 (70.0%) | 66/150 (44.0%) |
| valid_format | 129/150 (86.0%) | 144/150 (96.0%) |
| refuses_when_unanswerable | 21/30 (70.0%) | 15/30 (50.0%) |

## Métricas operacionais

| Métrica | v1 | v2 |
|---|---|---|
| Casos | 150 | 150 |
| Latência por caso, p50 (s) | 5.39 | 7.89 |
| Latência por caso, p95 (s) | 8.10 | 11.38 |
| Tokens de entrada, média por caso | 1095.76 | 1362.54 |
| Tokens de saída, média por caso | 69.83 | 116.44 |
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
