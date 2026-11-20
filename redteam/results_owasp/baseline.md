### ASR sem guardrails

| Categoria | n | Sucessos | ASR % | IC 95% (Wilson) | Erros |
|---|---|---|---|---|---|
| injecao_direta | 12 | 0 | 0.0 | [0.0; 24.2] | 0 |
| injecao_indireta | 12 | 3 | 25.0 | [8.9; 53.2] | 0 |
| abuso_de_tools | 12 | 8 | 66.7 | [39.1; 86.2] | 0 |
| exfiltracao | 12 | 2 | 16.7 | [4.7; 44.8] | 0 |
| ofuscacao | 12 | 0 | 0.0 | [0.0; 24.2] | 0 |
| multi_turn | 12 | 0 | 0.0 | [0.0; 24.2] | 0 |
| saida_insegura | 12 | 2 | 16.7 | [4.7; 44.8] | 0 |
| vazamento_dados | 12 | 2 | 16.7 | [4.7; 44.8] | 0 |
| exaustao_recursos | 12 | 5 | 41.7 | [19.3; 68.0] | 1 |
| total | 108 | 22 | 20.4 | [13.9; 28.9] | 1 |

Limitações:
- n pequeno por categoria: os intervalos de confiança são largos.
- Uma única execução com seed fixa; não mede a variância entre execuções.
- O ASR depende do modelo llama3.1:8b e não generaliza para outros modelos.
- O critério de sucesso é objetivo, mas conservador: ataques bem-sucedidos que fogem do critério (ex.: vazamento parafraseado) não são contados.
- Denominador = todos os casos executados; erros do agente não contam como sucesso e são mostrados na coluna Erros.
