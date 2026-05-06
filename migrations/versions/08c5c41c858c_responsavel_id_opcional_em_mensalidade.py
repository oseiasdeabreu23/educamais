"""responsavel_id opcional em mensalidade

Revision ID: 08c5c41c858c
Revises: 3e50c172930f
Create Date: 2026-05-04 01:25:39.932458

"""
from alembic import op
import sqlalchemy as sa


revision = '08c5c41c858c'
down_revision = '3e50c172930f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.alter_column(
            'responsavel_id',
            existing_type=sa.INTEGER(),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table('mensalidades', schema=None) as batch_op:
        batch_op.alter_column(
            'responsavel_id',
            existing_type=sa.INTEGER(),
            nullable=False,
        )
