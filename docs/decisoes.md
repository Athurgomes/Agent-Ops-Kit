# Decisões de projeto (ADRs curtas)

## ADR-001: como o CI roda sem modelo grande

**Contexto.** O runner gratuito do GitHub Actions não roda `llama3.1:8b` (memória e tempo) nem tool calling estável em modelos minúsculos (por exemplo `qwen2.5:0.5b`). Um gate com modelo pequeno mediria outro modelo, com outro comportamento, e seria instável.

**Decisão.** O CI não chama modelo. As respostas são geradas localmente com `aok eval` (Ollama, `temperature 0`, semente fixa) e versionadas em `evals/answers/<variante>.jsonl`. O job roda:

```
aok eval --baseline v1 --candidate v2 --reuse --fail-on-regression --report eval-report.md
```

Para o gate não ser burlável por respostas velhas, `aok eval` (sem `--reuse`) grava `evals/answers/manifest.json` com, por variante: sha256 do texto do prompt, sha256 do dataset, modelo, semente, número de casos e data. Com `--reuse`, o manifesto é verificado contra os arquivos atuais. Se o prompt, o dataset ou o modelo (`agent.yaml`) divergirem, ou o manifesto não existir, o comando sai com código 2 e a mensagem "respostas gravadas desatualizadas: regrave com aok eval". `--no-verify` pula a verificação e o relatório avisa isso. O gate usa só a métrica determinística: falha (código 1) se a diferença média (candidata menos baseline) for menor que 0 e o p-valor for menor que 0.05. O juiz fica fora do CI.

O manifesto das respostas v1 e v2 já commitadas foi criado a posteriori, depois de conferir no `git log` e nas datas dos arquivos que prompts e dataset não mudaram depois da gravação. O campo `nota` de cada entrada diz isso; ele não foi escrito pelo runner. Novas gravações feitas pelo `aok eval` são escritas pelo runner.

Alternativa descartada: modelo minúsculo no runner. Custo zero, mas mede outro modelo e o tool calling nele é instável.

**Consequências e limitações.**
- O CI verifica consistência e regressão sobre respostas gravadas localmente. Ele não reexecuta o modelo: não detecta mudança de comportamento do modelo, do Ollama ou do código do agente que não altere prompt, dataset ou modelo.
- O manifesto cobre prompt, dataset e modelo. Não cobre o corpus (`examples/rag_agent/corpus`), as ferramentas nem o `src/`; mudar isso exige regravar por disciplina do autor, não por trava.
- Quem edita o JSONL à mão não é barrado: o manifesto detecta respostas velhas, não adulteradas. A proteção contra isso é a revisão do PR (o diff do JSONL aparece nele).
- O gate só falha com piora estatisticamente distinguível (p < 0.05). Com 50 casos o poder é limitado: no relatório `evals/results/v1_vs_v2.md`, a diferença média na métrica determinística foi -0.0933 (v2 menos v1), IC 95% [-0.1933, +0.0067] e p-valor 0.0929, ou seja, o gate não falharia para v2 vs v1.
- Não validado em PR real no GitHub ainda; o workflow foi checado com `actionlint` e o mesmo comando foi rodado localmente.

## ADR-002: teste de permutação pareado e bootstrap com semente fixa

**Contexto.** Os dois prompts são avaliados nos mesmos casos, e as notas não são normais (checagens em 0, 0.25, ..., 1; notas do juiz de 1 a 5). Com n de dezenas, testes paramétricos assumem mais do que os dados sustentam.

**Decisão.** `paired_ab` (`src/agent_ops_kit/eval/ab.py`) compara as variantes por caso:
- p-valor: teste de permutação pareado por inversão de sinal das diferenças, bilateral (exato para n pequeno, Monte Carlo acima disso; o relatório indica o método).
- IC 95% da diferença média: bootstrap pareado por percentis, 10000 reamostragens.
- Semente fixa (padrão 42) e registrada no relatório, para reproduzir os mesmos números com o mesmo comando.
- Casos sem nota em algum dos lados são descartados e contados no relatório.

**Consequências.** Poucas suposições e resultado reproduzível. O p-valor não prova causalidade, e n pequeno limita o poder; o relatório traz esse aviso. Sem correção para múltiplas comparações: o gate usa uma única métrica.

## ADR-003: juiz é o mesmo modelo de 8B

**Contexto.** Respostas abertas não são bem cobertas por checagens determinísticas. O projeto é local e sem custo, então o juiz também roda no Ollama.

**Decisão.** O juiz usa o mesmo `llama3.1:8b` que gera as respostas, com rubrica explícita (fidelidade, relevância e completude, notas de 1 a 5) e saída em JSON. Entra no relatório só com `--judge`, sempre acompanhado de aviso, e fica fora do CI.

**Consequências e limitações.**
- Viés de autopreferência: o modelo tende a favorecer respostas parecidas com as que ele mesmo produz.
- Ruído e notas ordinais: a diferença média de notas 1 a 5 é uma aproximação, não uma medida intervalar.
- A rubrica não foi calibrada contra avaliação humana.
- Uso: complemento das checagens determinísticas, nunca substituto nem critério de gate. Se juiz e checagens divergirem, vale investigar os casos, não escolher o resultado mais favorável. No relatório `evals/results/v1_vs_v2.md`, por exemplo, o juiz deu diferença de -0.7667 (p-valor 0.0154) e as checagens -0.0933 (p-valor 0.0929): ambos apontam v2 pior, mas só o juiz passa de 5%, e é o instrumento menos confiável dos dois.
