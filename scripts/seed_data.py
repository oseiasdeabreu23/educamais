import bcrypt
from app import create_app, db
from app.models import (User, Turma, Disciplina, Aluno, Responsavel, AlunoResponsavel,
                        Professor, Nota, Frequencia, Atividade, Observacao,
                        Curso, Modulo, Videoaula, MatriculaCurso)
from datetime import date

app = create_app()
with app.app_context():
    db.create_all()

    def add_user(nome, email, senha, tipo):
        if User.query.filter_by(email=email).first():
            return
        hash_senha = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        db.session.add(User(nome=nome, email=email, senha=hash_senha, tipo=tipo))

    add_user('Admin Escola', 'admin@escola.com', 'admin123', 'admin')
    add_user('Prof. Pessoa', 'prof@escola.com', 'prof123', 'professor')
    add_user('Resp. Familia', 'resp@escola.com', 'resp123', 'responsavel')
    add_user('João Silva', 'aluno@escola.com', 'aluno123', 'aluno')

    turma = Turma.query.filter_by(nome='7A').first() or Turma(nome='7A')
    disciplina = Disciplina.query.filter_by(nome='Matemática').first() or Disciplina(nome='Matemática')
    if not turma.id: db.session.add(turma)
    if not disciplina.id: db.session.add(disciplina)
    db.session.commit()

    aluno = Aluno.query.filter_by(nome='João Silva').first() or Aluno(nome='João Silva', data_nascimento=date(2013,5,12), turma_id=turma.id)
    if not aluno.id: db.session.add(aluno)
    responsavel = Responsavel.query.filter_by(nome='Maria Silva').first() or Responsavel(nome='Maria Silva', telefone='11999990000')
    if not responsavel.id: db.session.add(responsavel)
    db.session.commit()

    # vinculo
    if not AlunoResponsavel.query.filter_by(aluno_id=aluno.id, responsavel_id=responsavel.id).first():
        db.session.add(AlunoResponsavel(aluno_id=aluno.id, responsavel_id=responsavel.id))

    prof = Professor.query.filter_by(nome='Prof. Pessoa').first()
    if not prof:
        prof = Professor(nome='Prof. Pessoa', turma_id=turma.id)
        prof.disciplinas.append(disciplina)
        db.session.add(prof)
    db.session.commit()

    if not Nota.query.filter_by(aluno_id=aluno.id, disciplina_id=disciplina.id).first():
        db.session.add(Nota(aluno_id=aluno.id, disciplina_id=disciplina.id, valor=4.5))
        db.session.add(Nota(aluno_id=aluno.id, disciplina_id=disciplina.id, valor=5.2))
        db.session.add(Nota(aluno_id=aluno.id, disciplina_id=disciplina.id, valor=4.8))

    if not Frequencia.query.filter_by(aluno_id=aluno.id).first():
        db.session.add(Frequencia(aluno_id=aluno.id, status='presente'))
        db.session.add(Frequencia(aluno_id=aluno.id, status='falta'))
        db.session.add(Frequencia(aluno_id=aluno.id, status='falta'))

    if not Atividade.query.filter_by(titulo='Prova 1').first():
        db.session.add(Atividade(titulo='Prova 1', descricao='Prova de Matemática, capítulo 1-2'))

    if not Observacao.query.filter_by(aluno_id=aluno.id, professor_id=prof.id).first():
        db.session.add(Observacao(aluno_id=aluno.id, professor_id=prof.id, texto='Aluno precisa revisar álgebra.'))

    # Vincular conta 'aluno' ao registro de Aluno
    user_aluno = User.query.filter_by(email='aluno@escola.com').first()
    if user_aluno and aluno.user_id is None:
        aluno.user_id = user_aluno.id
        db.session.commit()

    # Curso de exemplo
    curso = Curso.query.filter_by(titulo='Matemática Básica').first()
    if not curso:
        curso = Curso(titulo='Matemática Básica',
                      descricao='Fundamentos de álgebra, geometria e aritmética.',
                      ativo=True)
        db.session.add(curso)
        db.session.flush()

        mod1 = Modulo(curso_id=curso.id, titulo='Álgebra', ordem=0)
        mod2 = Modulo(curso_id=curso.id, titulo='Geometria', ordem=1)
        db.session.add_all([mod1, mod2])
        db.session.flush()

        db.session.add_all([
            Videoaula(modulo_id=mod1.id, titulo='Introdução à Álgebra',
                      video_url='https://www.youtube.com/watch?v=NybHckSEQBI',
                      duracao_min=12, ordem=0),
            Videoaula(modulo_id=mod1.id, titulo='Equações do 1º grau',
                      video_url='https://www.youtube.com/watch?v=NybHckSEQBI',
                      duracao_min=18, ordem=1),
            Videoaula(modulo_id=mod2.id, titulo='Figuras geométricas',
                      video_url='https://www.youtube.com/watch?v=NybHckSEQBI',
                      duracao_min=14, ordem=0),
        ])
        db.session.commit()

    if not MatriculaCurso.query.filter_by(aluno_id=aluno.id, curso_id=curso.id).first():
        db.session.add(MatriculaCurso(aluno_id=aluno.id, curso_id=curso.id,
                                      data_matricula=date.today()))
        db.session.commit()

    db.session.commit()
    print('Seed concluído com sucesso!')
