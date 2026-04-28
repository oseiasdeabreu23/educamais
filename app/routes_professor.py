from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from app import db
from app.models import Aluno, Disciplina, Nota, Frequencia, Atividade, Observacao, Professor, Turma
from app.services import media_aluno, queda_desempenho, stats_frequencia, alertas_frequencia
from datetime import date as date_type
import csv, io

professor_bp = Blueprint('professor', __name__, template_folder='templates')


def professor_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.tipo != 'professor':
            flash('Acesso apenas para professor.', 'danger')
            return redirect(url_for('auth.login'))
        return func(*args, **kwargs)

    return wrapper


@professor_bp.route('/dashboard')
@login_required
@professor_required
def dashboard():
    alunos = Aluno.query.all()
    return render_template('dashboard_professor.html', alunos=alunos)


MESES = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
ANO_ATUAL = __import__('datetime').datetime.now().year
ANOS_DISPONIVEIS = list(range(ANO_ATUAL - 2, ANO_ATUAL + 3))


@professor_bp.route('/lancar-nota', methods=['GET', 'POST'])
@login_required
@professor_required
def lancar_nota():
    if request.method == 'POST':
        disciplina_id = request.form.get('disciplina_id')
        turma_id      = request.form.get('turma_id')
        ano           = int(request.form.get('ano', ANO_ATUAL))
        aluno_ids     = request.form.getlist('aluno_ids')

        for aluno_id in aluno_ids:
            for mes in range(1, 13):
                valor_str = request.form.get(f'nota_{aluno_id}_{mes}', '').strip()
                if not valor_str:
                    # apaga nota existente se campo foi limpo
                    Nota.query.filter_by(aluno_id=aluno_id, disciplina_id=disciplina_id,
                                         mes=mes, ano=ano).delete()
                    continue
                try:
                    valor = float(valor_str.replace(',', '.'))
                except ValueError:
                    continue
                nota = Nota.query.filter_by(
                    aluno_id=aluno_id, disciplina_id=disciplina_id,
                    mes=mes, ano=ano).first()
                if nota:
                    nota.valor = valor
                else:
                    db.session.add(Nota(aluno_id=aluno_id, disciplina_id=disciplina_id,
                                        mes=mes, ano=ano, valor=valor))
        db.session.commit()
        flash('Notas salvas com sucesso!', 'success')
        return redirect(url_for('professor.lancar_nota',
                                turma_id=turma_id, disciplina_id=disciplina_id, ano=ano))

    turma_id      = request.args.get('turma_id', type=int)
    disciplina_id = request.args.get('disciplina_id', type=int)
    ano           = request.args.get('ano', ANO_ATUAL, type=int)

    turmas     = Turma.query.order_by(Turma.nome).all()
    disciplinas = Disciplina.query.order_by(Disciplina.nome).all()

    alunos_data = []
    if turma_id and disciplina_id:
        alunos = Aluno.query.filter_by(turma_id=turma_id).order_by(Aluno.nome).all()
        for aluno in alunos:
            notas_mes = {
                n.mes: n.valor
                for n in aluno.notas
                if n.disciplina_id == disciplina_id and n.ano == ano
            }
            valores = list(notas_mes.values())
            media_disc = round(sum(valores) / len(valores), 2) if valores else None
            alunos_data.append({
                'aluno': aluno,
                'notas_mes': notas_mes,
                'media': media_disc,
            })

    return render_template('professor_lancar_nota.html',
                           turmas=turmas, disciplinas=disciplinas,
                           turma_id=turma_id, disciplina_id=disciplina_id,
                           ano=ano, anos=ANOS_DISPONIVEIS,
                           alunos_data=alunos_data, meses=MESES)


@professor_bp.route('/notas/exportar')
@login_required
@professor_required
def exportar_notas():
    turma_id      = request.args.get('turma_id', type=int)
    disciplina_id = request.args.get('disciplina_id', type=int)
    ano           = request.args.get('ano', ANO_ATUAL, type=int)
    if not turma_id or not disciplina_id:
        flash('Selecione turma e disciplina antes de exportar.', 'warning')
        return redirect(url_for('professor.lancar_nota'))

    turma      = Turma.query.get_or_404(turma_id)
    disciplina = Disciplina.query.get_or_404(disciplina_id)
    alunos     = Aluno.query.filter_by(turma_id=turma_id).order_by(Aluno.nome).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f'Notas {disciplina.nome} — {turma.nome} — {ano}'])
    writer.writerow(['Aluno'] + MESES + ['Média', 'Status'])
    for aluno in alunos:
        notas_mes = {n.mes: n.valor for n in aluno.notas
                     if n.disciplina_id == disciplina_id and n.ano == ano}
        valores = [notas_mes.get(m) for m in range(1, 13)]
        preenchidos = [v for v in valores if v is not None]
        media = round(sum(preenchidos) / len(preenchidos), 2) if preenchidos else None
        if media is None:   status = '-'
        elif media < 5:     status = 'Abaixo da média'
        elif media < 7:     status = 'Na média'
        else:               status = 'Acima da média'
        row = [aluno.nome]
        row += [f'{v:.1f}' if v is not None else '' for v in valores]
        row += [f'{media:.1f}' if media is not None else '', status]
        writer.writerow(row)

    output.seek(0)
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition':
                 f'attachment; filename=notas_{turma.nome}_{disciplina.nome}_{ano}.csv'}
    )


@professor_bp.route('/frequencia', methods=['GET', 'POST'])
@login_required
@professor_required
def registrar_frequencia():
    turmas      = Turma.query.order_by(Turma.nome).all()
    disciplinas = Disciplina.query.order_by(Disciplina.nome).all()

    if request.method == 'POST':
        turma_id      = request.form.get('turma_id')
        disciplina_id = request.form.get('disciplina_id')
        data_str      = request.form.get('data')
        aluno_ids     = request.form.getlist('aluno_ids')

        try:
            data_freq = date_type.fromisoformat(data_str)
        except (ValueError, TypeError):
            data_freq = date_type.today()

        for aluno_id in aluno_ids:
            status = request.form.get(f'status_{aluno_id}', '').strip()
            if status not in ('presente', 'falta', 'justificada'):
                continue
            freq = Frequencia.query.filter_by(
                aluno_id=aluno_id, disciplina_id=disciplina_id, data=data_freq).first()
            if freq:
                freq.status = status
            else:
                db.session.add(Frequencia(
                    aluno_id=aluno_id, disciplina_id=disciplina_id,
                    data=data_freq, status=status))
        db.session.commit()
        flash('Frequência salva com sucesso!', 'success')
        return redirect(url_for('professor.registrar_frequencia',
                                turma_id=turma_id, disciplina_id=disciplina_id,
                                data=data_str))

    turma_id      = request.args.get('turma_id', type=int)
    disciplina_id = request.args.get('disciplina_id', type=int)
    data_str      = request.args.get('data', date_type.today().isoformat())

    try:
        data_freq = date_type.fromisoformat(data_str)
    except ValueError:
        data_freq = date_type.today()

    alunos_data = []
    if turma_id and disciplina_id:
        alunos = Aluno.query.filter_by(turma_id=turma_id).order_by(Aluno.nome).all()
        for aluno in alunos:
            freq_hoje = Frequencia.query.filter_by(
                aluno_id=aluno.id, disciplina_id=disciplina_id, data=data_freq).first()
            st  = stats_frequencia(aluno, disciplina_id)
            alt = alertas_frequencia(aluno, disciplina_id)
            alunos_data.append({
                'aluno':        aluno,
                'status_hoje':  freq_hoje.status if freq_hoje else None,
                'stats':        st,
                'alertas':      alt,
            })

    # totais da turma para o relatório
    total_presencas    = sum(1 for a in alunos_data if a['status_hoje'] == 'presente')
    total_faltas       = sum(1 for a in alunos_data if a['status_hoje'] == 'falta')
    total_justificadas = sum(1 for a in alunos_data if a['status_hoje'] == 'justificada')
    total_sem_registro = sum(1 for a in alunos_data if a['status_hoje'] is None)

    return render_template('professor_frequencia.html',
                           turmas=turmas, disciplinas=disciplinas,
                           turma_id=turma_id, disciplina_id=disciplina_id,
                           data=data_str, data_freq=data_freq,
                           alunos_data=alunos_data,
                           total_presencas=total_presencas,
                           total_faltas=total_faltas,
                           total_justificadas=total_justificadas,
                           total_sem_registro=total_sem_registro)


@professor_bp.route('/atividade', methods=['GET', 'POST'])
@login_required
@professor_required
def criar_atividade():
    turmas      = Turma.query.order_by(Turma.nome).all()
    disciplinas = Disciplina.query.order_by(Disciplina.nome).all()

    if request.method == 'POST':
        titulo        = request.form.get('titulo', '').strip()
        descricao     = request.form.get('descricao', '').strip()
        turma_id      = request.form.get('turma_id') or None
        disciplina_id = request.form.get('disciplina_id') or None
        data_str      = request.form.get('data', date_type.today().isoformat())

        try:
            data_at = date_type.fromisoformat(data_str)
        except ValueError:
            data_at = date_type.today()

        professor = Professor.query.filter_by(nome=current_user.nome).first()

        atividade = Atividade(
            titulo=titulo, descricao=descricao,
            turma_id=turma_id, disciplina_id=disciplina_id,
            professor_id=professor.id if professor else None,
            data=data_at
        )
        db.session.add(atividade)
        db.session.commit()
        flash('Atividade registrada com sucesso!', 'success')
        return redirect(url_for('professor.criar_atividade'))

    # filtros de busca
    f_turma      = request.args.get('f_turma',  type=int)
    f_disciplina = request.args.get('f_disciplina', type=int)
    f_dia        = request.args.get('f_dia',    type=int)
    f_mes        = request.args.get('f_mes',    type=int)
    f_ano        = request.args.get('f_ano',    type=int)

    q = Atividade.query
    if f_turma:
        q = q.filter_by(turma_id=f_turma)
    if f_disciplina:
        q = q.filter_by(disciplina_id=f_disciplina)
    if f_ano:
        q = q.filter(db.extract('year',  Atividade.data) == f_ano)
    if f_mes:
        q = q.filter(db.extract('month', Atividade.data) == f_mes)
    if f_dia:
        q = q.filter(db.extract('day',   Atividade.data) == f_dia)

    atividades = q.order_by(Atividade.data.desc()).all()

    anos_disponiveis = sorted({
        a.data.year for a in Atividade.query.with_entities(Atividade.data).all()
        if a.data
    }, reverse=True) or [date_type.today().year]

    return render_template('professor_atividade.html',
                           turmas=turmas, disciplinas=disciplinas,
                           atividades=atividades,
                           anos_disponiveis=anos_disponiveis,
                           f_turma=f_turma, f_disciplina=f_disciplina,
                           f_dia=f_dia, f_mes=f_mes, f_ano=f_ano)


@professor_bp.route('/atividade/excluir/<int:id>', methods=['POST'])
@login_required
@professor_required
def excluir_atividade(id):
    at = Atividade.query.get_or_404(id)
    db.session.delete(at)
    db.session.commit()
    flash('Atividade excluída.', 'success')
    return redirect(url_for('professor.criar_atividade'))


@professor_bp.route('/observacoes', methods=['GET', 'POST'])
@login_required
@professor_required
def observacoes():
    professor = Professor.query.filter_by(nome=current_user.nome).first()
    if request.method == 'POST':
        aluno_id = request.form.get('aluno_id')
        texto = request.form.get('texto')
        obs = Observacao(aluno_id=aluno_id, professor_id=professor.id if professor else None, texto=texto)
        db.session.add(obs)
        db.session.commit()
        flash('Observação adicionada', 'success')
        return redirect(url_for('professor.observacoes'))

    alunos = Aluno.query.all()
    observacoes = Observacao.query.order_by(Observacao.data.desc()).all()
    return render_template('professor_observacoes.html', alunos=alunos, observacoes=observacoes)


@professor_bp.route('/aluno/<int:aluno_id>')
@login_required
@professor_required
def historico_aluno(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    notas = aluno.notas
    frequencias = aluno.frequencias
    observacoes = aluno.observacoes
    media = media_aluno(aluno)
    queda, msg = queda_desempenho(aluno)
    return render_template('professor_historico.html', aluno=aluno, notas=notas, frequencias=frequencias, observacoes=observacoes, media=media, queda=queda, msg=msg)
