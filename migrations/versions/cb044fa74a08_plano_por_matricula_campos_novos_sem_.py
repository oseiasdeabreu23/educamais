"""plano por matricula: campos novos (sem drops)

Revision ID: cb044fa74a08
Revises: 3309f1526df3
Create Date: 2026-05-21 00:29:12.369536

Fase 1 do redesenho de planos de pagamento por matrícula.
Apenas adiciona colunas/índices/FKs — não dropa nada. Código continua
funcionando exatamente igual; backfill e refatoração vêm depois.
"""
from alembic import op
import sqlalchemy as sa


revision = 'cb044fa74a08'
down_revision = '3309f1526df3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('matriculas_turma', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mensalidade_padrao',
            sa.Numeric(precision=10, scale=2), nullable=True))

    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.add_column(sa.Column('matricula_turma_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_mensalidades_matricula_turma_id'),
            ['matricula_turma_id'], unique=False)
        batch_op.create_foreign_key('fk_mensalidades_matricula_turma',
            'matriculas_turma', ['matricula_turma_id'], ['id'])

    with op.batch_alter_table('planos_pagamento', schema=None) as batch_op:
        batch_op.add_column(sa.Column('matricula_turma_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('responsavel_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_planos_pagamento_matricula_turma_id'),
            ['matricula_turma_id'], unique=False)
        batch_op.create_foreign_key('fk_planos_pagamento_matricula_turma',
            'matriculas_turma', ['matricula_turma_id'], ['id'])
        batch_op.create_foreign_key('fk_planos_pagamento_responsavel',
            'responsaveis', ['responsavel_id'], ['id'])


def downgrade():
    with op.batch_alter_table('planos_pagamento', schema=None) as batch_op:
        batch_op.drop_constraint('fk_planos_pagamento_responsavel', type_='foreignkey')
        batch_op.drop_constraint('fk_planos_pagamento_matricula_turma', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_planos_pagamento_matricula_turma_id'))
        batch_op.drop_column('responsavel_id')
        batch_op.drop_column('matricula_turma_id')

    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.drop_constraint('fk_mensalidades_matricula_turma', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_mensalidades_matricula_turma_id'))
        batch_op.drop_column('matricula_turma_id')

    with op.batch_alter_table('matriculas_turma', schema=None) as batch_op:
        batch_op.drop_column('mensalidade_padrao')
