"""cora mock state no banco (cora_mock_boletos + cora_mock_movimentacoes)

Revision ID: b9e7f1a8d2c4
Revises: 08c5c41c858c
Create Date: 2026-05-06 12:00:00.000000

Move o estado do CoraMockClient do filesystem (instance/cora_mock.json)
pra duas tabelas no banco — necessário pra rodar em serverless (Vercel)
sem perder o mock entre invocações.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b9e7f1a8d2c4'
down_revision = '08c5c41c858c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cora_mock_boletos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cora_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='aberto'),
        sa.Column('valor', sa.Numeric(10, 2), nullable=False),
        sa.Column('vencimento', sa.Date(), nullable=False),
        sa.Column('pagador', sa.JSON(), nullable=True),
        sa.Column('descricao', sa.Text(), nullable=True),
        sa.Column('emitido_em', sa.DateTime(), nullable=True),
        sa.Column('pago_em', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('cora_id', name='uq_cora_mock_boleto_cora_id'),
    )
    op.create_index('ix_cora_mock_boletos_cora_id', 'cora_mock_boletos', ['cora_id'])

    op.create_table(
        'cora_mock_movimentacoes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('mov_id', sa.String(64), nullable=False),
        sa.Column('tipo', sa.String(10), nullable=False),
        sa.Column('valor', sa.Numeric(10, 2), nullable=False),
        sa.Column('descricao', sa.String(300), nullable=True),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('cora_boleto_id', sa.String(64), nullable=True),
        sa.UniqueConstraint('mov_id', name='uq_cora_mock_mov_id'),
    )


def downgrade():
    op.drop_table('cora_mock_movimentacoes')
    op.drop_index('ix_cora_mock_boletos_cora_id', table_name='cora_mock_boletos')
    op.drop_table('cora_mock_boletos')
