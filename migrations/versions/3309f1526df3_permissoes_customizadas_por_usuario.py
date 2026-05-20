"""permissoes customizadas por usuario

Adiciona:
- Coluna ``usuarios.permissoes_customizadas`` (Boolean default False).
- Tabela ``usuario_permissao`` (user_id, chave) — snapshot persistido
  pelo admin quando customiza as permissões de um usuário.

Quando ``User.permissoes_customizadas == True``, o RBAC consulta
``usuario_permissao`` em vez do set padrão do papel.

Idempotente: detecta se a tabela ou a coluna já existem (caso tenham
sido criadas via ``db.create_all()`` em dev) e pula.

Revision ID: 3309f1526df3
Revises: 7a3b9c4d5e6f
Create Date: 2026-05-20 02:18:35.107766

"""
from alembic import op
import sqlalchemy as sa


revision = '3309f1526df3'
down_revision = '7a3b9c4d5e6f'
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def _column_exists(bind, table, column):
    insp = sa.inspect(bind)
    return any(c['name'] == column for c in insp.get_columns(table))


def upgrade():
    bind = op.get_bind()

    # 1) Adiciona usuarios.permissoes_customizadas se ainda não existe.
    if not _column_exists(bind, 'usuarios', 'permissoes_customizadas'):
        with op.batch_alter_table('usuarios', schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                'permissoes_customizadas', sa.Boolean(),
                nullable=False, server_default='0'
            ))

    # 2) Cria usuario_permissao se ainda não existe.
    if not _table_exists(bind, 'usuario_permissao'):
        op.create_table(
            'usuario_permissao',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('chave', sa.String(length=80), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['usuarios.id'],
                                    ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_id', 'chave'),
        )


def downgrade():
    bind = op.get_bind()

    if _table_exists(bind, 'usuario_permissao'):
        op.drop_table('usuario_permissao')

    if _column_exists(bind, 'usuarios', 'permissoes_customizadas'):
        with op.batch_alter_table('usuarios', schema=None) as batch_op:
            batch_op.drop_column('permissoes_customizadas')
