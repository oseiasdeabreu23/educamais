"""area_aluno_e_cursos

Revision ID: 668a795acdcf
Revises:
Create Date: 2026-04-28 12:40:05.775994

"""
from alembic import op
import sqlalchemy as sa


revision = '668a795acdcf'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Adiciona user_id à tabela alunos (FK para usuarios)
    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_aluno_user_id', ['user_id'])
        batch_op.create_foreign_key('fk_aluno_user', 'usuarios', ['user_id'], ['id'])

    # As tabelas cursos, modulos, videoaulas, matriculas_curso e progresso_videoaulas
    # foram criadas via db.create_all() antes desta migration.
    # Não há nada mais a fazer aqui.


def downgrade():
    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_aluno_user', type_='foreignkey')
        batch_op.drop_constraint('uq_aluno_user_id', type_='unique')
        batch_op.drop_column('user_id')
