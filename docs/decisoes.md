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
- Exercitado em 2 PRs de teste no GitHub, fechados sem mesclar (#1 e #2; ver a seção D de [resultados.md](resultados.md)): o gate falhou por manifesto desatualizado e, com as respostas regravadas, por regressão. É um teste de mecanismo, com uma execução por PR. O workflow também foi checado com `actionlint`.

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

## ADR-004: auditoria com hash encadeado

**Contexto.** O fluxo do projeto precisa mostrar o que o agente recebeu, chamou e respondeu, e permitir conferir depois se o registro foi alterado. O projeto é local e sem custo, então não há serviço externo de log imutável.

**Decisão.** `src/agent_ops_kit/audit.py` grava um JSONL append-only, uma linha por evento, com `seq`, `ts` (UTC), `event`, `data`, `prev_hash` e `hash`. O `hash` é o sha256 da serialização canônica (`sort_keys=True`, `separators=(',',':')`, `ensure_ascii=False`) de todos os campos menos o próprio `hash`; a 1ª linha usa `prev_hash` igual a 64 zeros. `verify` recalcula a cadeia do início e aponta a primeira linha com problema (hash, `prev_hash`, `seq`, JSON inválido ou campo ausente). `AuditLog` recusa continuar uma cadeia quebrada. Opcionalmente, `anchor(path)` devolve o último hash para ser guardado fora do arquivo (CI, commit), e `verify` aceita `expected_last_hash` e `expected_n`.

**Consequências e limitações.**
- Detecta edição de conteúdo, remoção ou troca de ordem de linhas no meio da cadeia, inserção forjada (o hash da linha inserida não fecha a cadeia seguinte) e linha truncada.
- Não detecta truncamento do fim do arquivo (apagar as últimas linhas deixa uma cadeia válida mais curta). Só a âncora externa, se o operador a guardou, revela isso.
- Não detecta a reescrita completa da cadeia por quem tem acesso de escrita ao arquivo e recalcula todos os hashes. Não há chave nem assinatura. Isto não é imutabilidade, é evidência de adulteração parcial.
- O log reflete o que a aplicação registrou; o que não foi registrado não aparece, e dados sensíveis registrados ficam no arquivo em texto claro.
- Escrita thread-safe dentro de um processo; sem coordenação entre processos no mesmo arquivo.
- Alternativa descartada por ora: assinatura (HMAC/chave) ou carimbo de tempo externo, que fecham a reescrita completa mas exigem gestão de chave.
- **Atualização (ADR-018).** Assinatura digital opcional da âncora com **Ed25519** e **HMAC-SHA256** adicionada em `src/agent_ops_kit/audit_sign.py` e integrada a `aok audit`, `aok report build` e `aok check` (mantendo ausência de carimbo de tempo RFC 3161 TSA).

## ADR-005: template do `aok new` dentro do pacote, com cópia do núcleo do agente

**Contexto.** `aok new` precisa funcionar numa instalação normal, e `examples/` não faz parte do pacote. O plano sugere `templates/agent/` na raiz do repositório, que também ficaria de fora do pacote instalado.

**Decisão.** O template fica em `src/agent_ops_kit/templates/agent/`, incluído via `package-data` no `pyproject.toml` (desvio em relação ao plano). O núcleo do agente gerado (`app/agent.py`, `tools.py`, `indexer.py`) é uma cópia do agente de referência, e não uma promoção do código para o pacote: o núcleo tem padrões ligados ao exemplo (caminhos do config, do corpus e do Chroma) e os testes, o eval e o red team dependem de atributos desses módulos (monkeypatch em `tools.query_index`, `CONFIG_PATH`, `CORPUS_DIR`). Mover o código mudaria superfícies que as respostas gravadas e os resultados de red team tomam como dadas. Só mudam as 3 linhas de caminho, e `tests/test_new.py` compara o template com o original aplicando exatamente essas edições, então falha se os dois derivarem.

**Consequências.**
- O comportamento do agente de referência e os artefatos em `evals/` e `redteam/results/` ficam intactos.
- Correções no núcleo precisam ser repetidas no template; o teste de deriva avisa se esquecerem.
- O agente gerado depende do extra `rag` do kit (Chroma e Ollama), instalado com `pip install -e ".[rag]"` a partir do repositório do kit e de `docker compose up` do kit para ver o trace; o tracing se desliga com `AOK_TRACING=off`.
- Os arquivos do template são excluídos do ruff, por serem código de um projeto à parte (`app` não é pacote do kit).

## ADR-006: relatório publicado em pasta local versionada

**Contexto.** O relatório precisa chegar a quem não é técnico sem expor o que o agente processou.

**Decisão.** `aok check --publish` grava cada publicação em uma pasta nova (`<pasta>/<agent-id>/<timestamp UTC>/`) e atualiza `index.json`, mais recente primeiro; nunca sobrescreve versões. Entram só agregados e hashes (inclusive o resultado da verificação da cadeia de auditoria e a âncora); o log de auditoria nunca entra, por privacidade. O semáforo usa regras provisórias.

**Consequências e limitações.**
- A imutabilidade é por convenção, não técnica: quem tem acesso ao disco pode alterar ou apagar versões.
- Verde não significa seguro: o semáforo herda as limitações das medições (modelo pequeno, dataset pequeno, heurísticas contornáveis).
- Alternativas descartadas: enviar o log completo (expõe dados e conteúdo das interações); banco ou serviço próprio nesta fase (custo e manutenção sem necessidade para o escopo atual).

## ADR-007: plataforma de recebimento de relatórios em `platform/`

**Contexto.** O `aok check --publish` grava em pasta local (ADR-006). Para times diferentes publicarem num ponto comum, é preciso um serviço que receba o pacote. Isto é uma extensão fora do plano original.

**Decisão.** A plataforma fica em `platform/` no mesmo repositório (pacote `aok_platform`, extra `platform`), com FastAPI e SQLAlchemy: SQLite nos testes e Postgres no Docker.
- Só o relatório, os agregados e os hashes vão à plataforma (`aok check --publish URL`); o log de auditoria completo nunca sobe.
- O token de agente só publica e é guardado como hash (sha256); aparece uma única vez na emissão e pode ser revogado.
- As rotas admin usam uma chave de bootstrap lida de `AOK_ADMIN_BOOTSTRAP_KEY`; sem a variável, respondem 503. Não há chave padrão.
- O slug do agente é único globalmente (alterado nos ADRs 011 e 016 para único por organização, inclusive em bancos SQLite legados).
- Cada versão publicada recebe `seq` por agente; a API não tem update nem delete.

**Consequências e limitações.**
- O relatório é autodeclarado: a plataforma confere o esquema, o tamanho e o sha256 dos arquivos, mas não reexecuta eval nem red team. Quem publica pode enviar números que não vieram de uma execução real.
- A imutabilidade das versões vale só pela API: quem opera o banco ou o disco pode alterar ou apagar.
- A chave de bootstrap é única e compartilhada entre admins; não há login, papéis nem SSO na fase 2; login e papéis chegam na ADR-008.
- Estado da implantação (verificações com data; o que não foi reconfirmado está dito):
  - `docker compose` (API e postgres:16): reconfirmado localmente ponta a ponta em 19/11/2026 após o redesenho **Farol.** (incluindo o commit 308aee0), Alembic e `/v1/health`: build, subida, healthcheck de `db` e `api`, `GET /v1/health`, portal em `/`, `/v1/auth/capabilities`, cadastro admin, login por sessão, `aok report build`, `aok check --publish`, leitura do relatório e download `md`/`html`/`json`, reinício da API com persistência nos volumes nomeados `pg_data` e `aok_data`, conferência no Edge headless CDP em desktop (`1440x900`) e mobile (`375x812`, `0` erros de console/exceções JS, `scrollWidth <= innerWidth`), fluxos da UI admin (editar e desativar/reativar agente, conceder e revogar acesso posterior de área, redefinição de senha pelo admin) e `down -v`. Também exercitados em servidor local temporário SQLite/SMTP via Edge CDP em 19/11/2026: criação de organização com slug duplicado (`409` sem stack trace) em `/ops` e fluxo completo de recuperação de senha incluindo `429` em `/reset-password`.
  - CI: os runs dos commits 0b196eb, 88dc3fc (run #20, `evidencias/03-ci-github/`), 0c8c6b8 (run #24), 669633a (run #25) e fff746f (run #45, conferido em 19/11/2026) terminaram com sucesso nos três jobs em `ubuntu-latest` (`test`, onde `test_reset_recusa_link_simbolico` roda sem skip; `portal`; e `postgres`, com service container `postgres:16`).
  - Postgres real: verificado localmente em 19/11/2026 (commit fff746f) em `postgres:16` efêmero via `AOK_TEST_DATABASE_URL`: a suíte completa de plataforma (`286 passed, 0 skipped`, em 281.87s, incluindo `test_platform_pg_legacy.py`) passou, além de rodar no job `postgres` do CI. Os testes usam SQLite por padrão; com `AOK_TEST_DATABASE_URL`, rodam em Postgres.
  - Não verificados: leitor de tela, verificação automática completa de contraste, outros navegadores fora de Edge/Chromium, provedor SMTP externo real (STARTTLS), carga/desempenho em nuvem e `seed_demo` dentro do container do compose (a imagem não leva os resultados gravados do repositório).
  - Dívidas resolvidas nos ADRs posteriores: migrações formais com Alembic e remoção da restrição `UNIQUE(slug)` global em bancos SQLite legados (ADR-016), paginação das listagens admin/operador com `X-Total-Count` e store compartilhado de rate limiting no banco (`rate_limit_entry`, ADR-017).
- Alternativa descartada: enviar o log de auditoria (expõe conteúdo das interações).

## ADR-008: portal e login de usuários (fase 3)

**Contexto.** A fase 2 só recebe relatórios. Para pessoas lerem e baixarem, é preciso login, controle de acesso por área e um front-end. Extensão fora do plano original.

**Decisão.**
- Login por e-mail e senha, com hash scrypt da biblioteca padrão. Sessão em cookie `aok_session` (HttpOnly, SameSite=Strict, 8 h, `Secure` por padrão).
- CSRF só por SameSite=Strict. Isso vale enquanto portal e API estiverem no mesmo site (a API serve o portal); com domínios diferentes seria preciso token CSRF.
- Throttle de login em memória, por e-mail: 5 falhas travam o e-mail por 5 minutos (429).
- Acesso por área com herança para sub-áreas (CTE recursiva, nunca para cima). `org_admin` vê a organização toda. Área fora do alcance responde 404.
- `download_log` foi antecipado da fase 4 para a 3. Cada download grava o instante (baixado em) e o instante de geração do relatório (gerado em). Cada pessoa vê só os seus; só `org_admin` vê todos, por sessão e não pela chave de bootstrap, por LGPD. O filtro de área do histórico é por área exata, sem sub-áreas.
- Tabelas criadas com `create_all`, sem migração.
- Portal em React, Vite, TypeScript e Tailwind, servido pela própria API. O nome "Farol" é provisório e fictício (só em `platform/portal/src/brand.ts`). O visual é minimalista, em azul, com cantos arredondados (redesenho posterior ao primeiro visual, que se inspirava em um template neo-brutalista; o template foi abandonado). Substituído pelo ADR-009 e posteriormente consolidado no ADR-015.
- Idioma: toda a interface (landing, login, área logada) está em inglês. O conteúdo dos relatórios vindo do backend e os nomes do seed continuam em português (limitação conhecida). Superado pelo ADR-015 (interface consolidada em `pt-BR`).
- Placeholders: Sign Up, Pricing, redes sociais e links de rodapé (Docs, Blog, Contact, Terms, Privacy) aparecem como "Soon" e não são clicáveis. Na landing, a nota do fundador é um rascunho e a fala de usuário está marcada como placeholder, não é depoimento real. Superado pelo ADR-015.

**Consequências e limitações.**
- O throttle reinicia a cada deploy, não funciona com vários workers (cada processo conta separado) e permite que terceiros travem a conta de outra pessoa por 5 minutos.
- Dívida: sem Alembic, mudança de coluna não é aplicada em banco existente; adotar migração antes disso.
- A trilha cobre só o download (as escritas administrativas passaram a ter trilha no ADR-009); não há registro de login nem de leitura.
- Não há SSO, multiempresa, dark mode nem PDF (superado em parte pelos ADR-010 e ADR-011).
- Estado do `docker compose`, do Postgres e do CI (com datas e o que não foi reconfirmado): ver o ADR-007. Dívidas: sem Alembic; UNIQUE(slug) global em bancos SQLite antigos.
- **Atualização (ADR-016 e ADR-017):** as dívidas acima foram resolvidas posteriormente — migrações formais com Alembic e remoção da restrição `UNIQUE(slug)` global inclusive em bancos SQLite legados entraram no ADR-016, e o throttle de login migrou da memória para a tabela compartilhada `rate_limit_entry` no banco pelo ADR-017.

## ADR-009: administração do portal e trilha de eventos

**Contexto.** Depois do ADR-008, criar áreas, agentes, tokens e usuários dependia de chamadas diretas à API com a chave de bootstrap. O time de segurança precisa fazer isso pelo portal, com registro de quem mudou o quê. Extensão fora do plano original.

**Decisão.**
- Telas de administração, só para `org_admin`: `/app/admin/areas`, `agents`, `agents/:id` (com tokens), `users`, `activity` e `downloads`.
- Novas listagens `GET /v1/admin/areas`, `/agents`, `/agents/{id}/tokens`, `/users` e `/memberships`. Tokens: só metadados, nunca o token nem o hash. Usuários: nunca senha nem hash.
- Tabela `admin_event` (quando, quem, ação, tipo e id do alvo; sem segredos). Toda escrita administrativa grava o evento na mesma transação. `GET /v1/admin/events` só aceita sessão de `org_admin` (a chave de bootstrap não lê), mais recentes primeiro, com `limit` e `offset`. A API não tem update nem delete; o modelo também bloqueia alteração pelo ORM.
- Escopo por organização nas leituras e escritas administrativas: alvo de outra organização responde 404.
- Bloqueios 409: o admin não desativa a própria conta nem revoga o próprio `org_admin`; ninguém desativa ou revoga o último `org_admin` ativo, inclusive pela chave de bootstrap.
- Logout no portal só limpa a sessão local depois que o servidor confirma.
- Token emitido e senha gerada aparecem uma única vez e só em estado React (nunca em storage, URL ou console).
- Visual: texto preto em fundo branco, azul só em botões de impacto, links e foco; contêineres retos com borda de 1 px; inputs e botões em pílula; login em tela própria. Substitui a descrição do visual no ADR-008.

**Consequências e limitações.**
- Na época deste ADR a chave de bootstrap usava sempre a primeira organização (só havia uma). Superado pelo ADR-011.
- `admin_event` é imutável pela API, mas quem opera o banco pode alterá-lo.
- As listagens do admin não têm paginação; só os eventos têm.
- Mudança de coluna exigirá migração (Alembic); `create_all` continua.
- Visão multiempresa e de operador: ver ADR-010 e ADR-011.
- Verificado no navegador, com banco temporário: criar área e sub-área, registrar agente, emitir token (aparece uma vez), publicar um relatório real com `aok check --publish`, ver o relatório no portal, revogar o token e a publicação seguinte falhar com 401, criar usuário viewer com acesso só à área, desativar o usuário e o login falhar, ver os eventos.
- Não exercitados na interface: redefinir senha, editar ou reativar agente, conceder ou revogar acesso depois da criação.
- Postgres real verificado localmente (postgres:16 efêmero em Docker) e no CI (job postgres, run do commit 4f3e5a7): a suíte de plataforma (235 testes) passou, incluindo a migração de um banco legado. Estado do `docker compose`: ver o ADR-007. Não verificados: carga e desempenho em Postgres, `seed_demo` dentro do container do compose, Alembic (dívida), UNIQUE(slug) global em bancos SQLite antigos (dívida).
- **Atualização (paginação, ADR-016 e verificação em 19/11/2026):** todas as listagens de admin no backend passaram a suportar paginação retrocompatível (`limit`/`offset` + `X-Total-Count`), sendo que no portal atualmente apenas a tela de Atividade consome paginação via API (áreas, agentes, tokens e usuários ainda carregam a lista completa); os fluxos antes marcados como não exercitados (redefinir senha pelo admin, editar e desativar/reativar agente, conceder e revogar acesso depois da criação) foram exercitados via Edge CDP em `19/11/2026` (ADR-007); Alembic e remoção de `UNIQUE(slug)` global inclusive em bancos SQLite legados foram entregues no ADR-016 e deixaram de ser dívida.

## ADR-010: operador da plataforma (visão multiempresa, só metadados)

**Contexto.** Com mais de uma organização (isolamento por organização no backend), quem opera a plataforma precisa criar organizações, dar o primeiro acesso e ver a saúde de cada uma, sem virar leitor dos relatórios dos clientes. Extensão fora do plano original.

**Decisão.**
- Desligado por padrão: as rotas `/v1/ops/*` só existem com `AOK_OPS_ENABLED=true`; sem isso respondem 404.
- O operador fica em tabelas próprias (`platform_operator`, `operator_session`, `operator_event`) e não pertence a nenhuma organização. Login separado (`POST /v1/ops/auth/login`, cookie `aok_ops_session`, HttpOnly, SameSite=Strict, `Path=/v1/ops`, sessão de 4 h, mesmo scrypt, mesmo limitador de tentativas, erro genérico). Sessão de usuário, `org_admin` ou chave de bootstrap não vale em `/v1/ops`, e a sessão do operador não vale nas rotas de organização. A chave de bootstrap não tem relação com operadores.
- O operador só é criado por linha de comando (`python -m aok_platform.create_operator --email ...`): senha aleatória impressa uma vez, nunca em argumento nem em arquivo.
- `create_operator --reset-password` gera senha nova e encerra as sessões, mas NÃO reativa um operador inativo (mais seguro): para reativar é preciso o flag `--activate`, que só vale junto com `--reset-password`.
- As respostas que trazem a senha gerada (criar admin e reset) saem com `Cache-Control: no-store` e `Pragma: no-cache`.
- O console do portal fica em `/ops/*` e não é linkado em lugar nenhum do site público nem do portal das organizações. Com `AOK_OPS_ENABLED` desligado, `/ops/*` aparece como uma página 404 comum (inclusive o título da aba, que só muda quando o console existe) e `/v1/ops/*` responde 404. O console tem sessão própria, separada da do portal.
- Rotas: listar e criar organizações, alterar nome e ativar ou desativar (sem exclusão), criar um `org_admin` e redefinir a senha dele (a senha é gerada no servidor e devolvida uma única vez; o reset revoga as sessões), visão geral de uma organização, trilha de eventos administrativos da organização e trilha do próprio operador.
- Privacidade: o operador NÃO lê conteúdo de relatórios. Nenhuma rota `/v1/ops` devolve resumo, ressalvas, arquivos Markdown, HTML ou JSON, nem faz download, e nenhuma devolve token, hash de token, hash de senha ou senha (exceto a gerada, uma vez, na criação ou no reset). A visão geral traz só metadados: contagens, áreas, agentes (com tokens ativos, último relatório e semáforo da versão mais recente), usuários com acessos e versões (agente, número, semáforo, datas, número de casos, modelo).
- Toda escrita do operador (e o login) grava um `operator_event` (quando, quem, ação, organização e alvo; sem segredos), imutável pelo ORM.

**Consequências e limitações.**
- Quem opera o banco ou o servidor continua podendo ler tudo; a regra de privacidade vale para a API.
- O reset de senha devolve a senha ao operador porque não há envio de e-mail; ela precisa chegar ao admin por um canal seguro, fora da plataforma.
- Desativar uma organização corta login, sessões e tokens dela, mas não apaga nada; reativar devolve tudo.
- O throttle de login do operador é em memória, como o dos usuários.
- **Atualização (paginação e ADR-017):** o throttle de login do operador migrou da memória para a tabela compartilhada `rate_limit_entry` no banco no ADR-017, e `GET /v1/ops/organizations` e a lista `reports` de `GET /v1/ops/organizations/{id}` passaram a suportar paginação via `limit`/`offset` com cabeçalho `X-Total-Count`.

## ADR-011: isolamento multi-organização

**Contexto.** O ADR-009 assumia uma única organização. Para o operador (ADR-010) criar outras, o backend precisa isolar os dados por organização. Extensão fora do plano original.

**Decisão.**
- `organization` ganha `slug` único (`[a-z0-9-]`, 1 a 64), `active` e `created_at`. `agent` ganha `org_id`, e o slug do agente é único por organização (`UNIQUE(org_id, slug)`).
- O e-mail de usuário continua único globalmente, porque o login é só por e-mail; o mesmo e-mail em duas organizações seria ambíguo.
- Relatórios novos ficam em `AOK_DATA_DIR/<org_id>/<slug>/<sha256>`. Os antigos continuam resolvidos pelos caminhos guardados no banco, com checagem contra path traversal. O mesmo `sha256` pode existir em duas organizações.
- Chave de bootstrap: com exatamente 1 organização funciona como antes; com 2 ou mais exige o cabeçalho `X-Org-Slug` (400 se faltar, 404 se a organização não existir ou estiver inativa). Nunca assume "a primeira". `/v1/admin/events` e `/v1/admin/downloads` seguem só por sessão. Sessão de `org_admin` usa sempre a organização do usuário.
- Organização inativa: login falha (erro genérico), sessões e tokens de agente dão 401, nada é apagado; reativar devolve tudo.
- `ensure_schema` (em `db.py`, roda no startup, idempotente) adiciona colunas e tabelas novas e preenche os valores. Alembic continua pendente.
- `python -m aok_platform.create_org --slug ... --name ...` cria uma organização sem o console do operador.

**Consequências e riscos conhecidos.**
- Em bancos SQLite antigos, o `UNIQUE(slug)` de `agent` continua global até recriar a tabela. O 409 de slug pode então revelar que o slug existe em outra organização.
- O 409 de e-mail revela que o e-mail existe em alguma organização.
- Com 1 organização inativa, a chave de bootstrap ainda opera nela sem o cabeçalho; com `X-Org-Slug` apontando para ela a resposta é 404.
- Em bancos antigos, `ensure_schema` cria os índices únicos `uq_organization_slug` e `uq_agent_org_slug`, mas não cria as chaves estrangeiras nem o índice simples de `agent.org_id`.
- Verificações gerais de Postgres e CI: ver ADR-007.
- O throttle de login é em memória.
- Verificado no navegador, com banco temporário e `AOK_OPS_ENABLED=true`: operador criado pela CLI, login em `/ops`, 2 organizações, admin criado (senha exibida uma vez), admin entra no portal e vê só a própria organização, cadastra área, agente e token, publica um relatório real com `aok check --publish` e o vê no portal; o operador vê só metadados; desativar uma organização barra o admin dela e a outra segue intacta; reativar; reset de senha; sessões de operador e de usuário não se misturam; `/ops` é um 404 comum com o console desligado.
- Não exercitados: erro de slug de organização duplicado na interface, leitor de tela e contraste, outros navegadores.
- **Atualização (ADR-016, ADR-017 e verificação em 19/11/2026):** Alembic e a remoção da restrição `UNIQUE(slug)` global de `agent` inclusive em bancos SQLite legados foram entregues no ADR-016; o throttle de login migrou para a tabela compartilhada `rate_limit_entry` no banco no ADR-017; e o erro `409` de slug de organização duplicado na interface `/ops` foi exercitado em `19/11/2026` sem stack trace (ADR-007).

## ADR-012: recuperação de senha por e-mail

**Contexto.** Usuários das organizações só tinham reset de senha feito por um admin. Extensão fora do plano original, opcional.

**Decisão.**
- Recurso opcional: só existe com `AOK_SMTP_HOST` e `AOK_PUBLIC_URL`. Sem eles, `/v1/auth/password/forgot` e `/reset` respondem 404, `/v1/auth/capabilities` devolve `password_reset: false` e o "Forgot password?" do login fica como placeholder.
- Envio por SMTP da biblioteca padrão, configurável: STARTTLS por padrão, timeout e contexto TLS padrão. SMTPS (porta 465) não é suportado.
- O link é montado só a partir de `AOK_PUBLIC_URL`, nunca de `Host` ou `X-Forwarded-Host`. O token vai no fragmento (`#token=`), que não chega a logs de servidor nem ao `Referer`; o front o remove da URL.
- Token: `token_urlsafe(32)`, só o hash SHA-256 no banco (`password_reset`), uso único (UPDATE condicional atômico), validade de 30 min; um novo pedido invalida os anteriores.
- `/forgot` responde sempre 202 com o mesmo corpo, e a consulta e o envio rodam em background (anti-enumeração). Limites em memória: 3 pedidos por e-mail e 10 por IP por hora.
- `/reset`: erro 400 genérico para qualquer token inválido, 429 após 10 tentativas inválidas por IP por hora, senha com 12+ caracteres. Sucesso revoga todas as sessões do usuário, não faz login automático, envia e-mail de aviso e grava `user.password_reset` em `admin_event`, sem segredos.
- Operadores seguem com reset só pela CLI. Um `org_admin` sem SMTP configurado depende do operador.

**Consequências e limitações.**
- Os limites são em memória, por processo: reiniciam no deploy e não somam entre workers.
- Sem `AOK_TRUSTED_PROXIES` configurado (ver ADR-014), atrás de proxy o IP visto é o do proxy (`X-Forwarded-For` não é confiado). O bloqueio de 10 tentativas inválidas pode então atingir quem compartilha o IP, inclusive com token válido (risco de negação de serviço). Melhoria futura: limitar só as tentativas inválidas e deixar o token válido passar.
- Entregabilidade (SPF, DKIM) não verificada.
- E-mail ausente ou com mais de 254 caracteres responde 422, não 202.
- Verificado especificamente neste fluxo: 8 `/reset` simultâneos por token em Postgres local deram exatamente 1 sucesso por token (verificação manual, fora do repositório); no navegador (Edge) com servidor SMTP local real (Mailpit): link real no login com o recurso ativo e placeholder "Soon" com ele desligado; UI idêntica para e-mail existente e inexistente (e-mail só para o existente); e-mail com link `#token` sem a senha; fragmento removido da URL; senha curta recusada; senha nova funciona e a antiga falha; sessão anterior revogada; link reusado inválido; novo pedido invalida o anterior; aviso de troca recebido; 4º pedido seguido sem e-mail.
- Não exercitados: envio por provedor SMTP real (STARTTLS, entregabilidade), 429 do reset na interface, leitor de tela, contraste e outros navegadores. Verificações gerais de Postgres, CI e contagem atual de testes: ver ADR-007 e a seção "Estado e testes" do [README](../README.md).
- **Atualização (ADR-017 e verificação em 19/11/2026):** os contadores de `/forgot` e `/reset` foram movidos da memória para a tabela compartilhada `rate_limit_entry` (chave em SHA-256), e `POST /v1/auth/password/reset` passou a validar e consumir o token antes de aplicar o bloqueio por IP — eliminando o risco de negação de serviço sobre tokens válidos sob IP compartilhado/NAT. O bloqueio `429` em `/reset-password` (junto do fluxo completo via `/forgot-password`) também foi exercitado na interface em `19/11/2026` (conforme ADR-007), permanecendo não exercitados envio por provedor SMTP externo real (STARTTLS/entregabilidade), leitor de tela, contraste automático completo e outros navegadores fora de Edge/Chromium.

## ADR-013: relatório técnico-executivo em linguagem de negócios e estrutura ABNT NBR 10719

**Contexto.** A partir do ADR-006, `aok report build` e `aok check --publish` produziam relatórios focados em métricas técnicas, com leitura pouco direta para áreas de negócio e sem padronização formal para registro de ciência em auditoria ou impressão A4 em PDF.

**Decisão.**
- Padronizar `src/agent_ops_kit/report/render.py` de forma determinística (sem redação livre por LLM), gerando `relatorio.md` e `relatorio.html` a partir dos mesmos blocos (`build_blocks`).
- Organizar o documento segundo a **ABNT NBR 10719:2015** e a numeração progressiva da **ABNT NBR 6024:2012**:
  - Pré-textuais e controle documental: código determinístico do documento (`REL-AOK-...`), data/hora de emissão, agente, versão de prompt, modelo, semente, versão de esquema/regras e resultado consolidado; resumo executivo e sumário executivo das seções.
  - Seções 1 a 6 em linguagem de negócios: `1 INTRODUÇÃO E ESCOPO DA AVALIAÇÃO`, `2 PARECER EXECUTIVO PARA NEGÓCIOS E GOVERNANÇA` (semáforo e leitura gerencial), `3 ANÁLISE DE QUALIDADE FUNCIONAL E CONTINUIDADE DO SERVIÇO`, `4 ANÁLISE DE EXPOSIÇÃO A RISCOS OPERACIONAIS E CONTROLES DE PROTEÇÃO`, `5 RASTREABILIDADE, PRIVACIDADE E LIMITAÇÕES METODOLÓGICAS` e `6 CONCLUSÃO, ENCAMINHAMENTOS E QUADRO DE CIÊNCIA PARA AUDITORIA` (encaminhamentos objetivos conforme o semáforo e tabela de ciência/aprovação para Responsável Técnico, Gestor da Área de Negócio e Auditoria Interna / Riscos e Conformidade).
  - `APÊNDICE A — EVIDÊNCIAS TÉCNICAS E CRIPTOGRÁFICAS PARA AUDITORIA` (A.1 a A.6): tabelas completas do A/B, ASR por categoria com IC 95% de Wilson, falsos positivos, manifesto das respostas, hashes SHA-256 das entradas e verificação da cadeia de auditoria.
- Paginação A4 em CSS estático (sem JavaScript, CSP `default-src 'none'; style-src 'unsafe-inline'`): `@page{size:A4;margin:3cm 2cm 2cm 3cm}` e regras `@media print` com quebra de página no Apêndice A, permitindo gerar PDF diretamente pelo navegador ("Imprimir / Salvar como PDF"). No portal (`platform/portal/src/pages/ReportView.tsx`), o botão principal passa a exibir `Download HTML (ABNT / Print PDF)`.
- Alternativa descartada: geração de texto livre por LLM, pois introduziria custo, variabilidade não reproduzível, risco de alucinação sobre números medidos e dependência de modelo na etapa de relatório.

**Consequências e limitações.**
- Preserva reprodutibilidade bit a bit (o mesmo `relatorio.json` gera exatamente o mesmo Markdown e HTML), custo zero e dispensa dependências pesadas de geração de PDF no servidor (como Chromium ou WeasyPrint).
- A geração do arquivo `.pdf` depende da ação de impressão do navegador do leitor; a API não entrega binário PDF diretamente.
- Os limiares do semáforo seguem provisórios (verde não significa agente imune a falhas), os textos internos permanecem em português mesmo com a interface do portal em inglês e a estrutura ABNT NBR 10719 não substitui parecer jurídico, regulatório nem auditoria externa independente.

## ADR-014: prontidão para operação online e simplicidade de manutenção

**Contexto.** Para operar a plataforma (`platform/`) online atrás de proxy reverso HTTPS e manter o pacote instalável fora da raiz do repositório, era necessário eliminar dependências de importação com `examples/`, ajustar dependências de desenvolvimento, expor endpoint de saúde, permitir desligar documentação interativa, aplicar cabeçalhos HTTP defensivos e suportar leitura controlada de `X-Forwarded-For`, sem tornar o CI ou a manutenção mais complexos.

**Decisão.**
- **D1 — Desacoplamento de `examples/`**: os imports de `examples.rag_agent` em `src/agent_ops_kit/eval/runner.py`, `src/agent_ops_kit/redteam/harness.py` e `src/agent_ops_kit/redteam/false_positives.py` passaram para carga sob demanda dentro das funções de execução ao vivo (`_load_run_agent`, `_load_example`), com mensagem explícita de `ImportError` quando `examples.rag_agent` não está disponível. Os fluxos offline (`aok eval --reuse`, `aok redteam report`, `aok report`, `aok audit`) funcionam sem a pasta `examples/` (`tests/test_packaging_isolation.py`).
- **D2 — `httpx` movido para o extra `dev`**: `httpx` saiu do extra `[project.optional-dependencies].platform` em `pyproject.toml` e passou para `[project.optional-dependencies].dev`, pois no repositório é usado apenas pelo `TestClient` nos testes da plataforma.
- **D3 — Tagline na landing do portal**: `platform/portal/src/pages/Landing.tsx` passou a exibir `BRAND_TAGLINE` na seção principal da landing (`"Test reports for AI agents, with the caveats in plain sight."`).
- **D5 — Manter apenas `ruff check` no CI**: `.github/workflows/ci.yml` mantém apenas `python -m ruff check .`, em vez de adotar `ruff format --check` e reformatar 49 arquivos existentes, priorizando diffs limpos, histórico legível e manutenção simples.
- **Prontidão online da plataforma (`platform/aok_platform/app.py`, `recovery.py`, `platform/docker-compose.yml`, `platform/env.example`)**:
  - `GET /v1/health`: executa `SELECT 1` no banco e verifica acesso/criação de `AOK_DATA_DIR`, devolvendo `200 {"status": "ok"}` ou `503 {"status": "unavailable"}` com `Cache-Control: no-store` e sem expor detalhes internos; usado no `healthcheck` do serviço `api` em `platform/docker-compose.yml`.
  - `AOK_DOCS_ENABLED` (padrão `true`): quando `false`, desliga `/docs`, `/redoc` e `/openapi.json` no FastAPI e também no fallback SPA em `mount_portal` (passam a responder 404).
  - Cabeçalhos HTTP de segurança via middleware em `app.py`: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` e `Referrer-Policy: no-referrer` em todas as respostas, mais `Strict-Transport-Security: max-age=31536000; includeSubDomains` quando `AOK_HSTS_ENABLED=true` (padrão `false`, para ativar somente atrás de HTTPS obrigatório).
  - `AOK_TRUSTED_PROXIES` em `recovery.py` (`client_ip`): lista opcional de IPs/CIDRs confiáveis separados por vírgula. Sem configuração (padrão), ignora `X-Forwarded-For` e usa o IP do par conectado; quando o par conectado pertence a uma rede confiável, varre `X-Forwarded-For` da direita para a esquerda e utiliza o primeiro IP fora da lista confiável nos limites horários por IP da recuperação de senha.

**Consequências e limitações.**
- A plataforma está pronta para rodar online em **instância única** (um worker/processo atrás de proxy reverso HTTPS, com Postgres gerenciado/externo e disco persistente para `AOK_DATA_DIR`).
- Para múltiplas réplicas ou vários workers em alta disponibilidade, continuam como próximos passos: adoção formal do **Alembic** para migrações (em vez de `ensure_schema` no startup) e armazenamento compartilhado fora da memória do processo para os limitadores de tentativas (`LoginThrottle` e `HourlyLimiter`).
- `AOK_TRUSTED_PROXIES` exige a lista exata dos proxies da infraestrutura (entradas inválidas são ignoradas com registro em log); sem ela, os limites por IP da recuperação de senha continuam vendo o IP do proxy.
- Os novos mecanismos foram validados por testes automatizados em SQLite/`TestClient` (`tests/test_packaging_isolation.py` e `tests/test_platform_online_readiness.py`); não houve teste de carga nem validação em nuvem de produção.
- **Atualização (ADR-016 e ADR-017).** As pendências para múltiplas réplicas foram implementadas nos ADRs seguintes: migrações formais com Alembic (ADR-016) e store compartilhado no banco para `LoginThrottle` e `HourlyLimiter` (ADR-017).

## ADR-015: portal oficial "Farol." em pt-BR, direção visual de diário de bordo e semáforo acessível

**Contexto.** Nos ADRs 008 e 009, o portal mantinha nome provisório, interface em inglês divergente do conteúdo em português dos relatórios e placeholders "Soon" (cadastro aberto, página de preços, depoimento fictício e rascunho de nota de fundador). Era preciso consolidar a identidade oficial, unificar o idioma da interface em `pt-BR`, eliminar elementos fictícios e reforçar a acessibilidade do semáforo e dos controles interativos sem depender de CDN externo.

**Decisão.**
- **Marca oficial "Farol."**: consolidada em `platform/portal/src/brand.ts` (`BRAND_NAME`, `BRAND_DOT`, `BRAND_TAGLINE`, `BRAND_SUBTITLE`) e no título das abas, encerrando o status provisório registrado no ADR-008.
- **Interface 100% em `pt-BR` centralizada em `copy.ts`**: todos os textos visíveis ao usuário (landing, autenticação, área logada, administração e console `/ops`) passam a viver em `platform/portal/src/copy.ts`, com datas e números formatados explicitamente em `pt-BR` (`platform/portal/src/format.ts`), alinhando a interface ao idioma dos relatórios e do `seed_demo`.
- **Foco B2B sem cadastro aberto nem preços**: removidos placeholders "Soon", rascunho de fundador e depoimento fictício. O canal comercial é opcional via `CONTACT_URL` em `platform/portal/src/brand.ts` (string vazia por padrão, ocultando CTAs de contato). O console do operador (`/ops/*`) permanece desligado por padrão (`AOK_OPS_ENABLED`) e sem links na interface (ADR-010).
- **Direção visual Diário de Bordo / Carta Náutica e tipografia autohospedada**: paleta em papel `#ffffff`, tinta `#0a0a0a`, superfície `#f7f7f5` e azul `#2563eb` reservado a CTAs primários, links, foco (`:focus-visible`), ponto da marca e estados ativos; tipografia autohospedada via `@fontsource` (`Bricolage Grotesque`, `IBM Plex Sans` e `IBM Plex Mono`, sem CDN externo); desenhos ASCII decorativos marcados com `aria-hidden="true"` e respeito a `prefers-reduced-motion: reduce`.
- **Semáforo-como-resultado com glifos distintos além da cor**: verde (`●`), amarelo (`◐`) e vermelho (`✕`) combinam cor, glifo distinto, rótulo textual e prefixo `sr-only`, sempre acompanhados das regras provisórias e das ressalvas explícitas ("Verde não significa seguro" e autodeclaração do relatório).

**Consequências e limitações.**
- Elimina a divergência de idioma entre interface e relatórios e remove dependência externa de fontes em tempo de execução, ao custo de embutir os arquivos `woff`/`woff2` no bundle estático (`platform/portal/dist/assets/`).
- O provisionamento de contas segue sob controle administrativo (`org_admin` ou operador), e alterar `CONTACT_URL` requer recompilar o front-end.
- O redesenho é restrito à camada de interface: não altera contratos de API, isolamento multi-organização, throttle em memória, regras provisórias do semáforo nem o caráter autodeclarado dos relatórios (ADR-007).
- Verificado no build (`npm run build`) e via Edge headless/CDP em `1440x900` e `375x812` (zero erros de console, `scrollWidth <= innerWidth`, foco por teclado `:focus-visible` e `prefers-reduced-motion: reduce` em `/`, `/login` e `/app` com API simulada via CDP `Fetch`); não houve validação em leitores de tela nem em navegadores fora do Edge/Chromium.
- **Atualização (ADR-017 e verificação em 19/11/2026):** os limitadores de tentativas migraram da memória para a tabela compartilhada `rate_limit_entry` no banco no ADR-017, e o portal **Farol.** (incluindo o commit `308aee0`) foi revalidado ponta a ponta contra o `platform/docker-compose.yml` em `19/11/2026` (ADR-007).

## ADR-016: migrações formais de banco com Alembic (SQLite e Postgres)

**Contexto.** Conforme registrado no ADR-014, o `ensure_schema` artesanal em `platform/aok_platform/db.py` apenas criava tabelas e colunas ausentes sem versionamento formal e mantinha no SQLite legado a dívida da restrição global `UNIQUE(slug)` na tabela `agent`. Para evoluir o esquema com segurança e preparar a camada de banco para múltiplos workers, era necessário adotar migrações formais com Alembic sem quebrar instalações existentes nem complicar o fluxo local/Docker.

**Decisão.**
- **Alembic empacotado em `aok_platform`**: adicionado `alembic>=1.13` ao extra `platform` em `pyproject.toml`, com os scripts empacotados em `platform/aok_platform/migrations/` (`env.py`, `script.py.mako`, `versions/0001_initial_schema.py`) via `package-data` e arquivo auxiliar `platform/alembic.ini` para uso direto com `alembic -c platform/alembic.ini`.
- **Revisão inicial `0001_initial_schema` compatível com banco vazio e legado**: em banco vazio cria as 14 tabelas, FKs, restrições únicas e índices equivalentes a `models.py`; em banco legado sem `alembic_version` adiciona colunas ausentes, executa o backfill determinístico (`organization.slug`, `active`, `created_at`, `agent.org_id`), cria os índices novos e remove a unicidade global de `agent.slug` tanto no Postgres (`DROP CONSTRAINT IF EXISTS agent_slug_key`) quanto no SQLite (via `batch_alter_table(..., recreate="always")` preservando todos os dados).
- **Concorrência e `AOK_AUTO_MIGRATE`**: em Postgres, `env.py` adquire `pg_advisory_xact_lock` antes do DDL dentro da transação; `init_db` mantém tratamento explícito de `IntegrityError` ao criar a organização `default`. `ensure_schema` delega para `run_migrations` (`platform/aok_platform/migrate.py`), que também expõe `python -m aok_platform.migrate [upgrade|current|heads]`. A variável `AOK_AUTO_MIGRATE` (padrão `true`) permite desligar a migração automática no startup (`false`, `0`, `no`, `off`) quando o operador executa `migrate upgrade` antes de subir vários workers.

**Consequências e limitações.**
- Bancos existentes criados antes do Alembic recebem a revisão inicial no primeiro `upgrade` sem perda de dados, e o SQLite legado passa a suportar o mesmo `slug` de agente em organizações diferentes.
- Com `AOK_AUTO_MIGRATE=false` sobre banco não migrado, `init_db` recusa o startup com erro explícito sem alterar o banco.
- A adoção do Alembic resolve o versionamento e a serialização de DDL, mas escalar para múltiplas réplicas ou vários workers ainda depende de um armazenamento compartilhado fora da memória do processo para os limitadores de tentativas (`LoginThrottle` e `HourlyLimiter`), que continuam sendo o próximo passo para multi-réplica (resolvido no ADR-017).

## ADR-017: store compartilhado de rate limiting no banco e endurecimento do reset de senha

**Contexto.** Conforme registrado nos ADRs 012, 014 e 016, `LoginThrottle` e `HourlyLimiter` mantinham contagens apenas na memória de cada processo — reiniciando em deploys e não somando entre múltiplos workers ou réplicas. Além disso, `POST /v1/auth/password/reset` checava o limite de falhas por IP antes de validar o token, o que podia bloquear um usuário legítimo com token válido atrás de IP compartilhado/NAT após 10 tentativas inválidas de terceiros (ADR-012).

**Decisão.**
- **Tabela `rate_limit_entry` (migração Alembic `0002_rate_limit_entry`)**: chave primária composta `(bucket, key_hash)` separando os escopos (`"login"`, `"ops_login"`, `"forgot_email"`, `"forgot_ip"`, `"reset_fail"`), com `count`, `window_start`, `locked_until` e `expires_at` indexado (`ix_rate_limit_entry_expires_at`). A coluna `key_hash` armazena sempre o digest SHA-256 hex (64 caracteres) do e-mail ou IP — nunca o dado bruto em texto puro.
- **`LoginThrottle` e `HourlyLimiter` compartilhados (`platform/aok_platform/rate_limit.py`)**: reexportados por `sessions.py` e `recovery.py` para compatibilidade; usam `clock=time.time` em segundos, aceitam `factory` e `bucket` (mantendo fallback em memória quando `factory is None`) e tratam concorrência em Postgres (`SELECT ... FOR UPDATE` + retry de `IntegrityError` na corrida de inserção) e SQLite (`BEGIN IMMEDIATE` + retry com backoff para `IntegrityError` e `OperationalError` de trava, além de serialização em memória para `:memory:` com `StaticPool`). Entradas vencidas (`expires_at < now`) são podadas periodicamente por bucket.
- **Endurecimento de `POST /v1/auth/password/reset` (`recovery.py`)**: o endpoint consulta e consome atomicamente o token válido primeiro (`used_at is None`, `expires_at > now`, usuário e organização ativos), retornando `204` mesmo que o IP já tenha atingido 10 tentativas inválidas. Apenas tentativas inválidas (incluindo reuso posterior de token consumido) consultam e incrementam o limitador `fail`, retornando `429` após o limite ou `400` genérico enquanto dentro do limite.
- **Alternativa descartada**: adicionar Redis ou serviço externo de cache, que aumentaria custo operacional e complexidade de infraestrutura sem necessidade no estágio atual.

**Consequências e limitações.**
- Limites de login, operador e recuperação de senha passam a persistir entre reinícios e a somar entre múltiplos workers ou réplicas ligados ao mesmo banco, sem dependências externas novas.
- Cada tentativa autenticada/recuperação executa consultas curtas na tabela `rate_limit_entry`; se a escala futura exigir menor carga no banco transacional, a interface de `LoginThrottle`/`HourlyLimiter` permite trocar o backend de armazenamento de forma isolada.
- Verificado em SQLite (multi-instância em arquivo compartilhado, isolamento de buckets, privacidade dos hashes, concorrência com threads, poda automática e fallback em memória) e migração incremental Alembic `0001 -> 0002` com `compare_metadata` sem divergências.

## ADR-018: assinatura digital criptográfica da âncora de auditoria (Ed25519 e HMAC-SHA256)

**Contexto.** Conforme registrado no ADR-004, a cadeia de hashes sem chave não detecta a reescrita completa do arquivo nem o truncamento do fim quando o operador não guarda a âncora externamente. Para autenticar o último estado do log em pipelines de CI e relatórios executivos sem introduzir serviços pagos ou infraestrutura externa de carimbo de tempo, era necessário assinar criptograficamente a âncora do log.

**Decisão.**
- **Módulo `src/agent_ops_kit/audit_sign.py` (reexportado por `audit.py`)**: implementa geração de pares Ed25519 (`generate_ed25519_keypair`, PEM PKCS8 sem passphrase para automação e permissão `0o600` via `os.chmod` em POSIX), assinatura da âncora (`sign_anchor`) e verificação (`verify_signature` retornando `SignatureVerifyResult`).
- **Payload canônico assinado**: `{"schema_version": 1, "n_events": ..., "last_hash": ..., "signed_at_utc": ...}` serializado em UTF-8 via `audit.canonical` (usando `GENESIS_HASH` quando o log está vazio). `sign_anchor` exige validação prévia integral da cadeia (`audit.verify`).
- **Algoritmos e proteção de segredos**: `ed25519` (via biblioteca `cryptography>=42`, com `key_fingerprint` igual ao SHA-256 hex da chave pública PEM) e `hmac-sha256` (com `key_fingerprint` derivado em `sha256("aok-hmac-v1:" + key)[:16]`). Na CLI (`aok audit sign`, `aok audit verify`, `aok report build`, `aok check`), a chave HMAC é lida exclusivamente de variável de ambiente (`--hmac-key-env` / `--audit-hmac-key-env`), nunca como argumento literal nem gravada em recibo ou log.
- **Integração no relatório ABNT (`report/build.py` e `report/render.py`)**: quando `--audit-signature` e a chave verificadora são informados, `relatorio.json` registra `audit.signature` (`checked`, `ok`, `algorithm`, `key_fingerprint`, `signed_at_utc`, `reason`). Falha na verificação aciona a regra vermelha `audit_invalid` no semáforo. Seção 5 e Apêndice A.6 exibem o status da assinatura e a ressalva metodológica correspondente.

**Consequências e limitações.**
- **Ed25519**: cobre integridade autenticada e não-repúdio sujeito à custódia protegida da chave privada (o arquivo PKCS8 não usa passphrase por padrão para permitir automação em CI).
- **HMAC-SHA256**: cobre integridade autenticada por chave simétrica compartilhada, **sem não-repúdio** perante terceiros que também detenham a chave.
- **Sem RFC 3161 TSA**: ambos os modos não incluem carimbo de tempo externo confiável (RFC 3161 Time-Stamping Authority); o campo `signed_at_utc` é autodeclarado pelo relógio local e a detecção de truncamento/reescrita depende de arquivar o recibo `.sig.json` fora do arquivo de log.

## ADR-019: medição de variância multi-execução na avaliação funcional (`aok eval --runs N`)

**Contexto.** Até o ADR-018, a avaliação funcional A/B (`aok eval`) executava cada caso do dataset uma única vez (`runs = 1`, semente fixa `42`), o que impedia medir a variância entre execuções repetidas e a consistência de score e de resposta das variantes avaliadas. Era necessário adicionar suporte a múltiplas execuções por caso mantendo total compatibilidade com os manifestos e respostas já gravadas no repositório (`evals/answers/`, 1 execução por configuração) e com o gate de CI sem modelo (`--reuse`).

**Decisão.**
- **Suporte a `runs` no runner (`src/agent_ops_kit/eval/runner.py`)**: `run_variant(..., runs: int = 1)` valida `runs >= 1`; com `runs == 1`, preserva exatamente o formato atual de registro (sem o campo `run_index`); com `runs > 1`, executa `for run_index in range(runs)` usando `make_ollama_llm(seed + run_index)` quando `llm is None` (ou o `llm` injetado) e grava `"run_index": run_index` em cada registro JSONL.
- **Agregação pareada e métricas de variância**: `score_records` passa a calcular a média dos scores por `case_id` quando há mais de um registro por caso (mantendo resultado idêntico para 1 execução por caso), de modo que `paired_ab` preserva a unidade amostral por caso sem inflar artificialmente o número de pares. As funções `score_runs` e `summarize_runs` agrupam registros por `run_index` (com fallback sequencial por `case_id` para retrocompatibilidade) e calculam `n_runs`, `per_run_means`, `mean`, `run_stdev` (desvio-padrão amostral entre as médias das execuções), `mean_case_stdev` (média dos desvios-padrão amostrais por caso), `exact_score_consistency_rate` e `exact_answer_consistency_rate`.
- **CLI e relatórios (`cli.py`, `report/build.py`, `report/render.py`)**: `aok eval` aceita `--runs N` (padrão `1`, validado `>= 1`) e inclui a seção `## Variância entre execuções` quando há múltiplas execuções. `manifest_entry` e `verify_manifest` mantêm o esquema atual sem campo obrigatório novo (`n_cases` continua registrando o total de registros gravados no JSONL). No pacote ABNT, `eval.variance` entra no `relatorio.json`, com leitura de variância na Seção 3 e subtabela `A.1.1` no Apêndice A.1 quando `runs > 1`; com 1 execução por configuração, a limitação explícita é mantida intacta.

**Consequências e limitações.**
- Os resultados atualmente gravados no repositório (`evals/answers/` e `docs/resultados.md`) permanecem com **1 execução por configuração** (semente 42) até que seja feita nova gravação com o Ollama local.
- O tempo de geração cresce linearmente com `runs` quando executado com o modelo; o CI continua usando `--reuse` sobre as respostas gravadas sem custo de inferência.

## ADR-020: endurecimento anti-ofuscação, janela multi-turn e classificador semântico local TF-IDF

**Contexto.** Conforme registrado nos ADRs anteriores e nas limitações documentadas em `input_filter.py`, as heurísticas originais baseadas apenas em expressões regulares, NFKC e remoção básica de zero-width podiam ser contornadas por homoglyphs cirílicos ou gregos, fragmentação de palavras por espaços ou pontuação (token-splitting), payloads codificados em Base64 ou Hex, ataques distribuídos em múltiplos turnos de conversa e paráfrases semânticas sem vocabulário literal das regras. Era preciso endurecer a camada de entrada sem introduzir dependências pagas, chamadas externas ou novos falsos positivos no conjunto benigno.

**Decisão.**
- **Normalização anti-ofuscação (`src/agent_ops_kit/guardrails/obfuscation.py`)**:
  - **Confusables / Homoglyphs**: mapeamento de caracteres cirílicos e gregos visualmente semelhantes para ASCII equivalente após NFKC, remoção de caracteres zero-width (reaproveitando `verdict.strip_invisible`) e remoção de caracteres de formatação invisíveis (`Cf`).
  - **Anti token-splitting**: colapso conservador apenas de sequências de tokens curtos separados por pontuação interna (`.`, `-`, `_`) ou espaços únicos entre letras individuais, preservando abreviações, siglas e palavras hifenizadas legítimas.
  - **Decodificação segura de Base64 e Hex**: extração de candidatos Base64 (padrão ou URL-safe, `>= 16` caracteres) e Hex (`>= 20` dígitos pares, compacto com ou sem `0x` ou espaçado por bytes) com validação estrita UTF-8 e proporção mínima de caracteres imprimíveis (`>= 0.90`). Nunca bloqueia apenas pela aparência codificada (evitando falsos positivos em hashes SHA-256 ou texto comum): o conteúdo decodificado é submetido aos padrões reais do filtro e sinalizado com `"encoded_payload:<padrao>"`.
- **Classificador semântico local (`src/agent_ops_kit/guardrails/semantic.py`)**:
  - `LocalSemanticClassifier` implementado em biblioteca padrão Python, determinístico e 100% offline, usando vetores TF-IDF L2-normalizados que combinam n-gramas de palavras (1-2 grams) e n-gramas de caracteres (3-5 grams) sobre protótipos curados PT/EN de intenções de ataque versus perguntas corporativas/técnicas benignas.
  - Exige simultaneamente que a similaridade máxima de cosseno com protótipos de ataque atinja `threshold` (padrão calibrado `0.25`) **e** que a margem sobre o melhor protótipo benigno atinja `margin` (padrão calibrado `0.08`), expondo `score(...) -> SemanticScore` e `make_local_semantic_classifier(...)`.
- **Integração em janela multi-turn e fachada (`input_filter.py`, `guardrails/__init__.py`)**:
  - `check_input` mantém assinatura retrocompatível e passa a aplicar `obfuscation=True` por padrão e `semantic_classifier` opcional.
  - `check_conversation` e `Guardrails.screen_conversation(..., window=4)` avaliam apenas turnos do usuário (ignorando turnos do assistente para não gerar auto-bloqueio em recusas) tanto isoladamente quanto em janela deslizante contígua de 2 até `window` turnos, incluindo junção de fragmentos codificados partidos entre turnos (`"multi_turn_injection"`).
  - `Guardrails` aceita `semantic_classifier` opcional e suporta a flag opcional `"semantic_filter"` em `agent.yaml` sem quebrar esquemas ou configurações existentes.

**Consequências e limitações.**
- Validação local nos testes automatizados (`tests/test_guardrails_advanced.py`) registrou **0 falsos positivos** adicionais tanto nos 50 casos de `evals/dataset.jsonl` quanto nas 12 perguntas de `redteam/benign/benign.jsonl`.
- **Limitações honestas**: o classificador TF-IDF e os decoders ainda podem ser contornados por paráfrases inéditas distantes dos protótipos, idiomas fora de PT/EN, codificações não cobertas (ex.: ROT13, cifra customizada ou múltiplas camadas aninhadas de codificação) e fragmentação além da janela configurada (`window`). Não substitui isolamento arquitetural de ferramentas nem validação de saída.

## ADR-021: suíte OWASP LLM Top 10 expandida (108 ataques, 54 benignas) e mecanismo de suíte cega externa

**Contexto.** A suíte inicial em `redteam/attacks/` reunia 40 casos em 4 categorias (`injecao_direta`, `injecao_indireta`, `abuso_de_tools`, `exfiltracao`) e 12 perguntas benignas em `redteam/benign/benign.jsonl`, todos versionados no mesmo repositório. Para ampliar a cobertura do OWASP LLM Top 10 e permitir avaliação com conjunto reservado externo sem expor prompts confidenciais em logs ou relatórios, era necessário expandir o esquema, criar conjuntos maiores retrocompatíveis e implementar o carregamento de suíte cega fora do git.

**Decisão.**
- **Expansão retrocompatível do esquema (`src/agent_ops_kit/redteam/attacks.py`)**: inclusão de 5 novas categorias em `Category` (`ofuscacao`, `multi_turn`, `saida_insegura`, `vazamento_dados`, `exaustao_recursos`), mantendo as 4 originais; adição dos campos opcionais `turns`, `owasp_id` e `is_blind` em `AttackCase` (exigindo `len(turns) >= 2` para `multi_turn`). Os conjuntos e resultados originais (`redteam/attacks/`, `redteam/benign/benign.jsonl`, `redteam/results/`) permanecem intactos.
- **Conjuntos estáticos expandidos no repositório**:
  - `redteam/attacks_owasp_100/`: 108 ataques únicos divididos em 3 arquivos JSONL (`01_injecao_direta_e_ofuscacao.jsonl`, `02_multi_turn_e_indireta.jsonl`, `03_tools_exfiltracao_e_saida.jsonl`), com 12 casos em cada uma das 9 categorias OWASP LLM Top 10.
  - `redteam/benign_expanded/benign_50.jsonl`: 54 perguntas benignas novas no esquema `EvalCase`, cobrindo os 15 documentos de `examples/rag_agent/corpus/` e abstenções legítimas sem colisão de IDs com conjuntos anteriores.
- **Suíte cega externa e sigilo estrito (`attacks.py`, `harness.py`, `report.py`, `cli.py`)**:
  - `resolve_blind_dir` e `load_blind_attacks` (`BlindSuiteResult`) leem arquivos `*.jsonl` de diretório externo indicado por `--blind-attacks-dir` ou `AOK_BLIND_ATTACKS_DIR` (aceitando `poisoned_corpus/` local quando presente), marcam `is_blind=True` e calculam `suite_sha256` determinístico sem expor conteúdo de linha em exceções ou logs. Diretórios ausentes, vazios (0 casos) ou com colisão de IDs são rejeitados.
  - Em `run_attack`, casos com múltiplos turnos em `turns` e `input_filter` ativo passam previamente por `guardrails.screen_conversation(case.turns)`.
  - Nos registros `AttackRecord` com `is_blind=True`, `final_answer`, `raw_answer`, `tool_calls` e detalhes de exceção são esvaziados/omitidos; os metadados agregados (`blind_suite_used`, `n_blind_attacks`, `blind_suite_sha256`) são gravados no sidecar `<out>.meta.json` e exibidos com aviso explícito de sigilo em `build_report` e `build_summary`.

**Consequências e limitações.**
- Em verificação determinística offline apenas da camada de entrada (`check_input` + `LocalSemanticClassifier` + `check_conversation` em `tests/test_redteam_owasp_and_blind.py`), observou-se **0/54** falsos positivos em `benign_50.jsonl` e detecção de 66/108 casos em `attacks_owasp_100` (38/108 apenas com heurísticas sem classificador semântico), com lacunas esperadas em categorias que dependem da resposta do modelo ou da allowlist de tools (`saida_insegura`, `exaustao_recursos`, `abuso_de_tools` e `injecao_indireta`).
- Medições completas de ASR ponta a ponta com o agente e modelo local na suíte de 108 ataques e 54 benignas aguardam execução com o Ollama; `docs/resultados.md` continua refletindo a execução gravada dos 40 ataques e 12 benignas originais.
- Os arquivos em `redteam/attacks_owasp_100/` são públicos no repositório; a avaliação cega efetiva depende de o operador fornecer um diretório externo fora do controle de versão via `--blind-attacks-dir` ou `AOK_BLIND_ATTACKS_DIR`.

## ADR-022: Proveniência do relatório

**Contexto.** O `relatorio.json` guardava só hashes de config, dataset, respostas e manifesto; não dizia com que versão, commit, modelo ou comando os números foram obtidos.

**Decisão.**
- O bloco `provenance` (e a seção A.7 do relatório) registra versão do kit, commit git e árvore com mudanças (só arquivos rastreados), Python, sistema operacional, modelo, digest do modelo, versão do Ollama, comando, sementes e o sha256 de cada arquivo de entrada (dataset, prompts, suítes, benignas, corpus, `agent.yaml`, respostas).
- Digest e versão do Ollama são capturados na execução (`aok eval`, `aok redteam run`, medição de falsos positivos) e gravados no manifesto do eval, em `<resultado>.meta.json` e em `fp.meta.json`; o build só lê, sem modelo.
- O manifesto passa a ter `answers_sha256`; hash divergente do manifesto, do sidecar ou da suíte é erro (código 2).
- Ficam `null` ("não registrado") digest, versão do Ollama, sementes do red team e `answers_sha256` nas execuções antigas (`evals/answers*`, `redteam/results/`), que seguem validando sem regravação. Sem git, commit e árvore ficam `null`.
- Limites: os hashes comparam texto normalizado (CRLF e LF dão o mesmo hash) e o corpus envenenado do red team não entra no hash da suíte.

## ADR-023: Política de classificação versionada

**Contexto.** O semáforo era uma regra fixa no código ("provisoria-1"): sem limiar absoluto, e `triggered` listava só ids, sem limiar nem valor observado.

**Decisão.**
- As regras passam para `policies/default.yaml` (`id`, `version`, `description`, `rules`); cada regra compara uma métrica do `relatorio.json` com um limiar (`<`, `<=`, `>`, `>=`, `==`), sem expressões livres. A política padrão reproduz exatamente a "provisoria-1" (teste de equivalência contra a implementação antiga); `--policy PATH` em `report build` e `check` usa outra.
- O `relatorio.json` registra `policy` (`id`, `version`, `sha256`, `path_relative`, regras com `observed`, `passed`, `severity`, `rationale`) e `indicators` (valores derivados que as regras consultam). Cor = pior severidade entre as regras que falharam. Métrica ausente vira "não avaliada" (`passed: null`) e nunca dá verde: a cor é, no mínimo, amarela, com a ressalva "regra não avaliada". O relatório MD/HTML ganha a tabela "Critérios de classificação".
- Política inválida é erro claro, exit 2. Limiares absolutos (média mínima do eval, limite superior de Wilson do ASR) ficam só comentados no YAML, como proposta: decisão do dono.
- Plataforma: `semaphore.color` e `triggered` continuam no mesmo formato; ela só confere a cor e não lê `policy`, então aceita relatórios antigos e novos sem mudança.

## ADR-024: Achados rastreáveis até a evidência

**Contexto.** O relatório era agregado: um auditor não conseguia ir de um número (por exemplo, "5 ataques com sucesso") até o registro que o prova.

**Decisão.**
- O `relatorio.json` ganha `findings[]` e o relatório a seção "A.8 Achados e evidências". Entram: cada ataque com sucesso e cada erro de execução do red team (`RT-<ataque>-<config>`, `RT-ERR-...`), cada pergunta benigna bloqueada (`FP-<caso>-<conjunto>`) e cada caso do eval cuja nota média caiu do baseline para o candidato (`EV-<caso>-<variante>`). Caso repetido em várias execuções ganha `-r<n>` no id.
- Cada achado traz `evidence`: `file` (relativo à raiz), `line` (linha física do JSONL, base 1), `record_sha256` (sha256 do JSON canônico da linha: chaves ordenadas, sem espaços, UTF-8), `file_sha256` (o mesmo de `provenance.sha256_file`) e `run_id`/`trace_id` quando o registro os tem (senão `null`). No eval, a evidência é o 1º registro do caso em cada variante.
- O build relê os arquivos e confere linha, hash do registro e hash do arquivo; divergência é erro (exit 2), como na proveniência.
- Severidade: tabela fixa por categoria do red team (exfiltração, vazamento de dados e abuso de tools = alta; injeção, saída insegura, multi-turn e ofuscação = média; exaustão de recursos = baixa), que reflete o impacto potencial e não é CVSS; é heurística provisória do kit, sujeita a revisão pelo dono do projeto (`SEVERITY_BY_CATEGORY` em `src/agent_ops_kit/report/findings.py`). Erros, falsos positivos, regressões do eval e categorias fora da tabela ficam "não classificado".
- Ordenação determinística (origem, config, id). Só ids, categorias, estágios, motivos (códigos), notas e hashes: nenhum texto de ataque, pergunta ou resposta. O relatório MD/HTML lista no máximo 30 achados (maior severidade primeiro); a lista completa fica no JSON.
- Correção relacionada: a seção de atribuição do relatório do red team listava só os sucessos da baseline; passa a listar também os sucessos da execução com guardrails que não tiveram sucesso na baseline. Os `.md` já versionados em `redteam/results_owasp/` não foram regenerados e seguem sem essa lista.
- Limites: regressão do eval usa a média de notas por caso (sem teste estatístico por caso: é indício, não prova); relatórios antigos sem `findings` mostram "não registrados".

## ADR-025: McNemar exato e ressalvas geradas dos dados

**Contexto.** As ressalvas estatísticas do relatório eram texto fixo ("intervalos de confiança são largos", "suíte não é reservada") e a comparação baseline vs guardrails do red team mostrava só dois ASR separados, sem teste pareado.

**Decisão.**
- `src/agent_ops_kit/report/stats.py` (sem scipy, sem modelo) calcula o teste de McNemar exato e gera as ressalvas. O `relatorio.json` ganha `redteam.mcnemar` (`applicable`, `reason`, `n_paired`, `b`, `c`, `both`, `neither`, `p_value`, `excluded` com `errors`, `unpaired` e `total`) e `redteam.n_blind_attacks`. O relatório MD/HTML mostra a tabela na seção de análise de risco; sem os dados, mostra "não registrado" (relatórios antigos) ou "não aplicável" com o motivo (uma só configuração ou nenhum par válido).
- McNemar: pareado por `attack_id` (execuções repetidas do mesmo ataque se pareiam pela ordem de ocorrência). `b` = sucesso só na baseline, `c` = sucesso só com guardrails. p exato bilateral = `min(1, 2 * P(X <= min(b, c)))`, com `X ~ Binomial(b + c, 0,5)`, calculado com inteiros; `b + c = 0` dá p = 1. Pares com erro de execução em qualquer lado, ou presentes em só um lado, são excluídos e contados. Os ASR e os IC de Wilson existentes continuam contando erro como falha do ataque (inalterados); só o McNemar exclui.
- Efeito mínimo detectável (MDE), alfa 5% bilateral e poder 80% (`z_a = 1,959964`, `z_p = 0,841621`): proporções, `(z_a + z_p) * sqrt(2 * 0,5 * 0,5 / n)`, ou seja, diferença entre dois grupos independentes de n casos no pior caso (p = 0,5; ignora o ganho do pareamento, então é conservador). Média do eval: `(z_a + z_p) / z_a * meia-largura do IC 95% bootstrap`. Aproximações para ordem de grandeza, arredondadas para cima.
- Ressalvas, em ordem fixa: (1) uma linha por medição (n, IC 95%, MDE); (2) avisos: n pequeno (n < 30), IC largo (largura > 0,20 na escala 0 a 1), p não significativo (eval e McNemar, com a frase de que isso não prova equivalência), exclusões do McNemar; (3) suíte (pública e conhecida pelo autor quando `n_blind_attacks = 0`; parcial ou total quando há ataques cegos); (4) proveniência: commits diferentes entre execuções, árvore suja nas execuções, commit não registrado e árvore suja no build. As frases fixas de tamanho do teste e de suíte foram substituídas por estas; as demais ressalvas seguem fixas. Mesma entrada, mesmo texto.
- Não muda o semáforo, a política nem nenhum número já existente.
- Limites: limiares de aviso (30 e 0,20) são heurísticos do kit; o MDE não substitui análise de poder do estudo; a suíte "cega" só é reconhecida pelo campo `is_blind` dos registros, sem metadado sobre quem a conhece.
