# Relatórios

Implementação em [app/services_relatorios.py](../app/services_relatorios.py),
[app/services_export.py](../app/services_export.py) (função `relatorio_status_pdf`)
e rotas `/admin/relatorios*` em [app/routes_admin.py](../app/routes_admin.py).
Template: [app/templates/admin_relatorios.html](../app/templates/admin_relatorios.html).

## O que mostra

- **4 KPIs**: ativos, formados, evadidos (com taxa de evasão como sub), cadastros totais.
- **Donut** (Chart.js): distribuição atual por status.
- **Barras empilhadas** (Chart.js): matrículas por turma (ativo/formado/evadido/transferido).
- **Linha temporal** (Chart.js): saídas por ano usando `data_saida` das matrículas
  encerradas.
- **Tabela**: detalhamento por turma com mesmos dados das barras.

## Filtros

`?turma_id=<id>` restringe o detalhamento por turma (KPIs e histórico continuam
globais — fazem mais sentido sem filtro).

## Exportação PDF

`GET /admin/relatorios/pdf?turma_id=<id>` baixa PDF com KPIs + tabelas. Implementado
em `services_export.relatorio_status_pdf` usando reportlab. **Sem gráficos** — adicionar
exigiria matplotlib (decisão consciente pra evitar nova dependência).

## Permissão

`relatorio.ver` — admin (via `*`), coordenador e gestor.

## Portabilidade SQL

`historico_anual` usa `extract('year', ...)` em vez de `strftime('%Y', ...)` pra
funcionar tanto em SQLite (dev) quanto Postgres (prod no Supabase).
