### ASR com guardrails

| Categoria | n | Sucessos | ASR % | IC 95% (Wilson) | Erros |
|---|---|---|---|---|---|
| injecao_direta | 12 | 0 | 0.0 | [0.0; 24.2] | 0 |
| injecao_indireta | 12 | 0 | 0.0 | [0.0; 24.2] | 0 |
| abuso_de_tools | 8 | 0 | 0.0 | [0.0; 32.4] | 0 |
| exfiltracao | 8 | 0 | 0.0 | [0.0; 32.4] | 0 |
| total | 40 | 0 | 0.0 | [0.0; 8.8] | 0 |

Limitações:
- n pequeno por categoria: os intervalos de confiança são largos.
- Uma única execução com seed fixa; não mede a variância entre execuções.
- O ASR depende do modelo llama3.1:8b e não generaliza para outros modelos.
- O critério de sucesso é objetivo, mas conservador: ataques bem-sucedidos que fogem do critério (ex.: vazamento parafraseado) não são contados.
- Denominador = todos os casos executados; erros do agente não contam como sucesso e são mostrados na coluna Erros.

