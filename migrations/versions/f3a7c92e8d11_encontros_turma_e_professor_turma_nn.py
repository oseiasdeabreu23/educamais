"""encontros da turma + N:N professor x turma

Revision ID: f3a7c92e8d11
Revises: d4a2b8e6f193
Create Date: 2026-05-11 09:00:00.000000

Adiciona:
- `encontros_turma`: datas de aula previstas por turma, configuradas pelo
  admin no cadastro da turma. Alimenta o seletor de data na frequência.
- `professor_turma`: associação N:N para que um professor possa lecionar
  em várias turmas. Popula com o turma_id legado de cada professor.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a7c92e8d11'
down_revision = 'd4a2b8e6f193'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'encontros_turma',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('ordem', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('criado_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id'],
                                name='fk_encontros_turma_id'),
        sa.UniqueConstraint('turma_id', 'data', name='uq_encontro_turma_data'),
    )

    op.create_table(
        'professor_turma',
        sa.Column('professor_id', sa.Integer(), nullable=True),
        sa.Column('turma_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['professor_id'], ['professores.id'],
                                name='fk_prof_turma_prof'),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id'],
                                name='fk_prof_turma_turma'),
    )

    # Popular professor_turma com os vínculos atuais (campo Professor.turma_id)
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO professor_turma (professor_id, turma_id) "
        "SELECT id, turma_id FROM professores WHERE turma_id IS NOT NULL"
    ))


def downgrade():
    op.drop_table('professor_turma')
    op.drop_table('encontros_turma')
