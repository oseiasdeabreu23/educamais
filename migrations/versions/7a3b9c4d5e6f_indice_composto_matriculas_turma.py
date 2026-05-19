"""indice composto (aluno_id, status) em matriculas_turma

O padrão de consulta dominante após o redesenho de matrículas é
``WHERE aluno_id = ? AND status = 'ativo'`` (usado por
``_aluno_ativo_clausula``, properties derivadas em ``Aluno`` e por todos
os filtros de "ativo" em services.py). Sem este índice composto, o
Postgres filtra por aluno_id usando ix_matriculas_turma_aluno_id e
depois reavalia o status linha a linha.

Idempotente: testa existência antes de criar/dropar.

Revision ID: 7a3b9c4d5e6f
Revises: 416ed464ea47
Create Date: 2026-05-19 11:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '7a3b9c4d5e6f'
down_revision = '416ed464ea47'
branch_labels = None
depends_on = None


def _index_exists(bind, table, index_name):
    insp = sa.inspect(bind)
    return any(ix['name'] == index_name for ix in insp.get_indexes(table))


def upgrade():
    bind = op.get_bind()
    if not _index_exists(bind, 'matriculas_turma',
                         'ix_matriculas_turma_aluno_id_status'):
        op.create_index(
            'ix_matriculas_turma_aluno_id_status',
            'matriculas_turma',
            ['aluno_id', 'status'],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    if _index_exists(bind, 'matriculas_turma',
                     'ix_matriculas_turma_aluno_id_status'):
        op.drop_index('ix_matriculas_turma_aluno_id_status',
                      table_name='matriculas_turma')
