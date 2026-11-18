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
- O slug do agente é único globalmente.
- Cada versão publicada recebe `seq` por agente; a API não tem update nem delete.

**Consequências e limitações.**
- O relatório é autodeclarado: a plataforma confere o esquema, o tamanho e o sha256 dos arquivos, mas não reexecuta eval nem red team. Quem publica pode enviar números que não vieram de uma execução real.
- A imutabilidade das versões vale só pela API: quem opera o banco ou o disco pode alterar ou apagar.
- A chave de bootstrap é única e compartilhada entre admins; não há login, papéis nem SSO na fase 2; login e papéis chegam na ADR-008.
- Estado da implantação (verificações com data; o que não foi reconfirmado está dito):
  - `docker compose` (API e postgres:16): reconfirmado localmente em 17/11/2026 no commit e76164d (build, subida, healthcheck de `db` e `api`, portal em `/`, `/v1/auth/capabilities`, cadastro admin, login por sessão, `aok check --publish`, leitura do relatório e download `md`/`html`/`json`, reinício da API com persistência nos volumes nomeados `pg_data` e `aok_data`, e `down -v`).
  - CI: os runs dos commits 0b196eb, 88dc3fc (run #20, `evidencias/03-ci-github/`), 0c8c6b8 (run #24) e 669633a (run #25, conferido em 17/11/2026) terminaram com sucesso nos três jobs em `ubuntu-latest` (`test`, onde `test_reset_recusa_link_simbolico` roda sem skip; `portal`; e `postgres`, com service container `postgres:16` rodando os 254 testes de plataforma).
  - Postgres real: verificado localmente em 17/11/2026 (commit 79f1d01) em `postgres:16` efêmero via `AOK_TEST_DATABASE_URL`: a suíte completa de plataforma (`254 passed, 0 skipped`, em 266.37s (0:04:26), incluindo `test_platform_pg_legacy.py`) passou, além de rodar no job `postgres` do CI. Os testes usam SQLite por padrão; com `AOK_TEST_DATABASE_URL`, rodam em Postgres.
  - Não verificados: carga e desempenho em Postgres; `seed_demo` dentro do container do compose (a imagem não leva os resultados gravados do repositório).
  - Dívidas: em bancos SQLite antigos a restrição UNIQUE(slug) global do agente continua; o Alembic não existe.
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
- Portal em React, Vite, TypeScript e Tailwind, servido pela própria API. O nome "Farol" é provisório e fictício (só em `platform/portal/src/brand.ts`). O visual é minimalista, em azul, com cantos arredondados (redesenho posterior ao primeiro visual, que se inspirava em um template neo-brutalista; o template foi abandonado). Substituído pelo ADR-009.
- Idioma: toda a interface (landing, login, área logada) está em inglês. O conteúdo dos relatórios vindo do backend e os nomes do seed continuam em português (limitação conhecida).
- Placeholders: Sign Up, Pricing, redes sociais e links de rodapé (Docs, Blog, Contact, Terms, Privacy) aparecem como "Soon" e não são clicáveis. Na landing, a nota do fundador é um rascunho e a fala de usuário está marcada como placeholder, não é depoimento real.

**Consequências e limitações.**
- O throttle reinicia a cada deploy, não funciona com vários workers (cada processo conta separado) e permite que terceiros travem a conta de outra pessoa por 5 minutos.
- Dívida: sem Alembic, mudança de coluna não é aplicada em banco existente; adotar migração antes disso.
- A trilha cobre só o download (as escritas administrativas passaram a ter trilha no ADR-009); não há registro de login nem de leitura.
- Não há SSO, multiempresa, dark mode nem PDF (superado em parte pelos ADR-010 e ADR-011).
- Estado do `docker compose`, do Postgres e do CI (com datas e o que não foi reconfirmado): ver o ADR-007. Dívidas: sem Alembic; UNIQUE(slug) global em bancos SQLite antigos.

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
