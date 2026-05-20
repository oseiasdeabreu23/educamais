# Aniversariantes

Implementação em [app/services.py](../app/services.py) (`aniversariantes`) e rotas
`/admin/aniversariantes*` em [app/routes_admin.py](../app/routes_admin.py).
Templates: [app/templates/admin_aniversariantes.html](../app/templates/admin_aniversariantes.html)
+ widget no dashboard admin.

## O que mostra

`GET /admin/aniversariantes?escopo=dia|semana|mes`:
- **dia**: aniversariantes de hoje.
- **semana**: semana corrente (segunda a domingo).
- **mes**: mês corrente.

Tabela com nome, turma, data de aniversário, dia da semana, idade que faz,
telefone e botão WhatsApp com mensagem pronta. Badges "Hoje!" e "Amanhã".

Dashboard admin tem **widget compacto** que só aparece quando há aniversariantes hoje
— até 5 chips visíveis + link "ver todos".

## Critérios

- Só alunos com `status_derivado == 'ativo'` (passa pelo `_alunos_filtro_status`).
- Só alunos com `data_nascimento` preenchida.
- Usa `extract('month'/'day')` (portável SQLite + Postgres).
- Cobre 29/02 em ano não-bissexto (assume 28/02).
- Ordenado por (mes, dia, nome).

## Permissão

`aluno.ver` — admin, coordenador, gestor.
