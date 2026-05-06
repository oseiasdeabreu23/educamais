"""cadastro aluno expandido + duracao curso

Revision ID: 2990bdef0157
Revises: 55afed3d839b
Create Date: 2026-05-04 00:37:29.051852

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2990bdef0157'
down_revision = '55afed3d839b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cpf', sa.String(length=11), nullable=True))
        batch_op.add_column(sa.Column('sexo', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('cor_raca', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('telefone', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('cep', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('logradouro', sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column('numero', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('complemento', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('bairro', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('cidade', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('uf', sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column('pcd', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('pcd_descricao', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=False, server_default='ativo'))
        batch_op.add_column(sa.Column('autoriza_imagem', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('data_consentimento_imagem', sa.Date(), nullable=True))
        batch_op.create_unique_constraint('uq_alunos_cpf', ['cpf'])

    with op.batch_alter_table('cursos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duracao_meses', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('cursos', schema=None) as batch_op:
        batch_op.drop_column('duracao_meses')

    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.drop_constraint('uq_alunos_cpf', type_='unique')
        batch_op.drop_column('data_consentimento_imagem')
        batch_op.drop_column('autoriza_imagem')
        batch_op.drop_column('status')
        batch_op.drop_column('pcd_descricao')
        batch_op.drop_column('pcd')
        batch_op.drop_column('uf')
        batch_op.drop_column('cidade')
        batch_op.drop_column('bairro')
        batch_op.drop_column('complemento')
        batch_op.drop_column('numero')
        batch_op.drop_column('logradouro')
        batch_op.drop_column('cep')
        batch_op.drop_column('telefone')
        batch_op.drop_column('cor_raca')
        batch_op.drop_column('sexo')
        batch_op.drop_column('cpf')
