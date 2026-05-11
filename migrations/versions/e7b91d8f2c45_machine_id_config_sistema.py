"""machine_id em config_sistema

Revision ID: e7b91d8f2c45
Revises: f3a7c92e8d11
Create Date: 2026-05-11 10:00:00.000000

Adiciona coluna ``machine_id`` em config_sistema (singleton) usada pela
integração com o Painel de Licenças. Em Postgres (Vercel) é onde mora o
identificador da instância — em SQLite dev usamos arquivo em ``instance/``.
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7b91d8f2c45'
down_revision = 'f3a7c92e8d11'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('config_sistema', schema=None) as batch_op:
        batch_op.add_column(sa.Column('machine_id', sa.String(length=64),
                                      nullable=True))


def downgrade():
    with op.batch_alter_table('config_sistema', schema=None) as batch_op:
        batch_op.drop_column('machine_id')
