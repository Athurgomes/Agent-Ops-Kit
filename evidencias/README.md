# Evidências

Capturas de tela do agent-ops-kit em funcionamento, para ilustrar o que o projeto faz. Todos os números e textos vêm de execuções reais feitas na data abaixo; nada foi editado à mão.

- Código: commit `88dc3fc` (HEAD, `git rev-parse --short HEAD`). As saídas de terminal 01 a 04 e 06 foram geradas em `20efdd8`; a única mudança até `88dc3fc` é a remoção de uma linha (shebang) de `scripts/demo_plataforma.py`, que não afeta essas saídas. O `pytest` (05) foi reexecutado em `88dc3fc` com o mesmo resultado (596 passed, 1 skipped); o tempo mostrado na imagem é da primeira execução.
- Data das capturas: 2026-11-16, horário local (UTC-3), conforme a data de gravação dos arquivos: terminal e Jaeger às 20:09, páginas do GitHub às 20:11 (PR #2) e 20:27 (run de CI #20); portal e plataforma (pastas 04 a 10) entre 20:35 e 20:44. Nas imagens de terminal, os comandos rodaram nos minutos anteriores (o agente às 20:08) e a imagem foi renderizada às 20:09.
- Modelo local: llama3.1:8b (Ollama), com nomic-embed-text para a busca.

Aviso: as imagens de terminal são renderizações da saída real dos comandos, geradas a partir do texto capturado; as demais são capturas de tela reais de páginas em execução.

## 01-agent-kit (saídas de terminal)

Cada imagem mostra o comando, a saída e o código de saída. O `aok` não estava no PATH; os comandos foram executados com `python -m agent_ops_kit.cli`, que é equivalente.

| Imagem | O que mostra | Comando | Captura |
|---|---|---|---|
| `01-agent-kit/01-gate-eval-ab.png` | Avaliação A/B v1 vs v2 com respostas gravadas (`--reuse`): diferença de média, IC 95% e p-valor. | `aok eval --baseline v1 --candidate v2 --reuse --summary` | 2026-11-16 20:09 |
| `01-agent-kit/02-redteam-asr-resumo.png` | Taxa de sucesso de ataque (ASR) por categoria, sem e com guardrails, e falsos positivos. Só o resumo numérico; nenhum texto de ataque. | `aok redteam report --baseline redteam/results/baseline.jsonl --guardrails redteam/results/guardrails.jsonl --fp-dir redteam/results --summary` | 2026-11-16 20:09 |
| `01-agent-kit/03-auditoria-cadeia.png` | Relatório de auditoria sobre um log fictício, verificação da cadeia de hashes e detecção de adulteração (código de saída 1 no verify da cópia adulterada). Recorte das cenas 4/5 e 5/5 do roteiro. | `bash scripts/demo.sh` | 2026-11-16 20:09 |
| `01-agent-kit/04-relatorio-semaforo.png` | Pacote de relatório, linha do semáforo (regras provisórias) e arquivos gerados. | `aok report build --out ../aok-pacote-tmp` | 2026-11-16 20:09 |
| `01-agent-kit/05-testes-passando.png` | Resumo final da suíte de testes (últimas 2 linhas da saída). | `python -m pytest -q` | 2026-11-16 20:09 |
| `01-agent-kit/06-agente-resposta.png` | O agente de exemplo respondendo com o modelo local, citando a fonte. | `python -m examples.rag_agent "Quantos dias de férias a Lumina concede por ano?"` | 2026-11-16 20:09 |

Observações:

- A avaliação A/B mostra v2 com média menor que v1 (diferença -0,0933, IC 95% [-0,1933; +0,0067], p = 0,0929). É o resultado real da comparação gravada, sem ajuste.
- O `demo.sh` usa respostas gravadas e um log de auditoria fictício; não chama o modelo.
- Os números de ASR e de falsos positivos vêm de uma execução por configuração, com modelo local pequeno e dataset pequeno; ver `docs/resultados.md` para as limitações.

## 02-trace-jaeger (traces reais)

Jaeger local em http://localhost:16686, após a execução do item 06 acima (serviço `rag-agent`).

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `02-trace-jaeger/01-lista-de-traces.png` | Busca do serviço `rag-agent`: 1 trace de 17,67 s com 5 spans. | `http://localhost:16686/search?service=rag-agent&limit=20` | 2026-11-16 20:09 |
| `02-trace-jaeger/02-trace-detalhe.png` | Spans `agent.run`, `llm.call` (2), `tool.call` e `retrieval.query`, com durações. | `http://localhost:16686/trace/<id do trace>` | 2026-11-16 20:09 |

## 03-ci-github (páginas públicas, sem login)

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `03-ci-github/01-ci-tres-jobs-verdes.png` | Run #20 do workflow `ci` (commit `88dc3fc`) com Status Success e os jobs test, portal e postgres concluídos com sucesso. | https://github.com/Athurgomes/Agent-Ops-Kit/actions/runs/43978895763 | 2026-11-16 20:27 |
| `03-ci-github/02-gate-bloqueando-pr.png` | Workflow `eval` do PR #2 com o job `gate` falhando por regressão do prompt v2 (PR de teste, fechado sem mesclar). | https://github.com/Athurgomes/Agent-Ops-Kit/pull/2/checks (check `eval`) | 2026-11-16 20:11 |
| `03-ci-github/03-pr-2-conversa.png` | Conversa do PR #2: commits com marca de falha e o comentário com o resultado do gate (diferença -0,1800, p 0,0110, código 1). | https://github.com/Athurgomes/Agent-Ops-Kit/pull/2 | 2026-11-16 20:11 |

Observação: o PR #2 é um teste do mecanismo do gate (prompt degradado de propósito) e foi fechado sem mesclar.

## Portal e plataforma (pastas 04 a 10)

Capturas com o portal rodando em 127.0.0.1, sobre dados de demonstração gerados pelo seed (`aok_platform.seed_demo`): agentes, áreas e usuários fictícios (`*@demo.example`); o conteúdo dos relatórios é o do exemplo do repositório (llama3.1:8b, semente 42, uma execução por configuração). Commit do código: `5986851`. Horários em UTC-3, conferidos pela data de gravação de cada arquivo. Navegador: Edge headless (puppeteer-core), 1440x900, exceto a pasta 10 (390x844).

Como foram subidas: `scripts/demo_plataforma.py --publicar` (porta local) para as pastas 05 a 10; uma instância adicional com SMTP apontando para um Mailpit efêmero para as telas de recuperação de senha (04); uma terceira instância sem `AOK_OPS_ENABLED` para o console desligado. Tudo foi derrubado ao final. O script do repositório foi executado com a pasta de dados apontada para uma pasta temporária (a pasta padrão `.demo/` estava em uso por outra instância); o resto do roteiro é o do script.

Segredos mascarados por edição do DOM antes da captura (o valor real nunca aparece na imagem): o token do link do e-mail (04/07), o token emitido ao agente e o trecho de exemplo com o token (07/04 e 09/01, a mesma imagem), a senha gerada ao redefinir a senha de um usuário (07/06) e a senha inicial do admin criado no console do operador (08/04). Os campos de senha digitados aparecem como pontos. Nenhuma senha, token ou chave foi gravada no repositório; os arquivos temporários com credenciais foram apagados.

### 04-portal-publico

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `04-portal-publico/01-landing-hero.png` | Página inicial, primeira dobra (1440x900). | `/` | 2026-11-16 20:35 |
| `04-portal-publico/02-landing-completa.png` | Página inicial inteira. | `/` | 2026-11-16 20:35 |
| `04-portal-publico/03-landing-faq.png` | Seção de perguntas frequentes. | `/#faq` | 2026-11-16 20:37 |
| `04-portal-publico/04-login.png` | Tela de login. | `/login` | 2026-11-16 20:35 |
| `04-portal-publico/05-login-recuperar-senha.png` | Login com o link "Forgot password?" ativo (só aparece com SMTP configurado). | `/login` | 2026-11-16 20:35 |
| `04-portal-publico/06-recuperar-senha-pedido.png` | Pedido de recuperação enviado: a resposta é a mesma exista ou não a conta. | `/forgot-password` | 2026-11-16 20:35 |
| `04-portal-publico/07-email-recebido.png` | E-mail de redefinição no Mailpit (aba Text); token do link mascarado. | Mailpit local, porta 8025 | 2026-11-16 20:38 |
| `04-portal-publico/08-nova-senha.png` | Tela de nova senha com os campos preenchidos (pontos); o formulário não foi enviado. | `/reset-password#token=...` | 2026-11-16 20:37 |

### 05-portal-consumo (entrada como operacoes@demo.example)

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `05-portal-consumo/01-areas.png` | Áreas visíveis para o usuário. | `/app` | 2026-11-16 20:40 |
| `05-portal-consumo/02-agentes-da-area.png` | Agentes (e sub-áreas) da área Operações. | `/app/areas/1` | 2026-11-16 20:40 |
| `05-portal-consumo/03-relatorios-do-agente.png` | Versões publicadas do agente; a mais recente em destaque (versão 3, antes da publicação da pasta 09). | `/app/areas/1/agents/1` | 2026-11-16 20:40 |
| `05-portal-consumo/04-relatorio-detalhe.png` | Relatório: semáforo, resumo, ressalvas e o texto fixo "Green does not mean safe...". | `/app/reports/7` | 2026-11-16 20:40 |
| `05-portal-consumo/05-meus-downloads.png` | Histórico depois de baixar de fato 2 arquivos (MD e HTML), com "Downloaded at" e "Report generated at". | `/app/downloads` | 2026-11-16 20:40 |

### 06-visao-por-perfil

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `06-visao-por-perfil/01-viewer-operacoes-so-sua-area.png` | Viewer de Operações: só a própria área e a sub-área (mesma tela da 05/02, mesmo usuário). | `/app/areas/1` | 2026-11-16 20:40 |
| `06-visao-por-perfil/02-viewer-financas-so-sua-area.png` | Viewer de Finanças: só a própria área. | `/app` | 2026-11-16 20:40 |
| `06-visao-por-perfil/03-admin-ve-tudo.png` | admin@demo.example: todas as áreas e o menu de administração. | `/app` | 2026-11-16 20:40 |

### 07-administracao-sec (entrada como admin@demo.example)

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `07-administracao-sec/01-areas.png` | Administração de áreas. | `/app/admin/areas` | 2026-11-16 20:41 |
| `07-administracao-sec/02-agentes.png` | Administração de agentes. | `/app/admin/agents` | 2026-11-16 20:41 |
| `07-administracao-sec/03-agente-detalhe.png` | Detalhe do agente e seus tokens. | `/app/admin/agents/<id>` | 2026-11-16 20:41 |
| `07-administracao-sec/04-token-emitido.png` | Token recém-emitido (valor e trecho de exemplo mascarados). | `/app/admin/agents/<id>` | 2026-11-16 20:41 |
| `07-administracao-sec/05-usuarios.png` | Lista de usuários e acessos. | `/app/admin/users` | 2026-11-16 20:41 |
| `07-administracao-sec/06-senha-gerada.png` | Senha gerada ao redefinir um usuário (valor mascarado). | `/app/admin/users` | 2026-11-16 20:41 |
| `07-administracao-sec/07-atividade.png` | Registro de atividade administrativa. | `/app/admin/activity` | 2026-11-16 20:41 |
| `07-administracao-sec/08-todos-os-downloads.png` | Downloads de toda a organização. | `/app/admin/downloads` | 2026-11-16 20:41 |

### 08-console-operador (ops@demo.example)

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `08-console-operador/01-login.png` | Login do console do operador. | `/ops/login` | 2026-11-16 20:43 |
| `08-console-operador/02-organizacoes.png` | Lista de organizações. | `/ops/organizations` | 2026-11-16 20:43 |
| `08-console-operador/03-detalhe-organizacao.png` | Detalhe de uma organização, com a nota "metadata only" (só metadados, sem conteúdo de relatório). | `/ops/organizations/1` | 2026-11-16 20:43 |
| `08-console-operador/04-criar-admin-senha-mascarada.png` | Criação de um admin na organização beta; senha inicial mascarada. | `/ops/organizations/2` | 2026-11-16 20:43 |
| `08-console-operador/05-atividade.png` | Atividade da plataforma. | `/ops/activity` | 2026-11-16 20:43 |
| `08-console-operador/06-console-desligado-404.png` | Instância sem `AOK_OPS_ENABLED`: /ops/login mostra a página 404 comum. | /ops/login (outra instância) | 2026-11-16 20:42 |

### 09-fluxo-emissao-relatorio

Sequência real: o admin emite o token, o time publica com `aok check --publish`, a versão nova aparece no portal e, depois de revogar o token na tela, o mesmo comando é recusado. As imagens de terminal mostram o comando com `AOK_PLATFORM_TOKEN=***` (o valor não aparece) e a saída real, sem edição; o código de saída está na imagem (0 e 2). O `aok` não estava no PATH; foi executado com `python -m agent_ops_kit.cli`, equivalente.

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `09-fluxo-emissao-relatorio/01-token-emitido.png` | Mesma captura mascarada de 07/04. | `/app/admin/agents/<id>` | 2026-11-16 20:41 |
| `09-fluxo-emissao-relatorio/02-aok-check-publish.png` | Publicação pelo kit: "Publicado na plataforma como versão 4". | `aok check --config examples/rag_agent/agent.yaml --publish http://127.0.0.1:<porta> --agent-id assistente-politicas` | 2026-11-16 20:41 |
| `09-fluxo-emissao-relatorio/03-relatorio-aparece-no-portal.png` | A versão 4 em destaque na lista do agente (como operacoes@demo.example). | `/app/areas/1/agents/1` | 2026-11-16 20:41 |
| `09-fluxo-emissao-relatorio/04-token-revogado-401.png` | Mesmo comando depois de "Revoke": recusado ("token recusado (ausente, inválido ou revogado)"), código de saída 2. O nome do arquivo diz 401, mas a saída do kit não mostra o número do status. | mesmo comando | 2026-11-16 20:41 |

### 10-mobile (viewport 390x844)

| Imagem | O que mostra | URL | Captura |
|---|---|---|---|
| `10-mobile/01-landing.png` | Página inicial. | `/` | 2026-11-16 20:40 |
| `10-mobile/02-login.png` | Login. | `/login` | 2026-11-16 20:40 |
| `10-mobile/03-relatorio-detalhe.png` | Relatório inteiro (página longa; escala 1,5x, cerca de 510 KB). | `/app/reports/7` | 2026-11-16 20:44 |
| `10-mobile/04-menu.png` | Menu aberto na página inicial. | `/` | 2026-11-16 20:40 |

Limitações: as duas imagens de Operações (05/02 e 06/01) têm o mesmo conteúdo (mesmo usuário e página). As capturas do portal vêm de uma única sessão de demonstração; as horas exibidas dentro das telas são as do momento do seed.
