from datetime import datetime
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


# Tabela de associação Professor <-> Disciplina (muitos para muitos)
professor_disciplina = db.Table(
    'professor_disciplina',
    db.Column('professor_id', db.Integer, db.ForeignKey('professores.id')),
    db.Column('disciplina_id', db.Integer, db.ForeignKey('disciplinas.id'))
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

    user = db.relationship('User', backref=db.backref('aluno_profile', uselist=False))
    responsaveis = db.relationship('Responsavel', secondary='aluno_responsavel', back_populates='alunos')
    notas = db.relationship('Nota', backref='aluno', lazy=True)
    frequencias = db.relationship('Frequencia', backref='aluno', lazy=True)
    observacoes = db.relationship('Observacao', backref='aluno', lazy=True)
    matriculas = db.relationship('MatriculaCurso', backref='aluno', lazy=True)


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

    turma = db.relationship('Turma', backref='professores', lazy=True)
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


class ConfigSistema(db.Model):
    __tablename__ = 'config_sistema'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, default='EducaMais')
    logo_path = db.Column(db.String(500), nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
