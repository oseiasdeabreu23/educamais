from datetime import datetime, date
from flask_login import UserMixin
from app import db, login_manager


class User(db.Model, UserMixin):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(255), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # admin, professor, responsavel

    def get_id(self):
        return str(self.id)


class Turma(db.Model):
    __tablename__ = 'turmas'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    alunos = db.relationship('Aluno', backref='turma', lazy=True)
    encontros = db.relationship(
        'EncontroTurma', backref='turma', lazy=True,
        order_by='EncontroTurma.data, EncontroTurma.ordem',
        cascade='all, delete-orphan'
    )


# Tabela de associação Professor <-> Disciplina (muitos para muitos)
professor_disciplina = db.Table(
    'professor_disciplina',
    db.Column('professor_id', db.Integer, db.ForeignKey('professores.id')),
    db.Column('disciplina_id', db.Integer, db.ForeignKey('disciplinas.id'))
)


# Tabela de associação Professor <-> Turma (muitos para muitos).
# Um professor pode lecionar em várias turmas. O campo legado
# Professor.turma_id é mantido para compatibilidade com dados antigos.
professor_turma = db.Table(
    'professor_turma',
    db.Column('professor_id', db.Integer, db.ForeignKey('professores.id')),
    db.Column('turma_id', db.Integer, db.ForeignKey('turmas.id'))
)


class EncontroTurma(db.Model):
    """Datas de aula previstas para uma turma. Configurado pelo admin no
    cadastro/edição da turma — alimenta o seletor de data na frequência."""
    __tablename__ = 'encontros_turma'
    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey('turmas.id'), nullable=False)
    data = db.Column(db.Date, nullable=False)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('turma_id', 'data', name='uq_encontro_turma_data'),
    )


class Disciplina(db.Model):
    __tablename__ = 'disciplinas'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    notas = db.relationship('Nota', backref='disciplina', lazy=True)


class Aluno(db.Model):
    __tablename__ = 'alunos'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    data_nascimento = db.Column(db.Date, nullable=False)
    turma_id = db.Column(db.Integer, db.ForeignKey('turmas.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True, unique=True)
    mensalidade_padrao = db.Column(db.Numeric(10, 2), nullable=True)

    # Identificação ampliada (cadastro v2)
    cpf = db.Column(db.String(11), unique=True, nullable=True)  # só dígitos
    sexo = db.Column(db.String(30), nullable=True)
    cor_raca = db.Column(db.String(30), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)

    # Endereço desmembrado
    cep = db.Column(db.String(8), nullable=True)  # só dígitos
    logradouro = db.Column(db.String(150), nullable=True)
    numero = db.Column(db.String(10), nullable=True)
    complemento = db.Column(db.String(100), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    uf = db.Column(db.String(2), nullable=True)

    # Acessibilidade
    pcd = db.Column(db.Boolean, nullable=False, default=False)
    pcd_descricao = db.Column(db.Text, nullable=True)

    # Status do vínculo escolar
    status = db.Column(db.String(20), nullable=False, default='ativo')
    # ativo | transferido | evadido | formado

    # LGPD — autorização de uso de imagem
    autoriza_imagem = db.Column(db.Boolean, nullable=False, default=False)
    data_consentimento_imagem = db.Column(db.Date, nullable=True)

    user = db.relationship('User', backref=db.backref('aluno_profile', uselist=False))
    responsaveis = db.relationship('Responsavel', secondary='aluno_responsavel', back_populates='alunos')
    notas = db.relationship('Nota', backref='aluno', lazy=True)
    frequencias = db.relationship('Frequencia', backref='aluno', lazy=True)
    observacoes = db.relationship('Observacao', backref='aluno', lazy=True)
    matriculas = db.relationship('MatriculaCurso', backref='aluno', lazy=True)
    mensalidades = db.relationship('Mensalidade', backref='aluno', lazy=True)

    @property
    def idade(self):
        if not self.data_nascimento:
            return None
        hoje = date.today()
        anos = hoje.year - self.data_nascimento.year
        if (hoje.month, hoje.day) < (self.data_nascimento.month, self.data_nascimento.day):
            anos -= 1
        return anos

    @property
    def cpf_formatado(self):
        c = self.cpf or ''
        if len(c) != 11:
            return c
        return f'{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}'

    @property
    def cep_formatado(self):
        c = self.cep or ''
        if len(c) != 8:
            return c
        return f'{c[:5]}-{c[5:]}'


class Responsavel(db.Model):
    __tablename__ = 'responsaveis'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=True)

    alunos = db.relationship('Aluno', secondary='aluno_responsavel', back_populates='responsaveis')


class AlunoResponsavel(db.Model):
    __tablename__ = 'aluno_responsavel'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'))
    responsavel_id = db.Column(db.Integer, db.ForeignKey('responsaveis.id'))


class Professor(db.Model):
    __tablename__ = 'professores'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    turma_id = db.Column(db.Integer, db.ForeignKey('turmas.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True, unique=True)

    user = db.relationship('User', backref=db.backref('professor_profile', uselist=False))
    turma = db.relationship('Turma', backref='professores', lazy=True,
                            foreign_keys=[turma_id])
    turmas = db.relationship(
        'Turma',
        secondary='professor_turma',
        backref=db.backref('professores_lecionando', lazy=True),
        lazy=True
    )
    disciplinas = db.relationship(
        'Disciplina',
        secondary='professor_disciplina',
        backref=db.backref('professores', lazy=True),
        lazy=True
    )
    observacoes = db.relationship('Observacao', backref='professor', lazy=True)


class Nota(db.Model):
    __tablename__ = 'notas'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    disciplina_id = db.Column(db.Integer, db.ForeignKey('disciplinas.id'), nullable=False)
    mes = db.Column(db.Integer, nullable=False, default=1)   # 1=Jan … 12=Dez
    ano = db.Column(db.Integer, nullable=False, default=lambda: __import__('datetime').datetime.now().year)
    valor = db.Column(db.Float, nullable=False)
    data = db.Column(db.Date, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('aluno_id', 'disciplina_id', 'mes', 'ano',
                            name='uq_nota_aluno_disc_mes_ano'),
    )


class Frequencia(db.Model):
    __tablename__ = 'frequencias'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    disciplina_id = db.Column(db.Integer, db.ForeignKey('disciplinas.id'), nullable=True)
    data = db.Column(db.Date, default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False)  # presente, falta, justificada


class Atividade(db.Model):
    __tablename__ = 'atividades'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    data = db.Column(db.Date, default=datetime.utcnow)
    turma_id = db.Column(db.Integer, db.ForeignKey('turmas.id'), nullable=True)
    disciplina_id = db.Column(db.Integer, db.ForeignKey('disciplinas.id'), nullable=True)
    professor_id = db.Column(db.Integer, db.ForeignKey('professores.id'), nullable=True)
    turma = db.relationship('Turma', backref='atividades', lazy=True)
    disciplina = db.relationship('Disciplina', backref='atividades', lazy=True)
    professor_rel = db.relationship('Professor', backref='atividades', lazy=True)


class Observacao(db.Model):
    __tablename__ = 'observacoes'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    professor_id = db.Column(db.Integer, db.ForeignKey('professores.id'), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    data = db.Column(db.Date, default=datetime.utcnow)


class Curso(db.Model):
    __tablename__ = 'cursos'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    capa_url = db.Column(db.String(500), nullable=True)
    ativo = db.Column(db.Boolean, default=True)
    duracao_meses = db.Column(db.Integer, nullable=True)
    modulos = db.relationship('Modulo', backref='curso', lazy=True,
                              order_by='Modulo.ordem', cascade='all, delete-orphan')
    matriculas = db.relationship('MatriculaCurso', backref='curso', lazy=True,
                                 cascade='all, delete-orphan')


class Modulo(db.Model):
    __tablename__ = 'modulos'
    id = db.Column(db.Integer, primary_key=True)
    curso_id = db.Column(db.Integer, db.ForeignKey('cursos.id'), nullable=False)
    titulo = db.Column(db.String(150), nullable=False)
    ordem = db.Column(db.Integer, default=0)
    videoaulas = db.relationship('Videoaula', backref='modulo', lazy=True,
                                 order_by='Videoaula.ordem', cascade='all, delete-orphan')


class Videoaula(db.Model):
    __tablename__ = 'videoaulas'
    id = db.Column(db.Integer, primary_key=True)
    modulo_id = db.Column(db.Integer, db.ForeignKey('modulos.id'), nullable=False)
    titulo = db.Column(db.String(150), nullable=False)
    video_url = db.Column(db.String(500), nullable=False)
    duracao_min = db.Column(db.Integer, nullable=True)
    ordem = db.Column(db.Integer, default=0)
    progressos = db.relationship('ProgressoVideoaula', backref='videoaula', lazy=True,
                                 cascade='all, delete-orphan')


class MatriculaCurso(db.Model):
    __tablename__ = 'matriculas_curso'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    curso_id = db.Column(db.Integer, db.ForeignKey('cursos.id'), nullable=False)
    data_matricula = db.Column(db.Date, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('aluno_id', 'curso_id', name='uq_matricula_aluno_curso'),
    )


class ProgressoVideoaula(db.Model):
    __tablename__ = 'progresso_videoaulas'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    videoaula_id = db.Column(db.Integer, db.ForeignKey('videoaulas.id'), nullable=False)
    assistido = db.Column(db.Boolean, default=False)
    data = db.Column(db.Date, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('aluno_id', 'videoaula_id', name='uq_progresso_aluno_video'),
    )


class Mensalidade(db.Model):
    __tablename__ = 'mensalidades'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    responsavel_id = db.Column(db.Integer, db.ForeignKey('responsaveis.id'), nullable=True)
    plano_id = db.Column(db.Integer, db.ForeignKey('planos_pagamento.id'), nullable=True)
    mes = db.Column(db.Integer, nullable=False)
    ano = db.Column(db.Integer, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    vencimento = db.Column(db.Date, nullable=False)
    observacao = db.Column(db.Text, nullable=True)
    cancelada_em = db.Column(db.DateTime, nullable=True)
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)

    responsavel = db.relationship('Responsavel', backref='mensalidades', lazy=True)
    boletos = db.relationship('Boleto', backref='mensalidade', lazy=True,
                              cascade='all, delete-orphan')
    __table_args__ = (
        db.UniqueConstraint('aluno_id', 'mes', 'ano', name='uq_mensalidade_aluno_mes_ano'),
    )


class PlanoPagamento(db.Model):
    __tablename__ = 'planos_pagamento'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    n_parcelas = db.Column(db.Integer, nullable=False)
    valor_parcela = db.Column(db.Numeric(10, 2), nullable=False)
    dia_vencimento = db.Column(db.Integer, nullable=False, default=10)
    data_primeira = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='ativo')
    # ativo | cancelado | concluido
    observacao = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    cancelado_em = db.Column(db.DateTime, nullable=True)

    aluno = db.relationship('Aluno', backref=db.backref('planos_pagamento', lazy=True))
    mensalidades = db.relationship('Mensalidade', backref='plano', lazy=True)


class Boleto(db.Model):
    __tablename__ = 'boletos'
    id = db.Column(db.Integer, primary_key=True)
    mensalidade_id = db.Column(db.Integer, db.ForeignKey('mensalidades.id'), nullable=True)
    cora_boleto_id = db.Column(db.String(100), nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='aberto')
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    vencimento = db.Column(db.Date, nullable=False)
    emitido_em = db.Column(db.DateTime, default=datetime.utcnow)
    pago_em = db.Column(db.DateTime, nullable=True)
    link_pdf = db.Column(db.String(500), nullable=True)
    link_boleto = db.Column(db.String(500), nullable=True)

    # Tipo da cobrança — discrimina origem (manual, integração)
    tipo_cobranca = db.Column(db.String(20), nullable=False, default='cora')
    # cora | boleto_manual | pix_manual | mp_pix | mp_boleto
    linha_digitavel = db.Column(db.Text, nullable=True)
    pix_copia_cola = db.Column(db.Text, nullable=True)
    pdf_path = db.Column(db.String(500), nullable=True)

    # Mercado Pago (preenchido quando tipo_cobranca in (mp_pix, mp_boleto))
    mp_payment_id = db.Column(db.String(100), nullable=True, index=True)


class CategoriaDespesa(db.Model):
    __tablename__ = 'categorias_despesa'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), nullable=False, unique=True)
    cor = db.Column(db.String(20), nullable=True)
    movimentacoes = db.relationship('Movimentacao', backref='categoria', lazy=True)


class Movimentacao(db.Model):
    __tablename__ = 'movimentacoes'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_despesa.id'), nullable=True)
    descricao = db.Column(db.String(200), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    data = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    boleto_id = db.Column(db.Integer, db.ForeignKey('boletos.id'), nullable=True)
    comprovante_path = db.Column(db.String(500), nullable=True)
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)
    criado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    boleto = db.relationship('Boleto', backref='movimentacoes', lazy=True)
    criado_por = db.relationship('User', backref='movimentacoes', lazy=True)


class ConfigSistema(db.Model):
    __tablename__ = 'config_sistema'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, default='EducaMais')
    logo_path = db.Column(db.String(500), nullable=True)
    # Identificador único desta instância, usado pelo Painel de Licenças.
    # Em SQLite (dev) fica em instance/machine_id.txt; em Postgres (prod,
    # Vercel readonly FS) vive aqui. Preenchido na 1ª validação se vazio.
    machine_id = db.Column(db.String(64), nullable=True)


class IntegracaoMercadoPago(db.Model):
    """Singleton (sempre ID=1) com credenciais do Mercado Pago.

    `access_token` é o segredo principal — guardado em texto puro no banco
    (instituicao já usa SQLite local com acesso restrito). Em prod com
    Postgres compartilhado, considerar criptografia simétrica futura.
    """
    __tablename__ = 'integracao_mercadopago'
    id = db.Column(db.Integer, primary_key=True)
    ativo = db.Column(db.Boolean, nullable=False, default=False)
    ambiente = db.Column(db.String(20), nullable=False, default='production')
    # production | sandbox
    access_token = db.Column(db.Text, nullable=True)
    webhook_secret = db.Column(db.String(200), nullable=True)
    notification_url = db.Column(db.String(500), nullable=True)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow,
                              onupdate=datetime.utcnow)
    atualizado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'),
                                  nullable=True)

    atualizado_por = db.relationship('User', lazy=True)

    @property
    def access_token_mascarado(self):
        """Retorna o token com só os últimos 4 caracteres visíveis."""
        if not self.access_token:
            return ''
        if len(self.access_token) <= 8:
            return '••••'
        return '••••••••' + self.access_token[-4:]


class ConfigLicenca(db.Model):
    """Singleton (sempre ID=1) com config da integração com o Painel de
    Licenças. Substitui as envs ``PAINEL_LICENCA_API_KEY``,
    ``PAINEL_LICENCA_DOCUMENTO``, ``PAINEL_LICENCA_TIPO_CLIENTE`` e
    ``PAINEL_LICENCA_MODO`` — assim o admin configura tudo pela UI sem
    precisar mexer no ``.env``.

    Os parâmetros técnicos (``URL``, ``CACHE_HORAS``, ``GRACE_DIAS``,
    ``DEBUG_RESULTADO``) continuam vindo do env porque não fazem sentido
    expor pra usuário final.
    """
    __tablename__ = 'config_licenca'
    id = db.Column(db.Integer, primary_key=True)
    api_key = db.Column(db.Text, nullable=True)
    documento = db.Column(db.String(20), nullable=True)
    # pessoa_fisica | empresa (futuramente: municipio/ibge)
    tipo_cliente = db.Column(db.String(30), nullable=True)
    # log | bloqueio
    modo = db.Column(db.String(20), nullable=False, default='bloqueio')
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow,
                              onupdate=datetime.utcnow)
    atualizado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'),
                                  nullable=True)

    atualizado_por = db.relationship('User', lazy=True)

    @property
    def api_key_mascarada(self):
        """Mostra só o prefixo (pk_) e os últimos 4 caracteres."""
        if not self.api_key:
            return ''
        v = self.api_key
        if len(v) <= 8:
            return '••••'
        prefixo = v[:3] if v[:3] in ('pk_', 'sk_') else v[:3]
        return f'{prefixo}••••••••{v[-4:]}'


# --------------------------------------------------------------------------- #
# Estado do Cora mock (persistido no DB pra funcionar em serverless).
# Em prod com CORA_MODE=real estas tabelas ficam vazias — o estado vive no Cora.
# --------------------------------------------------------------------------- #
class CoraMockBoleto(db.Model):
    __tablename__ = 'cora_mock_boletos'
    id = db.Column(db.Integer, primary_key=True)
    cora_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='aberto')
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    vencimento = db.Column(db.Date, nullable=False)
    pagador = db.Column(db.JSON, nullable=True)
    descricao = db.Column(db.Text, nullable=True)
    emitido_em = db.Column(db.DateTime, default=datetime.utcnow)
    pago_em = db.Column(db.DateTime, nullable=True)


class CoraMockMovimentacao(db.Model):
    __tablename__ = 'cora_mock_movimentacoes'
    id = db.Column(db.Integer, primary_key=True)
    mov_id = db.Column(db.String(64), unique=True, nullable=False)
    tipo = db.Column(db.String(10), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    descricao = db.Column(db.String(300), nullable=True)
    data = db.Column(db.Date, nullable=False)
    cora_boleto_id = db.Column(db.String(64), nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
