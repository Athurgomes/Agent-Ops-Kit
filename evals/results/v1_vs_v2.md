# Relatório de avaliação A/B

- Comando: `aok eval --baseline v1 --candidate v2 --dataset evals/dataset.jsonl --prompts-dir evals/prompts --config examples/rag_agent/agent.yaml --answers-dir evals/answers --judge --seed 42 --report evals/results/v1_vs_v2.md`
- Modelo: llama3.1:8b
- Semente: 42
- Casos: 50
- Respostas: geradas nesta execução
- Data: 2026-11-12T18:55:25-03:00

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

## Taxa de aprovação por checagem

Aprovados/aplicáveis (a checagem não se aplica a todos os casos).

| Checagem | v1 | v2 |
|---|---|---|
| contains_expected | 21/40 (52.5%) | 17/40 (42.5%) |
| cites_correct_source | 35/50 (70.0%) | 22/50 (44.0%) |
| valid_format | 43/50 (86.0%) | 48/50 (96.0%) |
| refuses_when_unanswerable | 7/10 (70.0%) | 5/10 (50.0%) |

## Juiz (LLM-as-judge)

Aviso sobre o juiz: o juiz é o mesmo modelo de 8B que gera as respostas (viés de autopreferência e ruído); as notas são ordinais (1 a 5), não intervalares; a rubrica não foi calibrada contra humanos. Use como complemento das checagens determinísticas, não como substituto.

### Comparação A/B: v2 vs v1 (nota do juiz, 1 a 5)

| Item | Valor |
|---|---|
| Média v1 | 4.1933 |
| Média v2 | 3.4267 |
| Diferença média (v2 - v1) | -0.7667 |
| IC 95% da diferença (bootstrap) | [-1.3600, -0.1800] |
| p-valor (permutação pareada, bilateral, monte_carlo) | 0.0154 |
| n (pares usados) | 50 |
| Descartados | 0 |
| Semente / reamostragens | 42 / 10000 |

Diferença estatisticamente distinguível de zero a 5%.

Aviso: p-valor não é prova de causalidade, e n pequeno limita o poder do teste.

## Erros

| Variante | Erros do agente | Erros do juiz |
|---|---|---|
| v1 | 0 | 0 |
| v2 | 0 | 0 |
