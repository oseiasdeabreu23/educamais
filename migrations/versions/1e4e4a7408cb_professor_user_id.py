"""professor.user_id

Revision ID: 1e4e4a7408cb
Revises: 08af8ecb9b2b
Create Date: 2026-05-01 17:12:07.311445

"""
from alembic import op
import sqlalchemy as sa


revision = '1e4e4a7408cb'
down_revision = '08af8ecb9b2b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('professores', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_professores_user_id', ['user_id'])
        batch_op.create_foreign_key(
            'fk_professores_user_id_usuarios', 'usuarios', ['user_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('professores', schema=None) as batch_op:
        batch_op.drop_constraint('fk_professores_user_id_usuarios', type_='foreignkey')
        batch_op.drop_constraint('uq_professores_user_id', type_='unique')
        batch_op.drop_column('user_id')
