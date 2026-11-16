# Plataforma agent-ops-kit (fases 2 e 3: API e login)

API FastAPI que recebe o pacote de relatório publicado por `aok check --publish URL`.
A leitura (áreas, agentes, relatórios, download) é só para usuários com sessão; o token de agente só publica.

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

## Usuários e leitura (fase 3, backend)

1. Com a chave de bootstrap, crie o primeiro usuário e dê o perfil `org_admin`:
   `POST /v1/admin/users` (`email`, `password` com 12+ caracteres) e
   `POST /v1/admin/memberships` (`{"user_id": 1, "role": "org_admin"}`, sem `area_id`).
   Depois disso o admin entra por sessão e pode criar os demais; a chave segue valendo
   (retire `AOK_ADMIN_BOOTSTRAP_KEY` do ambiente para desativá-la).
2. `area_viewer` exige `area_id` e vale para a área e todas as sub-áreas (nunca para cima).
3. Login: `POST /v1/auth/login` -> cookie `aok_session` (HttpOnly, SameSite=Strict, 8 h,
   `Secure` por padrão; `AOK_COOKIE_SECURE=false` só para teste local sem HTTPS).
   `POST /v1/auth/logout`, `GET /v1/auth/me`. Erro de login é sempre o mesmo (401);
   5 falhas por e-mail travam o e-mail por 5 minutos (429, contagem em memória do processo).
4. Leitura (só sessão): `GET /v1/areas`, `/v1/areas/{id}/agents`, `/v1/agents/{id}/reports`,
   `/v1/reports/{id}`, `/v1/reports/{id}/download?format=md|html|json`. Área fora do alcance: 404.
5. Todo download grava em `download_log`. `GET /v1/me/downloads` mostra só os do próprio usuário
   (`downloaded_at` e `generated_at`); `GET /v1/admin/downloads` (org_admin por sessão) mostra todos.
