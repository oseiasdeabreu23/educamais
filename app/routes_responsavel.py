from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Responsavel, Aluno, Nota, Frequencia, Atividade
from app.services import media_aluno, aviso_whatsapp

responsavel_bp = Blueprint('responsavel', __name__, template_folder='templates')


def responsavel_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.tipo != 'responsavel':
            flash('Acesso apenas para responsável.', 'danger')
            return redirect(url_for('auth.login'))
        return func(*args, **kwargs)

    return wrapper


@responsavel_bp.route('/dashboard')
@login_required
@responsavel_required
def dashboard():
    # Tenta vincular pelo email ou nome do usuário logado
    responsavel = Responsavel.query.filter_by(email=current_user.email).first()
    if not responsavel:
        responsavel = Responsavel.query.filter_by(nome=current_user.nome).first()

    boletins = []
    if responsavel:
        for aluno in responsavel.alunos:
            boletins.append({
                'aluno': aluno,
                'media': media_aluno(aluno),
                'notas': aluno.notas,
                'frequencias': aluno.frequencias,
                'atividades': Atividade.query.order_by(Atividade.data.desc()).all(),
            })

    return render_template('dashboard_responsavel.html', boletins=boletins)


@responsavel_bp.route('/alerta/<int:aluno_id>')
@login_required
@responsavel_required
def alerta(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    # simulação de checagens
    if media_aluno(aluno) < 5 or len([f for f in aluno.frequencias if f.status == 'falta']) > 5:
        message = aviso_whatsapp(aluno, aluno.notas[0].disciplina if aluno.notas else None)
    else:
        message = 'Sem alertas no momento.'

    return render_template('responsavel_alerta.html', message=message, aluno=aluno)
