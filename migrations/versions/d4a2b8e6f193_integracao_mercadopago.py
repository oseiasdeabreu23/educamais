"""integracao mercadopago + mp_payment_id em boletos

Revision ID: d4a2b8e6f193
Revises: c1f0a4e9b237
Create Date: 2026-05-09 11:30:00.000000

Cria tabela singleton integracao_mercadopago com credenciais do MP e
adiciona coluna mp_payment_id em boletos para casar com o webhook do MP.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4a2b8e6f193'
down_revision = 'c1f0a4e9b237'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'integracao_mercadopago',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('ambiente', sa.String(length=20), nullable=False,
                  server_default='production'),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('webhook_secret', sa.String(length=200), nullable=True),
        sa.Column('notification_url', sa.String(length=500), nullable=True),
        sa.Column('atualizado_em', sa.DateTime(), nullable=True),
        sa.Column('atualizado_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['atualizado_por_id'], ['usuarios.id'],
                                name='fk_integ_mp_user'),
    )

    with op.batch_alter_table('boletos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mp_payment_id', sa.String(length=100),
                                      nullable=True))
        batch_op.create_index('ix_boletos_mp_payment_id', ['mp_payment_id'])


def downgrade():
    with op.batch_alter_table('boletos', schema=None) as batch_op:
        batch_op.drop_index('ix_boletos_mp_payment_id')
        batch_op.drop_column('mp_payment_id')

    op.drop_table('integracao_mercadopago')
