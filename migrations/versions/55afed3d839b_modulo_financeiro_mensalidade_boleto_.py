"""modulo financeiro: mensalidade, boleto, movimentacao, categoria_despesa

Revision ID: 55afed3d839b
Revises: 1e4e4a7408cb
Create Date: 2026-05-03 23:25:12.879441

"""
from alembic import op
import sqlalchemy as sa


revision = '55afed3d839b'
down_revision = '1e4e4a7408cb'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mensalidade_padrao', sa.Numeric(precision=10, scale=2), nullable=True))

    op.create_table(
        'mensalidades',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aluno_id', sa.Integer(), sa.ForeignKey('alunos.id'), nullable=False),
        sa.Column('responsavel_id', sa.Integer(), sa.ForeignKey('responsaveis.id'), nullable=False),
        sa.Column('mes', sa.Integer(), nullable=False),
        sa.Column('ano', sa.Integer(), nullable=False),
        sa.Column('valor', sa.Numeric(10, 2), nullable=False),
        sa.Column('vencimento', sa.Date(), nullable=False),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.Column('criada_em', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('aluno_id', 'mes', 'ano', name='uq_mensalidade_aluno_mes_ano'),
    )

    op.create_table(
        'boletos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('mensalidade_id', sa.Integer(), sa.ForeignKey('mensalidades.id'), nullable=True),
        sa.Column('cora_boleto_id', sa.String(100), nullable=True, index=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='aberto'),
        sa.Column('valor', sa.Numeric(10, 2), nullable=False),
        sa.Column('vencimento', sa.Date(), nullable=False),
        sa.Column('emitido_em', sa.DateTime(), nullable=True),
        sa.Column('pago_em', sa.DateTime(), nullable=True),
        sa.Column('link_pdf', sa.String(500), nullable=True),
        sa.Column('link_boleto', sa.String(500), nullable=True),
    )
    op.create_index('ix_boletos_cora_boleto_id', 'boletos', ['cora_boleto_id'])

    op.create_table(
        'categorias_despesa',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nome', sa.String(80), nullable=False, unique=True),
        sa.Column('cor', sa.String(20), nullable=True),
    )

    op.create_table(
        'movimentacoes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tipo', sa.String(10), nullable=False),
        sa.Column('categoria_id', sa.Integer(), sa.ForeignKey('categorias_despesa.id'), nullable=True),
        sa.Column('descricao', sa.String(200), nullable=False),
        sa.Column('valor', sa.Numeric(10, 2), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('boleto_id', sa.Integer(), sa.ForeignKey('boletos.id'), nullable=True),
        sa.Column('comprovante_path', sa.String(500), nullable=True),
        sa.Column('criada_em', sa.DateTime(), nullable=True),
        sa.Column('criado_por_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=True),
    )


def downgrade():
    op.drop_table('movimentacoes')
    op.drop_table('categorias_despesa')
    op.drop_index('ix_boletos_cora_boleto_id', table_name='boletos')
    op.drop_table('boletos')
    op.drop_table('mensalidades')
    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.drop_column('mensalidade_padrao')
