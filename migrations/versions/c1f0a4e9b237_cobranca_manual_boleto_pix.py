"""cobranca manual (boleto/pix) em Boleto

Revision ID: c1f0a4e9b237
Revises: b9e7f1a8d2c4
Create Date: 2026-05-09 10:00:00.000000

Adiciona campos para registrar cobranças manuais (boleto colado ou PIX
copia-e-cola) na tabela boletos. tipo_cobranca discrimina cora|boleto_manual|pix_manual.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c1f0a4e9b237'
down_revision = 'b9e7f1a8d2c4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('boletos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tipo_cobranca', sa.String(length=20),
                                      nullable=False, server_default='cora'))
        batch_op.add_column(sa.Column('linha_digitavel', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('pix_copia_cola', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('pdf_path', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('boletos', schema=None) as batch_op:
        batch_op.drop_column('pdf_path')
        batch_op.drop_column('pix_copia_cola')
        batch_op.drop_column('linha_digitavel')
        batch_op.drop_column('tipo_cobranca')
