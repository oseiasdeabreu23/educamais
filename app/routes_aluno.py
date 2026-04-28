from functools import wraps
from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.models import (Aluno, Nota, Frequencia, Atividade, Disciplina,
                        Curso, MatriculaCurso, Videoaula, ProgressoVideoaula)
from app.services import (media_aluno, stats_frequencia, alertas_frequencia,
                           queda_desempenho, embed_url)

aluno_bp = Blueprint('aluno', __name__, template_folder='templates')

MESES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
         'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def aluno_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.tipo != 'aluno':
            flash('Acesso exclusivo para alunos.', 'danger')
            return redirect(url_for('auth.login'))
        return func(*args, **kwargs)
    return wrapper


def _get_aluno():
    return current_user.aluno_profile


# ── Dashboard ──────────────────────────────────────────────────────────────────

@aluno_bp.route('/dashboard')
@login_required
@aluno_required
def dashboard():
    aluno = _get_aluno()
    if not aluno:
        flash('Perfil de aluno não encontrado. Contate o administrador.', 'warning')
        return redirect(url_for('auth.logout'))

    media = media_aluno(aluno)
    freq = stats_frequencia(aluno)
    alertas = alertas_frequencia(aluno)
    queda, msg_queda = queda_desempenho(aluno)
    matriculas = MatriculaCurso.query.filter_by(aluno_id=aluno.id).all()

    # Notas agrupadas por disciplina
    notas_por_disc = {}
    for nota in aluno.notas:
        did = nota.disciplina_id
        if did not in notas_por_disc:
            notas_por_disc[did] = {'disciplina': nota.disciplina, 'notas': []}
        notas_por_disc[did]['notas'].append(nota)

    disciplinas_data = []
    for data in notas_por_disc.values():
        notas = data['notas']
        media_disc = round(sum(n.valor for n in notas) / len(notas), 2)
        disciplinas_data.append({
            'disciplina': data['disciplina'],
            'media': media_disc,
            'notas': sorted(notas, key=lambda x: (x.ano, x.mes)),
        })
    disciplinas_data.sort(key=lambda x: x['disciplina'].nome)

    # Atividades recentes da turma
    atividades = []
    if aluno.turma_id:
        atividades = (Atividade.query
                      .filter_by(turma_id=aluno.turma_id)
                      .order_by(Atividade.data.desc())
                      .limit(5).all())

    # Médias mensais do ano atual para o gráfico
    ano_atual = datetime.now().year
    medias_mensais = []
    for mes in range(1, 13):
        notas_mes = [n.valor for n in aluno.notas
                     if n.mes == mes and n.ano == ano_atual]
        medias_mensais.append(round(sum(notas_mes) / len(notas_mes), 2)
                              if notas_mes else None)

    # Séries por disciplina para o gráfico
    series_chart = []
    cores = ['#4361ee', '#f72585', '#4cc9f0', '#7209b7',
             '#06d6a0', '#fb8500', '#e63946', '#457b9d']
    for i, d in enumerate(disciplinas_data):
        valores = []
        for mes in range(1, 13):
            n = next((x.valor for x in d['notas']
                      if x.mes == mes and x.ano == ano_atual), None)
            valores.append(n)
        series_chart.append({
            'label': d['disciplina'].nome,
            'data': valores,
            'cor': cores[i % len(cores)],
        })

    return render_template('aluno_dashboard.html',
                           aluno=aluno,
                           media=media,
                           freq=freq,
                           alertas=alertas,
                           queda=queda,
                           msg_queda=msg_queda,
                           matriculas=matriculas,
                           disciplinas_data=disciplinas_data,
                           atividades=atividades,
                           medias_mensais=medias_mensais,
                           series_chart=series_chart,
                           meses=MESES,
                           ano_atual=ano_atual)


# ── Boletim ────────────────────────────────────────────────────────────────────

@aluno_bp.route('/boletim')
@login_required
@aluno_required
def boletim():
    aluno = _get_aluno()
    ano = request.args.get('ano', datetime.now().year, type=int)
    anos_disponiveis = sorted({n.ano for n in aluno.notas}, reverse=True) \
                       or [datetime.now().year]

    disciplinas = Disciplina.query.order_by(Disciplina.nome).all()
    boletim_data = []
    for disc in disciplinas:
        notas_mes = {n.mes: n.valor for n in aluno.notas
                     if n.disciplina_id == disc.id and n.ano == ano}
        if not notas_mes:
            continue
        valores = [notas_mes.get(m) for m in range(1, 13)]
        preenchidos = [v for v in valores if v is not None]
        media = round(sum(preenchidos) / len(preenchidos), 2) if preenchidos else None
        boletim_data.append({'disciplina': disc, 'notas': valores, 'media': media})

    return render_template('aluno_boletim.html',
                           aluno=aluno,
                           boletim_data=boletim_data,
                           meses=MESES,
                           ano=ano,
                           anos_disponiveis=anos_disponiveis)


# ── Frequência ─────────────────────────────────────────────────────────────────

@aluno_bp.route('/frequencia')
@login_required
@aluno_required
def frequencia():
    aluno = _get_aluno()
    freq = stats_frequencia(aluno)
    alertas = alertas_frequencia(aluno)
    historico = sorted(aluno.frequencias, key=lambda x: x.data, reverse=True)

    return render_template('aluno_frequencia.html',
                           aluno=aluno,
                           freq=freq,
                           alertas=alertas,
                           historico=historico)


# ── Cursos ─────────────────────────────────────────────────────────────────────

@aluno_bp.route('/cursos')
@login_required
@aluno_required
def cursos():
    aluno = _get_aluno()
    matriculas = MatriculaCurso.query.filter_by(aluno_id=aluno.id).all()

    ids_assistidas = {
        p.videoaula_id
        for p in ProgressoVideoaula.query.filter_by(
            aluno_id=aluno.id, assistido=True).all()
    }

    cursos_data = []
    for m in matriculas:
        curso = m.curso
        todos_videos = [v for mod in curso.modulos for v in mod.videoaulas]
        total = len(todos_videos)
        assistidas = sum(1 for v in todos_videos if v.id in ids_assistidas)
        progresso = round((assistidas / total) * 100) if total > 0 else 0
        cursos_data.append({
            'curso': curso,
            'total_videos': total,
            'assistidas': assistidas,
            'progresso': progresso,
        })

    return render_template('aluno_cursos.html', aluno=aluno, cursos_data=cursos_data)


@aluno_bp.route('/cursos/<int:curso_id>')
@login_required
@aluno_required
def curso_detalhe(curso_id):
    aluno = _get_aluno()
    matricula = MatriculaCurso.query.filter_by(
        aluno_id=aluno.id, curso_id=curso_id).first_or_404()
    curso = matricula.curso

    ids_assistidas = {
        p.videoaula_id
        for p in ProgressoVideoaula.query.filter_by(
            aluno_id=aluno.id, assistido=True).all()
    }

    modulos_data = []
    for modulo in curso.modulos:
        videos_data = [{'video': v, 'assistido': v.id in ids_assistidas}
                       for v in modulo.videoaulas]
        modulos_data.append({
            'modulo': modulo,
            'videos': videos_data,
            'total': len(videos_data),
            'assistidos': sum(1 for vd in videos_data if vd['assistido']),
        })

    return render_template('aluno_curso_detalhe.html',
                           aluno=aluno,
                           curso=curso,
                           modulos_data=modulos_data)


# ── Videoaula player ───────────────────────────────────────────────────────────

@aluno_bp.route('/videoaula/<int:video_id>')
@login_required
@aluno_required
def videoaula(video_id):
    aluno = _get_aluno()
    video = Videoaula.query.get_or_404(video_id)
    curso = video.modulo.curso

    MatriculaCurso.query.filter_by(
        aluno_id=aluno.id, curso_id=curso.id).first_or_404()

    player_url = embed_url(video.video_url)

    progresso = ProgressoVideoaula.query.filter_by(
        aluno_id=aluno.id, videoaula_id=video.id).first()
    assistido = progresso.assistido if progresso else False

    videos_modulo = sorted(video.modulo.videoaulas, key=lambda x: x.ordem)
    idx = next((i for i, v in enumerate(videos_modulo) if v.id == video.id), 0)
    anterior = videos_modulo[idx - 1] if idx > 0 else None
    proximo = videos_modulo[idx + 1] if idx < len(videos_modulo) - 1 else None

    return render_template('aluno_videoaula.html',
                           aluno=aluno,
                           video=video,
                           curso=curso,
                           player_url=player_url,
                           assistido=assistido,
                           anterior=anterior,
                           proximo=proximo,
                           videos_modulo=videos_modulo,
                           idx_atual=idx)


@aluno_bp.route('/videoaula/<int:video_id>/marcar', methods=['POST'])
@login_required
@aluno_required
def marcar_assistida(video_id):
    aluno = _get_aluno()
    progresso = ProgressoVideoaula.query.filter_by(
        aluno_id=aluno.id, videoaula_id=video_id).first()
    if progresso:
        progresso.assistido = not progresso.assistido
    else:
        db.session.add(ProgressoVideoaula(
            aluno_id=aluno.id, videoaula_id=video_id,
            assistido=True, data=date.today()))
    db.session.commit()
    return redirect(url_for('aluno.videoaula', video_id=video_id))
