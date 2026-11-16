# Plataforma agent-ops-kit (fases 2 e 3: API, login e portal)

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

## Portal (fase 3, front-end)

Código em `platform/portal/` (React + Vite + TypeScript + Tailwind, sem biblioteca de UI). Interface
em inglês; o nome "Farol" é provisório e fictício e vive só em `platform/portal/src/brand.ts`.
A interface está toda em inglês (landing, login, área logada). Páginas: landing pública, login,
areas > agents > reports > report detail (baixar MD/HTML/JSON), "My downloads" e, para `org_admin`,
"All downloads".
Para `org_admin`: Administration (áreas, agentes, usuários, atividade) e All downloads.

Limitação conhecida: o conteúdo dos relatórios vindo do backend (ressalvas, textos do resumo) continua
em português; só a interface foi traduzida. Itens "Soon" (Sign Up, Pricing, redes sociais, Docs,
Blog, Contact, Terms, Privacy) são placeholders não clicáveis.

```bash
cd platform/portal
npm ci
npm run build      # tsc --noEmit + vite build -> platform/portal/dist
npm run dev        # http://localhost:5173 com proxy de /v1 para http://127.0.0.1:8000
```

A API serve `platform/portal/dist` em `/` (com fallback de SPA para o `index.html`) quando a pasta
existe; sem ela a API fica como antes. `AOK_PORTAL_DIR` aponta outra pasta. As rotas `/v1` não mudam.
A imagem Docker já faz o build do portal (estágio `node:22-slim`) e o serve.

## Demonstração local

```bash
pip install -e ".[platform]"                 # na raiz do repositório
export AOK_COOKIE_SECURE=false               # só para teste local sem HTTPS
# opcional: AOK_DATABASE_URL e AOK_DATA_DIR (padrão: SQLite ./aok_platform.db e ./aok_data)
python -m aok_platform.seed_demo             # rode na raiz do repositório
uvicorn aok_platform.app:create_app --factory   # abra http://127.0.0.1:8000
```

O seed é idempotente e só roda em banco local (SQLite ou localhost). Cria 2 áreas raiz
(Operações, com a sub-área Atendimento, e Finanças), 3 agentes fictícios e 3 usuários
(`admin@demo.example` como `org_admin`; `operacoes@demo.example` e `financas@demo.example` como
`area_viewer`). As senhas são geradas na hora e impressas uma única vez no terminal; não ficam em
arquivo (`--reset-passwords` gera novas). Cada agente recebe 2 versões do relatório REAL gerado
por `aok report build` a partir dos resultados gravados no repositório (a segunda usa
`--previous`); nenhum número é inventado. Rótulo: dados de demonstração: relatório do exemplo do
repositório. Os nomes dos agentes são fictícios; o conteúdo interno dos relatórios é o do
exemplo do repositório.

## Listagens e auditoria do admin

Só leitura, para `org_admin` (sessão) ou chave de bootstrap, sempre limitadas à organização de quem
chama: `GET /v1/admin/areas` (com `agent_count`), `/agents` (inclui inativos, `tokens_active_count`,
`last_report_at`), `/agents/{id}/tokens` (só metadados: nunca o token nem o hash), `/users`
(vínculos resumidos; nunca a senha nem o hash) e `/memberships`. Não há exclusão de áreas.
Toda escrita admin (criar/alterar área, agente, usuário, vínculo; emitir/revogar token; trocar
senha; ativar/desativar) grava um `admin_event` (quando, quem, ação, alvo; sem segredos; imutável).
`GET /v1/admin/events` (só sessão de `org_admin`; a chave de bootstrap não lê) devolve os mais
recentes primeiro, com `limit` (1 a 500) e `offset`.

Telas de administração do portal (só `org_admin`, menu "Administration"): áreas, agentes (cadastro,
tokens, ativar/desativar), usuários (criar, redefinir senha, acessos) e atividade. Tokens e senhas
geradas aparecem uma única vez, só em estado da tela (nunca em storage, URL ou console).

## Multiempresa (isolamento por organização)

- `organization` tem `slug` único (`[a-z0-9-]{1,64}`), `active` e `created_at`. Organização inativa:
  seus usuários não logam (erro genérico), as sessões existentes dão 401, os tokens de agente dão 401
  e nada é apagado. Reativar devolve tudo.
- O slug de agente é único **por organização** (`UNIQUE(org_id, slug)`); o 409 só vale dentro da
  própria organização e não revela outras. O e-mail de usuário continua único **globalmente**: o
  login é só por e-mail, então o mesmo e-mail em duas organizações seria ambíguo.
- Relatórios novos ficam em `AOK_DATA_DIR/<org_id>/<slug>/<sha256>`. Os já gravados continuam
  resolvidos pelos caminhos guardados no banco (download com checagem contra path traversal).
  O mesmo `sha256` pode existir em duas organizações sem colisão.
- Chave de bootstrap: com exatamente 1 organização funciona como antes; com 2 ou mais as rotas admin
  exigem o cabeçalho `X-Org-Slug` (400 se faltar; 404 se a organização não existir ou estiver
  inativa). `/v1/admin/events` e `/v1/admin/downloads` seguem só por sessão. Sessão de `org_admin`
  sempre usa a organização do próprio usuário (o cabeçalho é ignorado).
- Criar a 2ª organização por enquanto (a tela/rota do operador vem depois):

```bash
python -m aok_platform.create_org --slug acme --name "Acme"
# primeiro admin da nova organização, com a chave de bootstrap:
curl -X POST http://127.0.0.1:8000/v1/admin/users -H "Authorization: Bearer $AOK_ADMIN_BOOTSTRAP_KEY"   -H "X-Org-Slug: acme" -H "Content-Type: application/json" -d '{"email":"admin@acme.example","password":"<12+ caracteres>"}'
# depois POST /v1/admin/memberships com {"user_id": <id>, "role": "org_admin"} (mesmos cabeçalhos)
```

- Colunas novas em bancos existentes: `ensure_schema` (em `db.py`, roda no startup) adiciona o que falta
  e preenche (slug da organização, `active`, `created_at`, `agent.org_id`). **Migração formal
  (Alembic) continua dívida.** Limite conhecido: em bancos antigos a restrição `UNIQUE(slug)` de
  `agent` permanece no SQLite (o Postgres a remove); lá o slug segue global até recriar a tabela.
- `seed_demo` continua usando a única organização (a primeira).

