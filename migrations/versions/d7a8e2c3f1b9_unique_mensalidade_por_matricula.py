"""unique mensalidade por matricula (drop aluno+mes+ano, add matricula+mes+ano)

Revision ID: d7a8e2c3f1b9
Revises: cb044fa74a08
Create Date: 2026-05-21 01:30:00.000000

Permite múltiplos planos/mensalidades em paralelo no mesmo mês quando o aluno
tem mais de uma matrícula ativa (uma por turma).
"""
from alembic import op


revision = 'd7a8e2c3f1b9'
down_revision = 'cb044fa74a08'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.drop_constraint('uq_mensalidade_aluno_mes_ano', type_='unique')
        batch_op.create_unique_constraint(
            'uq_mensalidade_matricula_mes_ano',
            ['matricula_turma_id', 'mes', 'ano'],
        )


def downgrade():
    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.drop_constraint('uq_mensalidade_matricula_mes_ano', type_='unique')
        batch_op.create_unique_constraint(
            'uq_mensalidade_aluno_mes_ano',
            ['aluno_id', 'mes', 'ano'],
        )
