"""config_licenca singleton

Revision ID: a8c2d3f4e591
Revises: e7b91d8f2c45
Create Date: 2026-05-11 11:00:00.000000

Cria tabela singleton ``config_licenca`` que move a configuração do
Painel de Licenças (api_key, documento, tipo_cliente, modo) das envs
para a UI em ``/admin/licenca``. As demais envs (URL, cache, grace)
continuam técnicas e não expostas.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a8c2d3f4e591'
down_revision = 'e7b91d8f2c45'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotente: a tabela pode já existir se o ``run.py`` rodou
    # ``db.create_all()`` em dev antes da migration ser aplicada
    # (mesmo padrão da migration 08af8ecb9b2b/config_sistema).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'config_licenca' in inspector.get_table_names():
        return
    op.create_table(
        'config_licenca',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('api_key', sa.Text(), nullable=True),
        sa.Column('documento', sa.String(length=20), nullable=True),
        sa.Column('tipo_cliente', sa.String(length=30), nullable=True),
        sa.Column('modo', sa.String(length=20), nullable=False,
                  server_default='bloqueio'),
        sa.Column('atualizado_em', sa.DateTime(), nullable=True),
        sa.Column('atualizado_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['atualizado_por_id'], ['usuarios.id'],
                                name='fk_config_licenca_user'),
    )


def downgrade():
    op.drop_table('config_licenca')
