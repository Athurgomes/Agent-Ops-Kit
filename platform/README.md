# Plataforma agent-ops-kit (fases 2 e 3: API, login e portal)

API FastAPI que recebe o pacote de relatório publicado por `aok check --publish URL`.
A leitura (áreas, agentes, relatórios, download) é só para usuários com sessão; o token de agente só publica.

## Subir

```bash
cp platform/env.example platform/.env      # preencha os dois valores; o .env não é commitado
docker compose -f platform/docker-compose.yml --env-file platform/.env up --build
```

A API fica em `http://127.0.0.1:8000` (docs interativas em `/docs` quando `AOK_DOCS_ENABLED` não está em `false`; probe de saúde em `GET /v1/health`). Os arquivos dos
relatórios ficam no volume `aok_data` (`AOK_DATA_DIR`, padrão `./aok_data` fora do Docker e `/data` no Docker Compose).
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
   5 falhas por e-mail travam o e-mail por 5 minutos (429, contagem compartilhada no banco com chave em SHA-256).
4. Leitura (só sessão): `GET /v1/areas`, `/v1/areas/{id}/agents`, `/v1/agents/{id}/reports`,
   `/v1/reports/{id}`, `/v1/reports/{id}/download?format=md|html|json`. Área fora do alcance: 404.
5. Todo download grava em `download_log`. `GET /v1/me/downloads` mostra só os do próprio usuário
   (`downloaded_at` e `generated_at`); `GET /v1/admin/downloads` (org_admin por sessão) mostra todos.

## Portal (fase 3, front-end)

Código em `platform/portal/` (React + Vite + TypeScript + Tailwind, sem biblioteca de UI). O portal
tem nome oficial **Farol.**, com identidade e canal comercial opcional (`CONTACT_URL`, vazio por
padrão para ocultar CTAs de contato) definidos em `platform/portal/src/brand.ts`, e interface 100%
em `pt-BR` centralizada em `platform/portal/src/copy.ts` (alinhada ao conteúdo dos relatórios e do
`seed_demo`, com foco B2B sem cadastro aberto nem página de preços).

- **Direção visual e tipografia**: estética de diário de bordo / carta náutica (papel `#ffffff`,
  tinta `#0a0a0a`, superfície `#f7f7f5` e azul `#2563eb` reservado a CTAs primários, links, foco
  `:focus-visible`, ponto da marca e estados ativos), com fontes autohospedadas via `@fontsource`
  (`Bricolage Grotesque`, `IBM Plex Sans` e `IBM Plex Mono`, sem CDN externo), desenhos ASCII com
  `aria-hidden="true"` e suporte a `prefers-reduced-motion: reduce`.
- **Semáforo-como-resultado**: nunca depende apenas de cor — exibe glifos distintos (`●` Verde,
  `◐` Amarelo, `✕` Vermelho), rótulo textual e prefixo acessível, sempre acompanhado das regras
  provisórias e das ressalvas ("Verde não significa seguro" e autodeclaração).
- **Telas**: landing pública (`/`), login (`/login`), áreas > agentes > relatórios > detalhe
  (`/app/...`; botões `Baixar HTML (ABNT / PDF)`, `Baixar Markdown` e `Baixar JSON`, com impressão
  A4 ou salvamento em PDF pelo navegador no padrão ABNT NBR 10719), "Meus downloads" e, para
  `org_admin`, menu "Administração" (áreas, agentes, usuários, atividade) e "Todos os downloads".
- **Console do operador (`/ops/*`)**: preservado desligado por padrão (só responde quando o
  servidor sobe com `AOK_OPS_ENABLED=true`), sem links no site público nem no portal das
  organizações e renderizado como 404 comum quando desativado (ADR-010 e ADR-015).

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

Telas de administração do portal (só `org_admin`, menu "Administração"): áreas, agentes (cadastro,
tokens, ativar/desativar), usuários (criar, redefinir senha, acessos) e atividade. Tokens e senhas
geradas aparecem uma única vez, só em estado da tela (nunca em storage, URL ou console).

## Multiempresa (isolamento por organização)

- `organization` tem `slug` único (`[a-z0-9-]{1,64}`), `active` e `created_at`. Organização inativa:
  seus usuários não logam (erro genérico), as sessões existentes dão 401, os tokens de agente dão 401
  e nada é apagado. Reativar devolve tudo.
- O slug de agente é único **por organização** (`UNIQUE(org_id, slug)`); o 409 só vale dentro da
  própria organização e não revela outras organizações (inclusive após migrar bancos SQLite legados,
  nos quais a migração inicial recria `agent` preservando os dados e removendo o `UNIQUE(slug)` global).
  O e-mail de usuário continua único **globalmente**: o
  login é só por e-mail, então o mesmo e-mail em duas organizações seria ambíguo.
- Relatórios novos ficam em `AOK_DATA_DIR/<org_id>/<slug>/<sha256>`. Os já gravados continuam
  resolvidos pelos caminhos guardados no banco (download com checagem contra path traversal).
  O mesmo `sha256` pode existir em duas organizações sem colisão.
- Chave de bootstrap: com exatamente 1 organização funciona como antes; com 2 ou mais as rotas admin
  exigem o cabeçalho `X-Org-Slug` (400 se faltar; 404 se a organização não existir ou estiver
  inativa). `/v1/admin/events` e `/v1/admin/downloads` seguem só por sessão. Sessão de `org_admin`
  sempre usa a organização do próprio usuário (o cabeçalho é ignorado).
- Criar a 2ª organização por enquanto (ou, com o console ligado, pela tela do operador):

```bash
python -m aok_platform.create_org --slug acme --name "Acme"
# primeiro admin da nova organização, com a chave de bootstrap:
curl -X POST http://127.0.0.1:8000/v1/admin/users -H "Authorization: Bearer $AOK_ADMIN_BOOTSTRAP_KEY"   -H "X-Org-Slug: acme" -H "Content-Type: application/json" -d '{"email":"admin@acme.example","password":"<12+ caracteres>"}'
# depois POST /v1/admin/memberships com {"user_id": <id>, "role": "org_admin"} (mesmos cabeçalhos)
```

- Migrações formais de banco com **Alembic** (`platform/aok_platform/migrations/`, revisões
  `0001_initial_schema` e `0002_rate_limit_entry`): aplicadas automaticamente no startup por padrão (`ensure_schema` via
  `AOK_AUTO_MIGRATE=true`), com lock transacional (`pg_advisory_xact_lock`) em Postgres e upgrade
  seguro de bancos legados preservando dados (`organization.slug`, `active`, `created_at`,
  `agent.org_id` e remoção do `UNIQUE(slug)` global no SQLite e Postgres).
- Para aplicar ou inspecionar migrações explicitamente (recomendado com `AOK_AUTO_MIGRATE=false`
  ao subir vários workers):

```bash
python -m aok_platform.migrate upgrade   # aplica até head (lê AOK_DATABASE_URL ou --url)
python -m aok_platform.migrate current   # mostra revisão aplicada
```
- `seed_demo` continua usando a única organização (a primeira).

## Operador da plataforma (`/v1/ops`)

Desligado por padrão: só existe com `AOK_OPS_ENABLED=true` (senão 404). O operador não pertence a
nenhuma organização, tem login e cookie próprios (`aok_ops_session`, `Path=/v1/ops`, 4 h) e a chave de
bootstrap não tem relação com ele. Criação só por linha de comando:

```bash
python -m aok_platform.create_operator --email ops@example.com          # imprime a senha UMA vez
python -m aok_platform.create_operator --email ops@example.com --reset-password
python -m aok_platform.create_operator --email ops@example.com --reset-password --activate   # reativa um operador inativo
```

`--reset-password` **não** reativa um operador inativo (mais seguro): a senha nova fica gravada, mas o login
continua barrado até rodar de novo com `--activate` (que só vale junto com `--reset-password`).

Rotas (todas com sessão de operador; escritas vão para `operator_event`): `POST /v1/ops/auth/login|logout`,
`GET /v1/ops/auth/me`, `GET|POST /v1/ops/organizations`, `GET|PATCH /v1/ops/organizations/{id}` (sem DELETE),
`POST /v1/ops/organizations/{id}/admins` e `.../admins/{user_id}/reset-password` (a senha gerada volta
uma única vez), `GET /v1/ops/organizations/{id}/events` e `GET /v1/ops/events`. O operador só vê
metadados: nenhuma rota devolve conteúdo de relatório, download, token, hash ou senha (ADR-010).
As respostas que trazem a senha gerada (criar admin e reset) saem com `Cache-Control: no-store` e `Pragma: no-cache`.
No portal, o console fica em `/ops/*` (sem link em lugar nenhum); com o servidor sem `AOK_OPS_ENABLED`, `/ops/*` aparece como página inexistente (inclusive o título da aba, que só muda quando o console existe).

## Rodar os testes em Postgres

Por padrão os testes de plataforma usam SQLite em memória. Com `AOK_TEST_DATABASE_URL` definida, cada teste
roda num **schema novo** do Postgres (criado e apagado por `tests/conftest.py`, sem lixo). Exemplo com um
container efêmero (porta só em 127.0.0.1; a senha vai só na variável de ambiente, nunca em arquivo):

```bash
PGPW=$(python -c "import secrets;print(secrets.token_hex(16))")
docker run -d --rm --name aok-pg-test -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD="$PGPW" postgres:16
export AOK_TEST_DATABASE_URL="postgresql+psycopg://postgres:$PGPW@127.0.0.1:55432/postgres"
python -m pytest tests/test_platform_*.py -q      # inclui test_platform_pg_legacy.py (migração de banco legado)
docker rm -f aok-pg-test
```

A suíte em Postgres é bem mais lenta (um schema por teste): localmente em `postgres:16` efêmero, em 17/11/2026 (commit
`79f1d01`), a suíte completa passou com `254 passed, 0 skipped` em 266.37s (0:04:26) (incluindo `test_platform_pg_legacy.py`).
O CI também tem o job `postgres` com o mesmo teste; ele passou no GitHub até o run #25 (commit 669633a, conferido em
17/11/2026).

## Recuperação de senha (e-mail, opcional)

Só existe com `AOK_SMTP_HOST` **e** `AOK_PUBLIC_URL` definidos; sem isso `POST /v1/auth/password/forgot|reset`
respondem 404 e `GET /v1/auth/capabilities` devolve `{"password_reset": false}` (com tudo configurado, `true`).

| Variável | Função |
|----------|--------|
| `AOK_SMTP_HOST`, `AOK_SMTP_PORT` (587) | servidor SMTP (stdlib `smtplib`, sem serviço externo obrigatório) |
| `AOK_SMTP_USER`, `AOK_SMTP_PASSWORD` | credenciais, opcionais |
| `AOK_SMTP_STARTTLS` (true) | `false` só para SMTP local sem TLS |
| `AOK_SMTP_FROM` | remetente (padrão `no-reply@<host>`) |
| `AOK_PUBLIC_URL` | base do link do e-mail (ex.: `https://farol.example.com`). **Nunca** vem do cabeçalho Host/X-Forwarded (evita host header poisoning) |

- `POST /v1/auth/password/forgot {email}`: responde **sempre 202**, com o mesmo corpo, exista ou não o e-mail,
  esteja o usuário ou a organização ativos ou não. A consulta, o token e o envio rodam depois da resposta. Só
  envia se o usuário e a organização estiverem ativos. Limites persistidos no banco (`rate_limit_entry`, chave em
  SHA-256): 3 pedidos por e-mail e 10 por IP por hora (ao exceder, continua 202 sem enviar). Falha de SMTP não
  aparece para o cliente; o log traz só o e-mail mascarado (`a***@e***.com`), nunca o token.
- O e-mail leva só o link `{AOK_PUBLIC_URL}/reset-password#token=<token>` (token no **fragmento**, que não vai
  para logs nem Referer), validade de 30 min e o aviso "if you didn't request this, ignore it".
- `POST /v1/auth/password/reset {token, new_password}`: senha com 12+ caracteres (422 se curta); falha por
  qualquer motivo (inexistente, expirado, usado, usuário ou organização inativos) = `400 invalid or expired
  token`; mais de 10 tentativas inválidas por IP por hora = 429 (tokens válidos continuam sendo aceitos mesmo após
  10 falhas do IP, evitando negação de serviço em NAT/IP compartilhado). Sucesso = 204 sem corpo: troca a senha,
  revoga **todas** as sessões do usuário, invalida os outros tokens pendentes, grava `user.password_reset` em
  `admin_event` e envia um aviso "Your password was changed". Não faz login automático.
- Token: `token_urlsafe(32)`, só o hash SHA-256 na tabela `password_reset` (sem IP), uso único, 30 min; um novo
  pedido invalida os anteriores.
- Limitações: os limites são compartilhados no banco (`rate_limit_entry`, com poda periódica de entradas vencidas);
  atrás de proxy reverso sem `AOK_TRUSTED_PROXIES` configurado, o IP visto é o do proxy (com a variável definida,
  usa o primeiro IP fora dos proxies confiáveis em `X-Forwarded-For`, da direita para a esquerda). O
  operador da plataforma não usa este fluxo (a senha dele só se redefine pela linha de comando).

## Operação online (produção)

Para operar a plataforma publicada online em instância única:

1. **Publicação no CI do agente**: o pipeline do time do agente gera o pacote e envia apenas agregados,
   hashes e relatórios via `aok check --publish https://...` com `AOK_PLATFORM_TOKEN` em segredo de
   ambiente (o log completo de auditoria nunca sobe).
2. **Container único atrás de proxy reverso HTTPS**: suba a imagem de [platform/Dockerfile](Dockerfile)
   (API FastAPI + portal React compilado) atrás de proxy reverso com terminação TLS/HTTPS, ligada a um
   Postgres externo/gerenciado (`AOK_DATABASE_URL`) e a um volume persistente montado em `AOK_DATA_DIR`
   (`/data` no container).
3. **Configuração recomendada no ambiente** (ver [platform/env.example](env.example) e
   [platform/docker-compose.yml](docker-compose.yml)):
   - `AOK_COOKIE_SECURE=true` (padrão; exige HTTPS para o cookie de sessão);
   - `AOK_DOCS_ENABLED=false` (desativa `/docs`, `/redoc` e `/openapi.json`, inclusive no fallback SPA);
   - `AOK_HSTS_ENABLED=true` (envia `Strict-Transport-Security: max-age=31536000; includeSubDomains`;
     use apenas com HTTPS obrigatório — `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` e
     `Referrer-Policy: no-referrer` já vão em todas as respostas);
   - `AOK_TRUSTED_PROXIES=<IPs/CIDRs do proxy>` (lista separada por vírgula dos proxies confiáveis para
     extrair o IP real em `X-Forwarded-For` na recuperação de senha);
   - `AOK_AUTO_MIGRATE=false` (opcional em deploy com múltiplos workers/réplicas: desativa a
     execução de migrações no startup e exige rodar `python -m aok_platform.migrate upgrade`
     antes de iniciar os processos da API);
   - Remova `AOK_ADMIN_BOOTSTRAP_KEY` após criar o primeiro `org_admin` (ou usar `AOK_OPS_ENABLED=true` +
     CLI `create_operator`).
4. **Healthcheck**: configure o proxy/orquestrador em `GET /v1/health`, que valida `SELECT 1` no Postgres
   e o acesso a `AOK_DATA_DIR` (`200 {"status": "ok"}` ou `503 {"status": "unavailable"}`, com
   `Cache-Control: no-store`). O serviço `api` em `platform/docker-compose.yml` já usa esse endpoint.

Múltiplas réplicas e vários workers: as migrações de esquema usam **Alembic** (com `pg_advisory_xact_lock` em
Postgres e opção `AOK_AUTO_MIGRATE=false` para rodar `python -m aok_platform.migrate upgrade` antes de subir os
processos) e os limitadores de tentativas (`LoginThrottle` e `HourlyLimiter`) usam store compartilhado no banco
(`rate_limit_entry`, sem necessidade de Redis). Em múltiplos nós, apenas `AOK_DATA_DIR` precisa de volume
compartilhado para leitura dos arquivos de relatório. Detalhes das decisões e limites estão nos ADRs 014, 016 e 017
em [docs/decisoes.md](../docs/decisoes.md).

