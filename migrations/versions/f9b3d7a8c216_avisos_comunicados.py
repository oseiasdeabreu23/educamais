"""sistema de avisos/comunicados internos

Revision ID: f9b3d7a8c216
Revises: a8c2d3f4e591
Create Date: 2026-05-16 09:00:00.000000

Adiciona:
- `avisos`: comunicados criados pelo admin (titulo, mensagem, nivel,
  escopo global|por_papel|por_usuario, alvo CSV, expira_em, ativo).
- `aviso_leituras`: registro por usuário (entendi | lembrar_depois +
  lembrete_para). Unique por (aviso_id, usuario_id).
"""
from alembic import op
import sqlalchemy as sa


revision = 'f9b3d7a8c216'
down_revision = 'a8c2d3f4e591'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'avisos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('titulo', sa.String(length=200), nullable=False),
        sa.Column('mensagem', sa.Text(), nullable=False),
        sa.Column('nivel', sa.String(length=20), nullable=False,
                  server_default='info'),
        sa.Column('escopo', sa.String(length=20), nullable=False,
                  server_default='global'),
        sa.Column('papeis_alvo', sa.String(length=200), nullable=True),
        sa.Column('usuarios_alvo', sa.String(length=500), nullable=True),
        sa.Column('criado_por_id', sa.Integer(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('expira_em', sa.DateTime(), nullable=True),
        sa.Column('ativo', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.ForeignKeyConstraint(['criado_por_id'], ['usuarios.id'],
                                name='fk_aviso_criado_por'),
    )

    op.create_table(
        'aviso_leituras',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aviso_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='entendi'),
        sa.Column('atualizado_em', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('lembrete_para', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['aviso_id'], ['avisos.id'],
                                name='fk_leitura_aviso',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'],
                                name='fk_leitura_usuario'),
        sa.UniqueConstraint('aviso_id', 'usuario_id', name='uq_aviso_leitura'),
    )


def downgrade():
    op.drop_table('aviso_leituras')
    op.drop_table('avisos')
