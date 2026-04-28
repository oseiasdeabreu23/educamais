"""config_sistema

Revision ID: 08af8ecb9b2b
Revises: 668a795acdcf
Create Date: 2026-04-28 13:03:49.072407

"""
from alembic import op
import sqlalchemy as sa

revision = '08af8ecb9b2b'
down_revision = '668a795acdcf'
branch_labels = None
depends_on = None


def upgrade():
    # Tabela config_sistema já criada via db.create_all() no seed_data.py
    # Garantimos sua existência aqui para que a cadeia de revisões seja coerente
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'config_sistema' not in inspector.get_table_names():
        op.create_table(
            'config_sistema',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('nome', sa.String(length=100), nullable=False),
            sa.Column('logo_path', sa.String(length=500), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    op.drop_table('config_sistema')
