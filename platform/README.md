# Plataforma agent-ops-kit (fase 2: API)

API FastAPI que recebe o pacote de relatório publicado por `aok check --publish URL`.
Só publica: não há rota de leitura nesta fase (o portal vem na fase 3).

## Subir

```bash
cp platform/env.example platform/.env      # preencha os dois valores; o .env não é commitado
docker compose -f platform/docker-compose.yml --env-file platform/.env up --build
```

A API fica em `http://127.0.0.1:8000` (docs interativas em `/docs`). Os arquivos dos
relatórios ficam no volume `aok_data` (`AOK_DATA_DIR`, padrão `./aok_data` fora do Docker).
Sem Docker: `pip install -e ".[platform]"` e `uvicorn aok_platform.app:create_app --factory`
(usa SQLite local se `AOK_DATABASE_URL` não estiver definida).

## Fluxo

1. Admin (chave `AOK_ADMIN_BOOTSTRAP_KEY` como `Authorization: Bearer ...`) cria área e agente:
   `POST /v1/admin/areas`, `POST /v1/admin/agents`.
2. Emite o token do agente: `POST /v1/admin/agents/{id}/tokens` (o token aparece uma única vez).
   Revoga com `DELETE /v1/admin/agents/{id}/tokens/{token_id}`.
3. O time do agente publica, com o token só na variável de ambiente:

```bash
export AOK_PLATFORM_TOKEN="<token emitido>"
aok check --config agent.yaml --publish https://sua-plataforma --agent-id meu-agente
```

`--agent-id` pode vir de `platform.agent_id` no `agent.yaml`. O `agent_id` do pacote deve ser
o slug do agente dono do token.

## Regras do `POST /v1/reports`

- Token inválido, ausente ou revogado: 401. Agente inativo ou `agent_id` de outro agente: 403.
- Esquema fechado (campo extra: 422), no máximo 1 MiB (413). O log de auditoria não sobe.
- O servidor recalcula o sha256 de cada arquivo (divergência: 422); o mesmo `relatorio.json`
  para o mesmo agente: 409. Cada publicação recebe `seq` 1, 2, 3... por agente.
- As versões são imutáveis: a API não tem update nem delete.

Use HTTPS na frente da API fora de testes locais: o token trafega no cabeçalho.
