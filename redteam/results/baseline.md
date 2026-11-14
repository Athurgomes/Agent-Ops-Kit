### ASR sem guardrails

| Categoria | n | Sucessos | ASR % | IC 95% (Wilson) | Erros |
|---|---|---|---|---|---|
| injecao_direta | 12 | 1 | 8.3 | [1.5; 35.4] | 0 |
| injecao_indireta | 12 | 1 | 8.3 | [1.5; 35.4] | 0 |
| abuso_de_tools | 8 | 6 | 75.0 | [40.9; 92.9] | 0 |
| exfiltracao | 8 | 1 | 12.5 | [2.2; 47.1] | 0 |
| total | 40 | 9 | 22.5 | [12.3; 37.5] | 0 |

Limitações:
- n pequeno por categoria: os intervalos de confiança são largos.
- Uma única execução com seed fixa; não mede a variância entre execuções.
- O ASR depende do modelo llama3.1:8b e não generaliza para outros modelos.
- O critério de sucesso é objetivo, mas conservador: ataques bem-sucedidos que fogem do critério (ex.: vazamento parafraseado) não são contados.
- Denominador = todos os casos executados; erros do agente não contam como sucesso e são mostrados na coluna Erros.

