"""matriculas_turma com historico de vinculo aluno-turma

Cria a tabela matriculas_turma e faz backfill a partir de Aluno.turma_id
(cada aluno com turma_id ganha uma matrícula com o status atual).

Idempotente: detecta se a tabela já existe (caso tenha sido criada via
db.create_all() em dev) e pula a criação; o backfill só roda se a tabela
estiver vazia.

Aluno.turma_id e Aluno.status permanecem por compat (fase 1) — serão
removidos numa migration futura quando todo o código tiver migrado.

Revision ID: 416ed464ea47
Revises: f9b3d7a8c216
Create Date: 2026-05-19 00:43:17.783537

"""
from alembic import op
import sqlalchemy as sa
from datetime import date


revision = '416ed464ea47'
down_revision = 'f9b3d7a8c216'
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def _index_exists(bind, table, index_name):
    insp = sa.inspect(bind)
    return any(ix['name'] == index_name for ix in insp.get_indexes(table))


def upgrade():
    bind = op.get_bind()

    if not _table_exists(bind, 'matriculas_turma'):
        op.create_table(
            'matriculas_turma',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('aluno_id', sa.Integer(), nullable=False),
            sa.Column('turma_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False,
                      server_default='ativo'),
            sa.Column('data_matricula', sa.Date(), nullable=False),
            sa.Column('data_saida', sa.Date(), nullable=True),
            sa.Column('observacao', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id'], ),
            sa.ForeignKeyConstraint(['turma_id'], ['turmas.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _index_exists(bind, 'matriculas_turma', 'ix_matriculas_turma_aluno_id'):
        op.create_index('ix_matriculas_turma_aluno_id', 'matriculas_turma',
                        ['aluno_id'], unique=False)
    if not _index_exists(bind, 'matriculas_turma', 'ix_matriculas_turma_turma_id'):
        op.create_index('ix_matriculas_turma_turma_id', 'matriculas_turma',
                        ['turma_id'], unique=False)

    # ── Backfill ──────────────────────────────────────────────────────────
    # Só roda se a tabela estiver vazia. Pra cada aluno com turma_id, cria
    # uma MatriculaTurma refletindo o status global atual. Aluno sem
    # turma_id não recebe matrícula — entrará pelo formulário novo na fase 2.
    count = bind.execute(sa.text(
        'SELECT COUNT(*) FROM matriculas_turma'
    )).scalar()
    if count == 0:
        hoje = date.today().isoformat()
        bind.execute(sa.text("""
            INSERT INTO matriculas_turma
                (aluno_id, turma_id, status, data_matricula, data_saida, observacao)
            SELECT
                a.id,
                a.turma_id,
                COALESCE(a.status, 'ativo'),
                :hoje,
                CASE
                    WHEN COALESCE(a.status, 'ativo') = 'ativo' THEN NULL
                    ELSE :hoje
                END,
                'Backfill da migration 416ed464ea47'
            FROM alunos a
            WHERE a.turma_id IS NOT NULL
        """), {'hoje': hoje})


def downgrade():
    bind = op.get_bind()
    if _index_exists(bind, 'matriculas_turma', 'ix_matriculas_turma_turma_id'):
        op.drop_index('ix_matriculas_turma_turma_id', table_name='matriculas_turma')
    if _index_exists(bind, 'matriculas_turma', 'ix_matriculas_turma_aluno_id'):
        op.drop_index('ix_matriculas_turma_aluno_id', table_name='matriculas_turma')
    if _table_exists(bind, 'matriculas_turma'):
        op.drop_table('matriculas_turma')
