"""Apaga todos os Alunos e dados dependentes (uso pré-migration de schema).

Roda com: venv\\Scripts\\python.exe scripts\\limpar_alunos.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app, db
from app.models import (Aluno, Nota, Frequencia, Observacao, MatriculaCurso,
                        ProgressoVideoaula, Mensalidade, Boleto, Movimentacao,
                        AlunoResponsavel, User)

app = create_app()
with app.app_context():
    n_alunos = Aluno.query.count()
    if n_alunos == 0:
        print('Nenhum aluno para apagar.')
        raise SystemExit(0)

    print(f'Apagando {n_alunos} aluno(s) e dependências...')

    # Movimentações vindas de boletos viram desvinculadas (não apagamos histórico financeiro)
    Movimentacao.query.filter(Movimentacao.boleto_id.isnot(None)).update(
        {Movimentacao.boleto_id: None}, synchronize_session=False)

    Boleto.query.delete(synchronize_session=False)
    Mensalidade.query.delete(synchronize_session=False)
    ProgressoVideoaula.query.delete(synchronize_session=False)
    MatriculaCurso.query.delete(synchronize_session=False)
    Observacao.query.delete(synchronize_session=False)
    Frequencia.query.delete(synchronize_session=False)
    Nota.query.delete(synchronize_session=False)
    AlunoResponsavel.query.delete(synchronize_session=False)

    # Coleta user_ids vinculados a alunos antes de apagar
    user_ids = [a.user_id for a in Aluno.query.all() if a.user_id]
    Aluno.query.delete(synchronize_session=False)

    # Remove os usuários do tipo aluno órfãos
    if user_ids:
        User.query.filter(User.id.in_(user_ids)).delete(synchronize_session=False)

    db.session.commit()
    print('Limpeza concluída.')
