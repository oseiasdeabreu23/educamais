# Matrículas em turma (multi-vínculo + histórico)

Adicionado em **2026-05-19** pra suportar alunos cursando múltiplas turmas
simultaneamente e manter histórico de turmas anteriores (formado/evadido/transferido).

Implementação:
- Modelo [app/models.py](../app/models.py) → `MatriculaTurma`.
- Properties derivadas em `Aluno`.
- Helpers em [app/services.py](../app/services.py).
- Rotas + UI em [app/routes_admin.py](../app/routes_admin.py) e
  [app/templates/admin_aluno_vinculos.html](../app/templates/admin_aluno_vinculos.html).
- Migration [migrations/versions/416ed464ea47_matriculas_turma_com_historico_de_.py](../migrations/versions/416ed464ea47_matriculas_turma_com_historico_de_.py).

## Modelo de dados

```python
class MatriculaTurma(db.Model):
    id, aluno_id, turma_id
    status: 'ativo' | 'formado' | 'evadido' | 'transferido'
    data_matricula (default=today), data_saida (nullable), observacao
```

**Sem unique composto** por design. Mesmo aluno em "Catequese 2026" e
"Catequese 2027" são duas matrículas distintas (turmas diferentes). Mesmo aluno
**reentrando** numa turma onde já formou/evadiu também cria nova matrícula — o
histórico de cada "passagem" fica preservado independentemente. A validação de
"não duplicar" só impede 2 matrículas **ativas** simultâneas no mesmo par
(aluno, turma) — checada por `services.matricular_em_turma`.

## Status derivado

`Aluno.status_derivado` é a fonte da verdade. Calcula:
1. `ativo` se existe `MatriculaTurma(status='ativo')` para o aluno;
2. senão, status da matrícula mais recente (`vinculos_historico[0].status`);
3. senão, fallback pra `Aluno.status` legacy (alunos antigos sem matrícula);
4. senão, `'sem_vinculo'`.

Todos os filtros do sistema (`_alunos_filtro_status`, `query_alunos_ativos_na_turma`,
filtro da listagem `/admin/alunos`, etc) usam `_aluno_ativo_clausula()`, que expressa
o mesmo critério como SQL `EXISTS` + `OR` pra fallback legacy.

## Backfill + compat

A migration `416ed464ea47` é **idempotente** (criamos a tabela com check
`IF NOT EXISTS` porque ela pode já existir via `db.create_all()` em dev).
O backfill cria uma `MatriculaTurma` pra cada `Aluno` com `turma_id != None`,
usando `Aluno.status` como status inicial. Backfill só roda se a tabela estiver
vazia (segurança).

Campos legacy mantidos:
- `Aluno.turma_id` — sincronizado com a "primeira turma ativa" na criação.
  Lido por código antigo (templates `aluno.turma.nome`, etc).
- `Aluno.status` — ainda editável pelo form de edição. Quando muda para `evadido`,
  o `editar_aluno` chama `cancelar_plano_aluno` (wrapper agregado, idempotente —
  cancela planos de todas as matrículas + planos legacy).

## Rotas

- `GET /admin/alunos/<id>/vinculos` — página dedicada com tabela de vínculos
  ativos + histórico + form "Nova matrícula".
- `POST /admin/alunos/<id>/vinculos` — ações: `matricular`, `formar`, `evadir`,
  `transferir`. Cada ação encerrante aceita `data_saida` e `observacao`.
- Form `/admin/alunos` (criação): checkboxes `name="turma_ids"` criam N matrículas
  via `_matricular_turmas_iniciais`.
- Filtro `/admin/alunos?status=ativo|evadido|formado|transferido` usa subqueries
  `EXISTS` sobre `MatriculaTurma`.

## Cascade financeiro (atualizado 2026-05-21)

Cada matrícula carrega seu próprio plano de pagamento — multi-plano por matrícula
(ver [financeiro.md](financeiro.md)). O cascade é granular:

- **Evadir uma matrícula específica** (em `/admin/alunos/<id>/vinculos`): cancela
  só o plano daquela matrícula via `cancelar_plano_matricula(matricula)`. Outras
  matrículas ativas do aluno continuam com seus planos intactos.
- **Mudar `Aluno.status` legacy para `evadido`** (form principal de edição) ou
  **excluir aluno**: chama `cancelar_plano_aluno(aluno)` (wrapper agregado) que
  itera todas as matrículas + cobre planos legacy sem `matricula_turma_id`.

Todas as funções de cancelamento são **idempotentes** — as duas rotas coexistem
sem duplicar cancelamento.

## Limitações conhecidas

- `Aluno.turma_id` legacy ainda existe — fase 5 do redesenho remove
  (item 8 da seção *O que ainda NÃO foi feito* no CLAUDE.md).
- Formar/Evadir/Transferir não notifica responsáveis automaticamente.
