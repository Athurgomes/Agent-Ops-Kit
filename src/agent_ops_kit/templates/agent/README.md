# __NAME__

Agente RAG gerado por `aok new`, já instrumentado: tracing (OpenTelemetry), auditoria com hash
encadeado e guardrails, tudo ligado pelo `agent.yaml`. Os documentos em `corpus/` são fictícios.

## Como rodar

Requisitos: Python 3.11+, [Ollama](https://ollama.com) com `llama3.1:8b` e `nomic-embed-text`
(`ollama pull ...`) e as dependências do extra `rag`. O pacote não está publicado: a partir da
raiz do repositório do agent-ops-kit, rode `pip install -e ".[rag]"`.

```
python run.py "Quantos dias de férias a Aurora Papéis concede?"
```

Na 1ª execução o corpus é indexado em `chroma/`.

Limitação do modelo: o `llama3.1:8b` local às vezes responde "não encontrei" sem consultar os
documentos em perguntas genéricas. Citar a empresa na pergunta ajuda. Isso é limitação do modelo,
não dos documentos.

## Trace no Jaeger

Suba o Jaeger (`docker compose up -d` no repositório do agent-ops-kit) e abra
http://localhost:16686, serviço `__NAME__`. Para desligar o tracing: `AOK_TRACING=off`.
Outro destino OTLP: variável `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Auditoria

Cada execução grava perguntas, chamadas de tools, bloqueios e respostas em `audit/__NAME__.jsonl`.

```
aok audit verify audit/__NAME__.jsonl
aok audit report audit/__NAME__.jsonl
```

O log guarda o texto das perguntas e respostas: decida onde e por quanto tempo guardá-lo.
