# Práticas de Desenvolvimento de Software

Este guia reúne as práticas de engenharia adotadas pelos times de produto da Lumina Tecnologia. O responsável pelas práticas é o time de Engenharia de Plataforma.

## Código e revisão

Todo código passa por pull request com no mínimo 2 aprovações antes do merge na branch main. O prazo esperado para a primeira revisão é de 1 dia útil. Pull requests devem ter no máximo 400 linhas alteradas, sempre que possível. Commits seguem o padrão Conventional Commits.

## Testes e qualidade

A cobertura mínima de testes é de 80% para código novo. O pipeline de CI roda testes, lint e verificação de segurança, e deve terminar em até 15 minutos. Merge só é permitido com o pipeline verde.

## Deploy

Os deploys em produção acontecem de segunda a quinta-feira, até as 16h. Deploys às sextas-feiras são proibidos, exceto correções de SEV1. Todo deploy usa estratégia canário, com 10% do tráfego por 30 minutos antes da liberação total. O rollback deve levar menos de 10 minutos.

## Linguagens e ferramentas

As linguagens padrão são Python 3.11 para serviços de dados e TypeScript para o front-end. O repositório de código fica no GitLab interno e os containers rodam em Kubernetes.

## Dívida técnica

Cada time reserva 20% da capacidade de cada sprint para dívida técnica. As sprints duram 2 semanas e começam sempre às segundas-feiras.
