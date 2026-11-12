# Gestão de Incidentes de Produção

Este documento descreve como a Lumina Tecnologia trata incidentes que afetam o produto em produção. O processo é coordenado pelo time de Engenharia de Plataforma.

## Severidades

- SEV1: indisponibilidade total ou perda de dados. Aciona o plantão imediatamente.
- SEV2: degradação relevante para parte dos clientes.
- SEV3: falha pontual sem impacto amplo.

## Papéis

Em todo incidente SEV1 ou SEV2 é designado um Comandante do Incidente (IC), que coordena a resposta. Um segundo profissional atua como Comunicador, responsável por atualizar a página de status a cada 30 minutos durante um SEV1.

## Plantão

O plantão funciona em escala semanal, com troca todas as segundas-feiras às 10h. Cada escala tem 2 pessoas: um principal e um reserva. O plantonista deve reconhecer o alerta em até 10 minutos. Se não reconhecer, o alerta passa ao reserva e depois ao gerente de Engenharia, Henrique Moura. O plantão é remunerado com adicional de R$ 700,00 por semana.

## Pós-incidente

Todo SEV1 exige um post-mortem sem culpados, publicado em até 5 dias úteis. O documento deve conter linha do tempo, causa raiz, impacto e ações corretivas com responsável e prazo. Os post-mortems ficam no repositório interno "incidentes" e são revisados na reunião mensal de confiabilidade, toda primeira quinta-feira do mês.

## Ferramentas

Alertas via PagerLumina e comunicação no canal #incidentes.
