"""plano de pagamento + cancelada_em em mensalidade

Revision ID: 3e50c172930f
Revises: 2990bdef0157
Create Date: 2026-05-04 01:10:22.566344

"""
from alembic import op
import sqlalchemy as sa


revision = '3e50c172930f'
down_revision = '2990bdef0157'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'planos_pagamento',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.Column('n_parcelas', sa.Integer(), nullable=False),
        sa.Column('valor_parcela', sa.Numeric(10, 2), nullable=False),
        sa.Column('dia_vencimento', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('data_primeira', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ativo'),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=True),
        sa.Column('cancelado_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id'], name='fk_planos_aluno'),
    )

    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plano_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cancelada_em', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            'fk_mensalidade_plano', 'planos_pagamento',
            ['plano_id'], ['id'],
        )


def downgrade():
    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.drop_constraint('fk_mensalidade_plano', type_='foreignkey')
        batch_op.drop_column('cancelada_em')
        batch_op.drop_column('plano_id')

    op.drop_table('planos_pagamento')
