import os
import uuid
import bcrypt
from decimal import Decimal, InvalidOperation
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, current_app, send_file, abort, jsonify)
from flask_login import login_required, current_user, logout_user
from werkzeug.utils import secure_filename
from app import db
from app.models import (User, Aluno, Responsavel, Professor, Turma, Disciplina,
                        Curso, Modulo, Videoaula, MatriculaCurso, ConfigSistema,
                        Mensalidade, Boleto, CategoriaDespesa, Movimentacao,
                        PlanoPagamento, IntegracaoMercadoPago, EncontroTurma,
                        Aviso, AvisoLeitura, Atividade, MatriculaTurma,
                        Nota, Frequencia, Observacao, AlunoResponsavel,
                        ProgressoVideoaula)
from app.services import (media_turma, medias_por_turma, frequencia_geral,
                          alunos_baixo_desempenho, status_derivado_por_aluno,
                          cpf_valido, cep_valido, uf_valida, so_digitos, UFS_BR,
                          aniversariantes, ESCOPOS_ANIVERSARIO,
                          matricular_em_turma, formar_em_turma,
                          evadir_em_turma, transferir_em_turma)
from app import (services_backup, services_financeiro, services_mercadopago,
                 services_avisos, services_relatorios, storage)
from app.services_cora import get_cora_client, CoraError, CoraMockClient
from app.services_mercadopago import MercadoPagoError
from app.permissoes import (requires, pode, ROLES_CRIAVEIS_ADMIN, ROLES_LABEL,
                            ROLES_ADMIN_LIKE, PERMISSOES, PERMISSOES_CATALOGO,
                            PERMISSOES_TODAS)
from app import services_permissoes
from datetime import date, datetime
from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError

LOGO_EXTENSOES = {'png', 'jpg', 'jpeg', 'webp', 'svg'}


def _extensao_valida(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in LOGO_EXTENSOES)

admin_bp = Blueprint('admin', __name__, template_folder='templates')


def admin_required(func):
    """Acesso somente para admin (papel mais restrito). Mantido para
    rotas sensíveis: configurações, backup, gestão de usuários,
    integração Mercado Pago, etc. Para permissões granulares, use
    o decorator @requires('chave') do módulo app.permissoes."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.tipo != 'admin':
            flash('Acesso apenas para administrador.', 'danger')
            return redirect(url_for('auth.login'))
        return func(*args, **kwargs)

    return wrapper


# ── Dashboard ──────────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard')
@login_required
@requires('dashboard.ver')
def dashboard():
    turmas = Turma.query.all()
    # medias_por_turma() roda 1 query agregada para todas as turmas,
    # evitando o N+1 do padrão [media_turma(t) for t in turmas].
    medias_map = medias_por_turma()
    medias = [medias_map.get(t.id, 0) for t in turmas]
    relatorios = {
        'media_geral': round(sum(medias) / (len(turmas) or 1), 2),
        'medias_por_turma': medias_map,
        'frequencia': frequencia_geral(),
        'baixo_desempenho': alunos_baixo_desempenho(),
    }
    aniv_hoje = aniversariantes(escopo='dia')
    return render_template('dashboard_admin.html', turmas=turmas,
                           relatorios=relatorios, aniv_hoje=aniv_hoje)


# ── Aniversariantes ────────────────────────────────────────────────────────────

@admin_bp.route('/aniversariantes')
@login_required
@requires('aniversariante.ver')
def aniversariantes_view():
    escopo = (request.args.get('escopo') or 'dia').lower()
    if escopo not in ESCOPOS_ANIVERSARIO:
        escopo = 'dia'
    lista = aniversariantes(escopo=escopo)
    return render_template('admin_aniversariantes.html',
                           lista=lista, escopo=escopo, hoje=date.today())


# ── Relatórios ────────────────────────────────────────────────────────────────

@admin_bp.route('/relatorios')
@login_required
@requires('relatorio.ver')
def relatorios():
    turma_id_raw = request.args.get('turma_id', type=int)
    snapshot = services_relatorios.snapshot_completo(turma_id=turma_id_raw)
    turmas = Turma.query.order_by(Turma.nome).all()
    return render_template(
        'admin_relatorios.html',
        snapshot=snapshot,
        turmas=turmas,
        turma_id=turma_id_raw,
    )


@admin_bp.route('/relatorios/pdf')
@login_required
@requires('relatorio.exportar')
def relatorios_pdf():
    turma_id_raw = request.args.get('turma_id', type=int)
    snapshot = services_relatorios.snapshot_completo(turma_id=turma_id_raw)
    turma_nome = None
    if turma_id_raw:
        t = Turma.query.get(turma_id_raw)
        turma_nome = t.nome if t else None

    from app.services_export import relatorio_status_pdf
    config = ConfigSistema.query.first()
    pdf_bytes = relatorio_status_pdf(
        snapshot,
        filtro_turma=turma_nome,
        nome_instituicao=(config.nome if config else 'EducaMais'),
    )
    nome = f'relatorio_alunos_{date.today().isoformat()}.pdf'
    return send_file(pdf_bytes, mimetype='application/pdf',
                     as_attachment=True, download_name=nome)


# ── Alunos ─────────────────────────────────────────────────────────────────────

SEXOS_CHOICES = ('Masculino', 'Feminino', 'Outro', 'Prefiro não informar')
COR_RACA_CHOICES = ('Branca', 'Preta', 'Parda', 'Amarela', 'Indígena', 'Não declarada')
STATUS_ALUNO_CHOICES = ('ativo', 'evadido', 'formado')


def _aplicar_dados_aluno(aluno, form, is_novo=False):
    """Lê o form, valida e popula o objeto Aluno. Retorna (ok, mensagem_erro)."""
    nome = (form.get('nome') or '').strip()
    if not nome:
        return False, 'Nome é obrigatório.'

    try:
        data_nasc = date.fromisoformat(form.get('data_nascimento') or '')
    except ValueError:
        return False, 'Data de nascimento inválida.'

    cpf_raw = form.get('cpf') or ''
    cpf = so_digitos(cpf_raw) or None
    if cpf and not cpf_valido(cpf):
        return False, 'CPF inválido.'

    sexo = form.get('sexo') or None
    if sexo and sexo not in SEXOS_CHOICES:
        return False, 'Sexo inválido.'

    cor_raca = form.get('cor_raca') or None
    if cor_raca and cor_raca not in COR_RACA_CHOICES:
        return False, 'Cor/Raça inválida.'

    status = form.get('status') or 'ativo'
    if status not in STATUS_ALUNO_CHOICES:
        return False, 'Status inválido.'

    cep = so_digitos(form.get('cep')) or None
    if cep and not cep_valido(cep):
        return False, 'CEP inválido.'

    uf = (form.get('uf') or '').strip().upper() or None
    if uf and not uf_valida(uf):
        return False, 'UF inválida.'

    turma_id = form.get('turma_id') or None
    mensalidade = form.get('mensalidade_padrao')
    mensalidade = _parse_decimal(mensalidade) if mensalidade else None

    autoriza = bool(form.get('autoriza_imagem'))
    data_consent_str = form.get('data_consentimento_imagem') or ''
    data_consent = None
    if autoriza:
        if data_consent_str:
            try:
                data_consent = date.fromisoformat(data_consent_str)
            except ValueError:
                return False, 'Data de consentimento inválida.'
        else:
            data_consent = date.today()

    aluno.nome = nome
    aluno.data_nascimento = data_nasc
    aluno.cpf = cpf
    aluno.sexo = sexo
    aluno.cor_raca = cor_raca
    aluno.telefone = (form.get('telefone') or '').strip() or None
    aluno.cep = cep
    aluno.logradouro = (form.get('logradouro') or '').strip() or None
    aluno.numero = (form.get('numero') or '').strip() or None
    aluno.complemento = (form.get('complemento') or '').strip() or None
    aluno.bairro = (form.get('bairro') or '').strip() or None
    aluno.cidade = (form.get('cidade') or '').strip() or None
    aluno.uf = uf
    aluno.pcd = bool(form.get('pcd'))
    aluno.pcd_descricao = (form.get('pcd_descricao') or '').strip() or None if aluno.pcd else None
    aluno.status = status
    aluno.autoriza_imagem = autoriza
    aluno.data_consentimento_imagem = data_consent if autoriza else None
    aluno.turma_id = turma_id or None
    aluno.mensalidade_padrao = mensalidade
    return True, None


def _sincronizar_matriculas(aluno, curso_ids):
    """Adiciona matrículas novas e remove as desmarcadas."""
    novos_ids = {int(c) for c in curso_ids if c}
    atuais = {m.curso_id: m for m in aluno.matriculas}
    # Remove os que saíram
    for cid, matr in atuais.items():
        if cid not in novos_ids:
            db.session.delete(matr)
    # Adiciona os novos
    for cid in novos_ids:
        if cid not in atuais and Curso.query.get(cid):
            db.session.add(MatriculaCurso(aluno_id=aluno.id, curso_id=cid,
                                          data_matricula=date.today()))


def _matricular_turmas_iniciais(aluno, turma_ids):
    """Cria MatriculaTurma ativas para cada turma selecionada na criação.
    Sincroniza aluno.turma_id (legacy) com a primeira da lista."""
    ids = []
    for raw in turma_ids:
        if not raw:
            continue
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        return
    primeira = None
    for tid in ids:
        turma = Turma.query.get(tid)
        if not turma:
            continue
        try:
            matricular_em_turma(aluno, turma)
        except ValueError:
            continue
        if primeira is None:
            primeira = turma
    if primeira is not None and not aluno.turma_id:
        aluno.turma_id = primeira.id


@admin_bp.route('/alunos', methods=['GET', 'POST'])
@login_required
@requires('aluno.ver')
def alunos():
    if request.method == 'POST':
        if not pode(current_user, 'aluno.criar'):
            abort(403)
        aluno = Aluno()
        ok, erro = _aplicar_dados_aluno(aluno, request.form, is_novo=True)
        if not ok:
            flash(erro, 'danger')
            return redirect(url_for('admin.alunos'))
        try:
            db.session.add(aluno)
            db.session.flush()
            _sincronizar_matriculas(aluno, request.form.getlist('curso_ids'))
            _matricular_turmas_iniciais(aluno, request.form.getlist('turma_ids'))
            db.session.commit()
            flash('Aluno cadastrado.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('CPF já cadastrado para outro aluno.', 'danger')
        return redirect(url_for('admin.alunos'))

    filtro_status = request.args.get('status', '')
    turmas = Turma.query.order_by(Turma.nome).all()
    cursos = Curso.query.order_by(Curso.titulo).all()
    # Eager-load batched: cada relação vira UMA query com IN(...).
    # O template usa em cada linha (e dentro do modal):
    #   - a.turmas_ativas / a.vinculos_historico → matriculas_turma + turma
    #   - a.matriculas (curso) + m.curso.titulo → matriculas (curso) + curso
    # Sem isso, são ~10 queries por aluno.
    from sqlalchemy.orm import selectinload, joinedload
    q = Aluno.query.options(
        selectinload(Aluno.matriculas_turma).joinedload(MatriculaTurma.turma),
        selectinload(Aluno.matriculas).joinedload(MatriculaCurso.curso),
        joinedload(Aluno.turma),
    )

    if filtro_status in STATUS_ALUNO_CHOICES:
        # Filtro via status derivado das MatriculaTurma.
        # Para alunos antigos sem nenhuma matrícula (raros após o backfill),
        # cai no fallback Aluno.status pra não sumirem das listagens.
        tem_ativa = MatriculaTurma.query.filter(
            MatriculaTurma.aluno_id == Aluno.id,
            MatriculaTurma.status == 'ativo',
        ).exists()
        sem_matricula = ~MatriculaTurma.query.filter(
            MatriculaTurma.aluno_id == Aluno.id,
        ).exists()

        if filtro_status == 'ativo':
            q = q.filter(or_(tem_ativa, and_(sem_matricula, Aluno.status == 'ativo')))
        else:
            tem_status = MatriculaTurma.query.filter(
                MatriculaTurma.aluno_id == Aluno.id,
                MatriculaTurma.status == filtro_status,
            ).exists()
            q = q.filter(or_(
                and_(tem_status, ~tem_ativa),
                and_(sem_matricula, Aluno.status == filtro_status),
            ))

    alunos = q.order_by(Aluno.nome).all()
    # Precomputa status_derivado em UMA query para evitar N+1 ao renderizar
    # (a property faz iteração sobre o backref dinâmico matriculas_turma).
    status_map = status_derivado_por_aluno([a.id for a in alunos])
    return render_template('admin_alunos.html',
                           alunos=alunos, turmas=turmas, cursos=cursos,
                           sexos=SEXOS_CHOICES, cor_racas=COR_RACA_CHOICES,
                           status_choices=STATUS_ALUNO_CHOICES, ufs=UFS_BR,
                           filtro_status=filtro_status,
                           status_map=status_map)


@admin_bp.route('/alunos/editar/<int:id>', methods=['POST'])
@login_required
@requires('aluno.editar')
def editar_aluno(id):
    aluno = Aluno.query.get_or_404(id)
    status_anterior = aluno.status
    ok, erro = _aplicar_dados_aluno(aluno, request.form)
    if not ok:
        flash(erro, 'danger')
        return redirect(url_for('admin.alunos'))
    try:
        _sincronizar_matriculas(aluno, request.form.getlist('curso_ids'))
        db.session.commit()
        flash('Aluno atualizado.', 'success')
        # Auto-cancelar plano quando aluno vira evadido
        if status_anterior == 'ativo' and aluno.status == 'evadido':
            res = services_financeiro.cancelar_plano_aluno(
                aluno, motivo=f'Aluno marcado como {aluno.status}.')
            if res['plano_cancelado']:
                msg = (f"Plano cancelado automaticamente: "
                       f"{res['mensalidades_canceladas']} mensalidade(s), "
                       f"{res['boletos_cancelados']} boleto(s).")
                flash(msg, 'info')
    except IntegrityError:
        db.session.rollback()
        flash('CPF já cadastrado para outro aluno.', 'danger')
    return redirect(url_for('admin.alunos'))


@admin_bp.route('/alunos/excluir/<int:id>', methods=['POST'])
@login_required
@requires('aluno.excluir')
def excluir_aluno(id):
    aluno = Aluno.query.get_or_404(id)

    # Bloqueia exclusão se o aluno tem histórico financeiro pago.
    # Apagar destruiria registro contábil — preferimos preservar e sugerir
    # marcar como "evadido" (que mantém histórico mas tira dos dashboards).
    tem_boleto_pago = (db.session.query(Boleto.id)
                       .join(Mensalidade, Mensalidade.id == Boleto.mensalidade_id)
                       .filter(Mensalidade.aluno_id == aluno.id,
                               Boleto.status == 'pago')
                       .first() is not None)
    if tem_boleto_pago:
        flash(
            f'Não é possível excluir {aluno.nome} porque já existem boletos '
            'pagos no histórico (registro contábil). Marque como evadido '
            'para tirar dos dashboards mantendo o histórico financeiro.',
            'warning'
        )
        return redirect(url_for('admin.alunos') + f'#aluno-{aluno.id}')

    nome = aluno.nome

    try:
        # 1) Cancela plano ativo + boletos em aberto (no Cora, se houver)
        try:
            services_financeiro.cancelar_plano_aluno(aluno)
        except Exception:
            # Se Cora falhar, segue — vamos apagar tudo localmente mesmo.
            db.session.rollback()

        # 2) Apaga dependências em ordem (filhos antes dos pais)
        ProgressoVideoaula.query.filter_by(aluno_id=aluno.id).delete(
            synchronize_session=False)
        MatriculaCurso.query.filter_by(aluno_id=aluno.id).delete(
            synchronize_session=False)
        Nota.query.filter_by(aluno_id=aluno.id).delete(synchronize_session=False)
        Frequencia.query.filter_by(aluno_id=aluno.id).delete(
            synchronize_session=False)
        Observacao.query.filter_by(aluno_id=aluno.id).delete(
            synchronize_session=False)
        AlunoResponsavel.query.filter_by(aluno_id=aluno.id).delete(
            synchronize_session=False)

        # Mensalidades têm cascade='all, delete-orphan' nos boletos, então
        # apagar a mensalidade já apaga os boletos vinculados.
        Mensalidade.query.filter_by(aluno_id=aluno.id).delete(
            synchronize_session=False)
        PlanoPagamento.query.filter_by(aluno_id=aluno.id).delete(
            synchronize_session=False)

        # 3) Apaga o usuário vinculado (se existir), depois o próprio aluno
        user_vinculado = aluno.user_id
        db.session.delete(aluno)
        if user_vinculado:
            user = User.query.get(user_vinculado)
            if user:
                db.session.delete(user)

        db.session.commit()
        flash(f'Aluno {nome} excluído.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Erro ao excluir aluno %s: %s', id, e)
        flash(
            'Não foi possível excluir o aluno por causa de vínculos no banco. '
            'Tente marcar como "evadido" — o aluno some dos dashboards mas '
            'o histórico fica preservado.',
            'danger'
        )
    return redirect(url_for('admin.alunos'))


# ── Vínculos do aluno (matrículas em turma) ───────────────────────────────────

@admin_bp.route('/alunos/<int:id>/vinculos', methods=['GET', 'POST'])
@login_required
@requires('aluno.ver')
def aluno_vinculos(id):
    aluno = Aluno.query.get_or_404(id)

    if request.method == 'POST':
        if not pode(current_user, 'aluno.editar'):
            abort(403)
        action = (request.form.get('action') or '').strip()
        observacao = (request.form.get('observacao') or '').strip() or None
        data_saida_raw = (request.form.get('data_saida') or '').strip()
        data_saida = None
        if data_saida_raw:
            try:
                data_saida = date.fromisoformat(data_saida_raw)
            except ValueError:
                flash('Data de saída inválida.', 'danger')
                return redirect(url_for('admin.aluno_vinculos', id=aluno.id))

        try:
            if action == 'matricular':
                turma_id = request.form.get('turma_id')
                turma = Turma.query.get(int(turma_id)) if turma_id else None
                if not turma:
                    flash('Turma inválida.', 'danger')
                    return redirect(url_for('admin.aluno_vinculos', id=aluno.id))
                matricular_em_turma(aluno, turma, observacao=observacao)
                if not aluno.turma_id:
                    aluno.turma_id = turma.id
                db.session.commit()
                flash(f'{aluno.nome} matriculado em {turma.nome}.', 'success')

            elif action in ('formar', 'evadir', 'transferir'):
                m_id = request.form.get('matricula_id')
                matricula = MatriculaTurma.query.get_or_404(int(m_id))
                if matricula.aluno_id != aluno.id:
                    abort(403)
                fn = {
                    'formar': formar_em_turma,
                    'evadir': evadir_em_turma,
                    'transferir': transferir_em_turma,
                }[action]
                fn(matricula, data_saida=data_saida, observacao=observacao)

                # Cancela o plano DESTA matrícula quando ela evadir.
                # Outros planos do aluno (de outras turmas ativas) continuam.
                if action == 'evadir':
                    try:
                        res = services_financeiro.cancelar_plano_matricula(
                            matricula,
                            motivo=f'Matrícula em {matricula.turma.nome} evadida.'
                        )
                        if res.get('plano_cancelado'):
                            flash(
                                f"Plano da matrícula cancelado: "
                                f"{res['mensalidades_canceladas']} mensalidade(s), "
                                f"{res['boletos_cancelados']} boleto(s).",
                                'info'
                            )
                    except Exception:
                        db.session.rollback()
                        current_app.logger.exception(
                            'Falha ao cancelar plano da matrícula #%s', matricula.id)

                # Se o aluno ficou sem nenhuma matrícula ativa, sincroniza
                # Aluno.turma_id (legacy) pra manter compat com filtros antigos.
                if not aluno.vinculos_ativos:
                    aluno.turma_id = None

                db.session.commit()
                labels = {'formar': 'formado', 'evadir': 'evadido',
                          'transferir': 'transferido'}
                flash(
                    f'Vínculo com {matricula.turma.nome} marcado como '
                    f'{labels[action]}.',
                    'success'
                )

            else:
                flash('Ação desconhecida.', 'danger')

        except ValueError as ex:
            db.session.rollback()
            flash(str(ex), 'danger')

        return redirect(url_for('admin.aluno_vinculos', id=aluno.id))

    # GET — turmas disponíveis pra nova matrícula (todas, exceto as já ativas)
    ativas_ids = {m.turma_id for m in aluno.vinculos_ativos}
    turmas_disponiveis = [t for t in Turma.query.order_by(Turma.nome).all()
                          if t.id not in ativas_ids]
    return render_template('admin_aluno_vinculos.html',
                           aluno=aluno,
                           turmas_disponiveis=turmas_disponiveis,
                           hoje=date.today())


# ── Turmas ─────────────────────────────────────────────────────────────────────

def _sincronizar_encontros(turma, datas_str):
    """Substitui os encontros da turma pelas datas recebidas (YYYY-MM-DD).

    Ignora strings vazias e duplicadas, e ordena cronologicamente.
    """
    datas_validas = []
    vistos = set()
    for s in datas_str:
        s = (s or '').strip()
        if not s or s in vistos:
            continue
        try:
            d = date.fromisoformat(s)
        except ValueError:
            continue
        vistos.add(s)
        datas_validas.append(d)
    datas_validas.sort()

    # Remove os atuais e regrava (mais simples que diff incremental).
    # Flush entre delete e insert é obrigatório: sem ele o SQLAlchemy pode
    # emitir os INSERTs antes dos DELETEs no mesmo flush e violar o
    # UniqueConstraint(turma_id, data) quando datas iguais são re-salvas.
    for enc in list(turma.encontros):
        db.session.delete(enc)
    db.session.flush()
    for i, d in enumerate(datas_validas):
        db.session.add(EncontroTurma(turma_id=turma.id, data=d, ordem=i))


@admin_bp.route('/turmas', methods=['GET', 'POST'])
@login_required
@requires('turma.ver')
def turmas():
    if request.method == 'POST':
        if not pode(current_user, 'turma.criar'):
            abort(403)
        nome = (request.form.get('nome') or '').strip()
        if not nome:
            flash('Nome da turma é obrigatório.', 'danger')
            return redirect(url_for('admin.turmas'))
        turma = Turma(nome=nome)
        db.session.add(turma)
        db.session.flush()
        _sincronizar_encontros(turma, request.form.getlist('encontros'))
        db.session.commit()
        flash('Turma criada.', 'success')
        return redirect(url_for('admin.turmas'))

    turmas = Turma.query.order_by(Turma.nome).all()
    return render_template('admin_turmas.html', turmas=turmas)


@admin_bp.route('/turmas/<int:id>')
@login_required
@requires('turma.ver')
def turma_detalhe(id):
    turma = Turma.query.get_or_404(id)
    alunos = (Aluno.query.filter_by(turma_id=id)
              .order_by(Aluno.nome).all())
    return render_template('admin_turma_detalhe.html', turma=turma, alunos=alunos)


@admin_bp.route('/turmas/editar/<int:id>', methods=['POST'])
@login_required
@requires('turma.editar')
def editar_turma(id):
    turma = Turma.query.get_or_404(id)
    nome = (request.form.get('nome') or '').strip()
    if not nome:
        flash('Nome da turma é obrigatório.', 'danger')
        return redirect(request.referrer or url_for('admin.turmas'))
    turma.nome = nome
    _sincronizar_encontros(turma, request.form.getlist('encontros'))
    db.session.commit()
    flash('Turma atualizada.', 'success')
    return redirect(request.referrer or url_for('admin.turmas'))


@admin_bp.route('/turmas/<int:id>/encontros.json')
@login_required
def turma_encontros_json(id):
    """Endpoint usado pelo painel do professor para listar datas configuradas."""
    if not current_user.is_authenticated or current_user.tipo not in ('admin', 'professor'):
        abort(403)
    turma = Turma.query.get_or_404(id)
    return jsonify({
        'turma_id': turma.id,
        'turma_nome': turma.nome,
        'encontros': [
            {'data': e.data.isoformat(), 'ordem': e.ordem}
            for e in turma.encontros
        ],
    })


@admin_bp.route('/turmas/excluir/<int:id>', methods=['POST'])
@login_required
@requires('turma.excluir')
def excluir_turma(id):
    turma = Turma.query.get_or_404(id)
    if turma.alunos:
        flash('Não é possível excluir turma com alunos vinculados.', 'danger')
        return redirect(url_for('admin.turmas'))
    db.session.delete(turma)
    db.session.commit()
    flash('Turma removida.', 'success')
    return redirect(url_for('admin.turmas'))


# ── Professores ────────────────────────────────────────────────────────────────

def _sincronizar_turmas_professor(professor, turma_ids):
    """Atualiza professor.turmas (N:N) com a lista recebida e mantém
    professor.turma_id (campo legado) apontando para a primeira da lista."""
    ids = {int(t) for t in turma_ids if t}
    turmas_objs = Turma.query.filter(Turma.id.in_(ids)).all() if ids else []
    professor.turmas = turmas_objs
    professor.turma_id = turmas_objs[0].id if turmas_objs else None


@admin_bp.route('/professores', methods=['GET', 'POST'])
@login_required
@requires('professor.ver')
def professores():
    if request.method == 'POST':
        if not pode(current_user, 'professor.criar'):
            abort(403)
        nome = request.form.get('nome')
        turma_ids = request.form.getlist('turma_ids')
        user_id = request.form.get('user_id', type=int) or None
        disciplina_ids = request.form.getlist('disciplina_ids')

        if user_id and Professor.query.filter_by(user_id=user_id).first():
            flash('Esse usuário já está vinculado a outro professor.', 'danger')
            return redirect(url_for('admin.professores'))

        professor = Professor(nome=nome, user_id=user_id)
        db.session.add(professor)
        db.session.flush()

        _sincronizar_turmas_professor(professor, turma_ids)

        for disc_id in disciplina_ids:
            disciplina = Disciplina.query.get(disc_id)
            if disciplina:
                professor.disciplinas.append(disciplina)

        db.session.commit()
        flash('Professor cadastrado.', 'success')
        return redirect(url_for('admin.professores'))

    professores = Professor.query.order_by(Professor.nome).all()
    disciplinas = Disciplina.query.order_by(Disciplina.nome).all()
    turmas = Turma.query.order_by(Turma.nome).all()
    users_disponiveis = User.query.filter_by(tipo='professor').filter(
        ~User.id.in_(db.session.query(Professor.user_id).filter(Professor.user_id.isnot(None)))
    ).order_by(User.nome).all()
    return render_template('admin_professores.html',
                           professores=professores, disciplinas=disciplinas, turmas=turmas,
                           users_disponiveis=users_disponiveis)


@admin_bp.route('/professores/editar/<int:id>', methods=['POST'])
@login_required
@requires('professor.editar')
def editar_professor(id):
    professor = Professor.query.get_or_404(id)
    professor.nome = request.form.get('nome')

    novo_user_id = request.form.get('user_id', type=int) or None
    if novo_user_id != professor.user_id:
        if novo_user_id and Professor.query.filter(
                Professor.user_id == novo_user_id, Professor.id != professor.id).first():
            flash('Esse usuário já está vinculado a outro professor.', 'danger')
            return redirect(url_for('admin.professores'))
        professor.user_id = novo_user_id

    _sincronizar_turmas_professor(professor, request.form.getlist('turma_ids'))

    disciplina_ids = request.form.getlist('disciplina_ids')
    professor.disciplinas.clear()
    for disc_id in disciplina_ids:
        disciplina = Disciplina.query.get(disc_id)
        if disciplina:
            professor.disciplinas.append(disciplina)

    db.session.commit()
    flash('Professor atualizado.', 'success')
    return redirect(url_for('admin.professores'))


@admin_bp.route('/professores/excluir/<int:id>', methods=['POST'])
@login_required
@requires('professor.excluir')
def excluir_professor(id):
    professor = Professor.query.get_or_404(id)
    db.session.delete(professor)
    db.session.commit()
    flash('Professor removido.', 'success')
    return redirect(url_for('admin.professores'))


# ── Disciplinas ────────────────────────────────────────────────────────────────

@admin_bp.route('/disciplinas', methods=['GET', 'POST'])
@login_required
@requires('disciplina.ver')
def disciplinas():
    if request.method == 'POST':
        if not pode(current_user, 'disciplina.criar'):
            abort(403)
        nome = request.form.get('nome')
        disciplina = Disciplina(nome=nome)
        db.session.add(disciplina)
        db.session.commit()
        flash('Disciplina criada.', 'success')
        return redirect(url_for('admin.disciplinas'))

    disciplinas = Disciplina.query.order_by(Disciplina.nome).all()
    return render_template('admin_disciplinas.html', disciplinas=disciplinas)


# ── Responsáveis ───────────────────────────────────────────────────────────────

@admin_bp.route('/responsaveis', methods=['GET', 'POST'])
@login_required
@requires('responsavel.ver')
def responsaveis():
    if request.method == 'POST':
        if not pode(current_user, 'responsavel.criar'):
            abort(403)
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        email = request.form.get('email', '').strip().lower() or None
        aluno_ids = request.form.getlist('aluno_ids')

        responsavel = Responsavel(nome=nome, telefone=telefone, email=email)
        db.session.add(responsavel)
        db.session.flush()

        for aluno_id in aluno_ids:
            aluno = Aluno.query.get(aluno_id)
            if aluno:
                responsavel.alunos.append(aluno)

        db.session.commit()
        flash('Responsável cadastrado com sucesso.', 'success')
        return redirect(url_for('admin.responsaveis'))

    responsaveis = Responsavel.query.all()
    alunos = Aluno.query.all()
    return render_template('admin_responsaveis.html', responsaveis=responsaveis, alunos=alunos)


# ── Usuários ───────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios', methods=['GET', 'POST'])
@login_required
@requires('usuario.gerenciar')
def usuarios():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'criar':
            nome = request.form.get('nome').strip()
            email = request.form.get('email').strip().lower()
            senha = request.form.get('senha')
            tipo = request.form.get('tipo')
            aluno_id_form = request.form.get('aluno_id', type=int)
            professor_id_form = request.form.get('professor_id', type=int)

            if tipo not in ROLES_CRIAVEIS_ADMIN:
                flash('Tipo de usuário inválido.', 'danger')
                return redirect(url_for('admin.usuarios'))

            if User.query.filter_by(email=email).first():
                flash('Este e-mail já está cadastrado.', 'warning')
                return redirect(url_for('admin.usuarios'))

            hashed = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user = User(nome=nome, email=email, senha=hashed, tipo=tipo)
            db.session.add(user)
            db.session.flush()

            if tipo == 'aluno' and aluno_id_form:
                aluno = Aluno.query.get(aluno_id_form)
                if aluno and aluno.user_id is None:
                    aluno.user_id = user.id

            if tipo == 'professor':
                if professor_id_form:
                    prof = Professor.query.get(professor_id_form)
                    if prof and prof.user_id is None:
                        prof.user_id = user.id
                else:
                    db.session.add(Professor(nome=nome, user_id=user.id))

            db.session.commit()
            flash(f'Acesso criado para {nome}.', 'success')

        elif action == 'editar':
            user_id = request.form.get('user_id')
            user = User.query.get(user_id)
            if user and user.tipo != 'admin':
                user.nome = request.form.get('nome').strip()
                user.email = request.form.get('email').strip().lower()
                nova_senha = request.form.get('senha', '').strip()
                if nova_senha:
                    user.senha = bcrypt.hashpw(nova_senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                db.session.commit()
                flash('Usuário atualizado.', 'success')
            else:
                flash('Usuário não encontrado.', 'danger')

        elif action == 'excluir':
            user_id = request.form.get('user_id')
            user = User.query.get(user_id)
            if user and user.tipo != 'admin':
                db.session.delete(user)
                db.session.commit()
                flash('Usuário removido.', 'success')
            else:
                flash('Usuário não encontrado ou não pode ser removido.', 'danger')

        return redirect(url_for('admin.usuarios'))

    usuarios = User.query.filter(User.tipo != 'admin').order_by(User.tipo, User.nome).all()
    professores = Professor.query.order_by(Professor.nome).all()
    responsaveis = Responsavel.query.order_by(Responsavel.nome).all()
    alunos_sem_acesso = Aluno.query.filter_by(user_id=None).order_by(Aluno.nome).all()
    professores_sem_acesso = Professor.query.filter_by(user_id=None).order_by(Professor.nome).all()
    emails_com_acesso = {u.email for u in usuarios}
    return render_template('admin_usuarios.html',
                           usuarios=usuarios,
                           professores=professores,
                           responsaveis=responsaveis,
                           alunos_sem_acesso=alunos_sem_acesso,
                           professores_sem_acesso=professores_sem_acesso,
                           emails_com_acesso=emails_com_acesso,
                           roles_label=ROLES_LABEL)


# ── Permissões customizadas por usuário ────────────────────────────────────────

@admin_bp.route('/usuarios/<int:user_id>/permissoes', methods=['GET', 'POST'])
@login_required
@requires('usuario.gerenciar')
def usuario_permissoes(user_id):
    user = User.query.get_or_404(user_id)

    # Regras de quem pode ser editado.
    if user.tipo == 'admin':
        flash('Admins têm acesso total imutável — não podem ser customizados.', 'warning')
        return redirect(url_for('admin.usuarios'))
    if user.tipo not in ROLES_ADMIN_LIKE:
        flash('Customização de permissões só vale para papéis administrativos '
              '(coordenador, gestor, secretário).', 'warning')
        return redirect(url_for('admin.usuarios'))
    if user.id == current_user.id:
        flash('Você não pode editar suas próprias permissões.', 'warning')
        return redirect(url_for('admin.usuarios'))

    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        try:
            if action == 'personalizar':
                services_permissoes.snapshot_permissoes_papel(user)
                flash(f'Permissões de {user.nome} agora são personalizadas. '
                      'Ajuste a matriz abaixo.', 'success')

            elif action == 'salvar':
                chaves = request.form.getlist('permissoes')
                aplicadas = services_permissoes.salvar_permissoes_customizadas(user, chaves)
                flash(f'Permissões salvas: {len(aplicadas)} concedidas.', 'success')

            elif action == 'restaurar':
                services_permissoes.restaurar_padrao_papel(user)
                flash(f'Permissões de {user.nome} voltaram ao padrão do papel '
                      f'({ROLES_LABEL.get(user.tipo, user.tipo)}).', 'success')

            else:
                flash('Ação desconhecida.', 'danger')

        except services_permissoes.PermissoesError as e:
            flash(str(e), 'danger')

        return redirect(url_for('admin.usuario_permissoes', user_id=user.id))

    # GET — monta a view.
    efetivas = services_permissoes.permissoes_efetivas(user)
    padrao_papel = set(PERMISSOES.get(user.tipo, set()))

    return render_template(
        'admin_usuario_permissoes.html',
        usuario=user,
        catalogo=PERMISSOES_CATALOGO,
        efetivas=efetivas,
        padrao_papel=padrao_papel,
        papel_label=ROLES_LABEL.get(user.tipo, user.tipo),
    )


# ── Cursos ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/cursos', methods=['GET', 'POST'])
@login_required
@requires('curso.ver')
def cursos():
    if request.method == 'POST':
        if not pode(current_user, 'curso.criar'):
            abort(403)
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        capa_url = request.form.get('capa_url', '').strip()
        if not titulo:
            flash('Título é obrigatório.', 'danger')
            return redirect(url_for('admin.cursos'))
        curso = Curso(titulo=titulo,
                      descricao=descricao or None,
                      capa_url=capa_url or None)
        db.session.add(curso)
        db.session.commit()
        flash('Curso criado com sucesso.', 'success')
        return redirect(url_for('admin.cursos'))

    todos_cursos = Curso.query.order_by(Curso.titulo).all()
    return render_template('admin_cursos.html', cursos=todos_cursos)


@admin_bp.route('/cursos/<int:curso_id>', methods=['GET', 'POST'])
@login_required
@requires('curso.ver')
def curso_detalhe(curso_id):
    curso = Curso.query.get_or_404(curso_id)

    if request.method == 'POST':
        action = request.form.get('action')

        # Coordenador/secretário podem matricular/desmatricular alunos no curso,
        # mas só quem tem 'curso.editar' pode mexer em módulos, vídeos e dados.
        if action in ('matricular', 'desmatricular'):
            if not pode(current_user, 'matricula_curso.gerenciar'):
                abort(403)
        else:
            if not pode(current_user, 'curso.editar'):
                abort(403)

        if action == 'editar_curso':
            titulo = request.form.get('titulo', '').strip()
            if titulo:
                curso.titulo = titulo
            curso.descricao = request.form.get('descricao', '').strip() or None
            curso.capa_url = request.form.get('capa_url', '').strip() or None
            curso.ativo = 'ativo' in request.form
            db.session.commit()
            flash('Curso atualizado.', 'success')

        elif action == 'criar_modulo':
            titulo = request.form.get('titulo', '').strip()
            if titulo:
                ordem = len(curso.modulos)
                db.session.add(Modulo(curso_id=curso_id, titulo=titulo, ordem=ordem))
                db.session.commit()
                flash('Módulo adicionado.', 'success')

        elif action == 'criar_video':
            modulo_id = request.form.get('modulo_id', type=int)
            titulo = request.form.get('titulo', '').strip()
            video_url = request.form.get('video_url', '').strip()
            duracao = request.form.get('duracao_min', type=int)
            modulo = Modulo.query.get(modulo_id)
            if modulo and modulo.curso_id == curso_id and titulo and video_url:
                ordem = len(modulo.videoaulas)
                db.session.add(Videoaula(
                    modulo_id=modulo_id, titulo=titulo,
                    video_url=video_url, duracao_min=duracao, ordem=ordem))
                db.session.commit()
                flash('Videoaula adicionada.', 'success')

        elif action == 'excluir_modulo':
            modulo_id = request.form.get('modulo_id', type=int)
            modulo = Modulo.query.get(modulo_id)
            if modulo and modulo.curso_id == curso_id:
                db.session.delete(modulo)
                db.session.commit()
                flash('Módulo excluído.', 'success')

        elif action == 'excluir_video':
            video_id = request.form.get('video_id', type=int)
            video = Videoaula.query.get(video_id)
            if video and video.modulo.curso_id == curso_id:
                db.session.delete(video)
                db.session.commit()
                flash('Videoaula excluída.', 'success')

        elif action == 'matricular':
            aluno_id = request.form.get('aluno_id', type=int)
            if aluno_id:
                if not MatriculaCurso.query.filter_by(
                        aluno_id=aluno_id, curso_id=curso_id).first():
                    db.session.add(MatriculaCurso(aluno_id=aluno_id, curso_id=curso_id,
                                                   data_matricula=date.today()))
                    db.session.commit()
                    flash('Aluno matriculado no curso.', 'success')
                else:
                    flash('Aluno já está matriculado neste curso.', 'warning')

        elif action == 'desmatricular':
            matricula_id = request.form.get('matricula_id', type=int)
            matricula = MatriculaCurso.query.get(matricula_id)
            if matricula and matricula.curso_id == curso_id:
                db.session.delete(matricula)
                db.session.commit()
                flash('Matrícula removida.', 'success')

        return redirect(url_for('admin.curso_detalhe', curso_id=curso_id))

    alunos_matriculados_ids = {m.aluno_id for m in curso.matriculas}
    alunos_disponiveis = (Aluno.query
                          .filter(Aluno.id.notin_(alunos_matriculados_ids))
                          .order_by(Aluno.nome).all())

    return render_template('admin_curso_detalhe.html',
                           curso=curso,
                           alunos_disponiveis=alunos_disponiveis)


@admin_bp.route('/cursos/<int:curso_id>/excluir', methods=['POST'])
@login_required
@requires('curso.excluir')
def excluir_curso(curso_id):
    curso = Curso.query.get_or_404(curso_id)
    db.session.delete(curso)
    db.session.commit()
    flash('Curso removido.', 'success')
    return redirect(url_for('admin.cursos'))


# ── Configurações do Sistema ───────────────────────────────────────────────────

@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
@requires('configuracao.gerenciar')
def configuracoes():
    cfg = ConfigSistema.query.first()
    if not cfg:
        cfg = ConfigSistema(nome='EducaMais')
        db.session.add(cfg)
        db.session.commit()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'salvar':
            nome = request.form.get('nome', '').strip()
            if nome:
                cfg.nome = nome

            logo_file = request.files.get('logo')
            if logo_file and logo_file.filename:
                if not _extensao_valida(logo_file.filename):
                    flash('Formato inválido. Use PNG, JPG, JPEG, WEBP ou SVG.', 'danger')
                    return redirect(url_for('admin.configuracoes'))

                # Valida tamanho manualmente (MAX_CONTENT_LENGTH cobre o global)
                logo_file.seek(0, 2)
                tamanho = logo_file.tell()
                logo_file.seek(0)
                if tamanho > 2 * 1024 * 1024:
                    flash('Arquivo muito grande. Máximo permitido: 2 MB.', 'danger')
                    return redirect(url_for('admin.configuracoes'))

                ext = logo_file.filename.rsplit('.', 1)[1].lower()

                # Remove logo anterior (se existir e tiver extensão diferente)
                if cfg.logo_path and cfg.logo_path != f'logo.{ext}':
                    storage.delete_upload(cfg.logo_path)

                nome_arquivo = f'logo.{ext}'
                cfg.logo_path = storage.save_upload(logo_file, nome_arquivo)

            db.session.commit()
            flash('Configurações salvas com sucesso.', 'success')

        elif action == 'remover_logo':
            if cfg.logo_path:
                storage.delete_upload(cfg.logo_path)
                cfg.logo_path = None
                db.session.commit()
            flash('Logo removida.', 'success')

        return redirect(url_for('admin.configuracoes'))

    # Usa g.licenca quando disponível (setado pelo before_request com o
    # estado fresco da validação atual). Fallback: info_licenca() — cache
    # de arquivo (não persiste em prod readonly, então pode vir vazio).
    from flask import g
    from app.services_licenca import info_licenca
    licenca_estado = getattr(g, 'licenca', None) or info_licenca() or {}
    return render_template('admin_configuracoes.html', cfg=cfg,
                           licenca_estado=licenca_estado)


# ── Vincular aluno/turma ───────────────────────────────────────────────────────

@admin_bp.route('/vincular', methods=['POST'])
@login_required
@requires('usuario.gerenciar')
def vincular_aluno_turma():
    aluno_id = request.form.get('aluno_id')
    turma_id = request.form.get('turma_id')
    aluno = Aluno.query.get(aluno_id)
    if aluno:
        aluno.turma_id = turma_id
        db.session.commit()
        flash('Aluno vinculado à turma.', 'success')
    else:
        flash('Aluno não encontrado.', 'danger')
    return redirect(url_for('admin.alunos'))


# ── Backup e restauração ───────────────────────────────────────────────────────

@admin_bp.route('/backup')
@login_required
@requires('backup.gerenciar')
def backup():
    backups = services_backup.listar_backups(current_app)
    return render_template('admin_backup.html', backups=backups)


@admin_bp.route('/backup/criar', methods=['POST'])
@login_required
@requires('backup.gerenciar')
def backup_criar():
    try:
        caminho = services_backup.criar_backup(current_app)
        flash(f'Backup criado: {caminho.name}', 'success')
    except Exception as e:
        flash(f'Erro ao criar backup: {e}', 'danger')
    return redirect(url_for('admin.backup'))


@admin_bp.route('/backup/baixar/<nome>')
@login_required
@requires('backup.gerenciar')
def backup_baixar(nome):
    try:
        caminho = services_backup.caminho_backup(current_app, nome)
    except ValueError:
        flash('Nome de arquivo inválido.', 'danger')
        return redirect(url_for('admin.backup'))
    if not caminho.exists():
        flash('Backup não encontrado.', 'danger')
        return redirect(url_for('admin.backup'))
    return send_file(caminho, as_attachment=True, download_name=nome)


@admin_bp.route('/backup/excluir/<nome>', methods=['POST'])
@login_required
@requires('backup.gerenciar')
def backup_excluir(nome):
    try:
        if services_backup.excluir_backup(current_app, nome):
            flash(f'Backup {nome} removido.', 'success')
        else:
            flash('Backup não encontrado.', 'warning')
    except ValueError:
        flash('Nome de arquivo inválido.', 'danger')
    return redirect(url_for('admin.backup'))


@admin_bp.route('/backup/restaurar', methods=['POST'])
@login_required
@requires('backup.gerenciar')
def backup_restaurar():
    arquivo = request.files.get('backup_file')
    confirmacao = request.form.get('confirmacao', '').strip().upper()

    if not arquivo or not arquivo.filename:
        flash('Selecione um arquivo de backup (.zip).', 'danger')
        return redirect(url_for('admin.backup'))
    if not arquivo.filename.lower().endswith('.zip'):
        flash('O arquivo precisa ser um .zip de backup.', 'danger')
        return redirect(url_for('admin.backup'))
    if confirmacao != 'RESTAURAR':
        flash('Digite RESTAURAR no campo de confirmação para prosseguir.', 'warning')
        return redirect(url_for('admin.backup'))

    resultado = services_backup.restaurar_backup(current_app, arquivo)
    if not resultado['ok']:
        flash(f'Falha ao restaurar: {resultado["mensagem"]}', 'danger')
        return redirect(url_for('admin.backup'))

    # Sessão atual ficou inválida (IDs podem ter trocado) — força logout
    logout_user()
    flash(
        f'Backup restaurado. Pre-backup do estado anterior: {resultado["pre_backup"]}. '
        'Faça login novamente.',
        'success',
    )
    return redirect(url_for('auth.login'))


# ── Financeiro ─────────────────────────────────────────────────────────────────

COMPROVANTE_EXTENSOES = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}
COMPROVANTE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

MESES_PT = [
    'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]


def _comprovante_valido(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in COMPROVANTE_EXTENSOES)


def _parse_decimal(valor_str, default=None):
    if not valor_str:
        return default
    try:
        return Decimal(str(valor_str).replace(',', '.'))
    except (InvalidOperation, ValueError):
        return default


def _periodo_atual():
    hoje = date.today()
    return hoje.month, hoje.year


@admin_bp.route('/financeiro')
@login_required
@requires('financeiro.ver')
def financeiro():
    services_financeiro.seed_categorias_padrao()
    # Default = mês corrente (atualiza automaticamente no início do mês).
    # Aceita ?mes=&ano= pra revisitar períodos passados.
    hoje = date.today()
    try:
        mes = int(request.args.get('mes', hoje.month))
        ano = int(request.args.get('ano', hoje.year))
        if not 1 <= mes <= 12:
            mes = hoje.month
        if not 2020 <= ano <= 2099:
            ano = hoje.year
    except ValueError:
        mes, ano = hoje.month, hoje.year

    kpis = services_financeiro.kpis_mes(mes, ano)
    # Últimas 8 movimentações do mês selecionado (vs. globais antes)
    inicio = date(ano, mes, 1)
    from calendar import monthrange as _mr
    fim = date(ano, mes, _mr(ano, mes)[1])
    ult = (Movimentacao.query
           .filter(Movimentacao.data >= inicio, Movimentacao.data <= fim)
           .order_by(Movimentacao.data.desc(), Movimentacao.id.desc())
           .limit(8).all())

    # Mês anterior / próximo (para navegação)
    mes_ant, ano_ant = (12, ano - 1) if mes == 1 else (mes - 1, ano)
    mes_prox, ano_prox = (1, ano + 1) if mes == 12 else (mes + 1, ano)

    return render_template(
        'admin_financeiro.html',
        kpis=kpis, mes=mes, ano=ano, mes_nome=MESES_PT[mes - 1],
        ultimas_movs=ult, meses=MESES_PT,
        mes_ant=mes_ant, ano_ant=ano_ant,
        mes_prox=mes_prox, ano_prox=ano_prox,
        mes_atual=hoje.month, ano_atual=hoje.year,
    )


# Mensalidades ----------------------------------------------------------------

@admin_bp.route('/financeiro/mensalidades')
@login_required
@requires('financeiro.ver')
def financeiro_mensalidades():
    mes = int(request.args.get('mes', date.today().month))
    ano = int(request.args.get('ano', date.today().year))
    mensalidades = (Mensalidade.query
                    .filter_by(mes=mes, ano=ano)
                    .join(Aluno).order_by(Aluno.nome).all())
    return render_template(
        'admin_financeiro_mensalidades.html',
        mensalidades=mensalidades, mes=mes, ano=ano,
        mes_nome=MESES_PT[mes - 1], meses=MESES_PT,
        mp_ativo=services_mercadopago.is_mp_active(),
    )


@admin_bp.route('/financeiro/mensalidades/lote', methods=['POST'])
@login_required
@requires('mensalidade.gerar_lote')
def financeiro_mensalidades_lote():
    mes = int(request.form.get('mes', date.today().month))
    ano = int(request.form.get('ano', date.today().year))
    valor_default = _parse_decimal(request.form.get('valor_default'))
    res = services_financeiro.gerar_mensalidades_lote(mes, ano, valor_default=valor_default)
    msg = f"Lote {mes:02d}/{ano}: {res['criadas']} criadas, {res['puladas']} já existiam."
    if res['alunos_sem_valor']:
        msg += f" Sem valor: {len(res['alunos_sem_valor'])}."
    if res['alunos_sem_responsavel']:
        msg += f" Sem responsável: {len(res['alunos_sem_responsavel'])}."
    flash(msg, 'success' if res['criadas'] else 'warning')
    return redirect(url_for('admin.financeiro_mensalidades', mes=mes, ano=ano))


@admin_bp.route('/financeiro/mensalidades/<int:id>/excluir', methods=['POST'])
@login_required
@requires('mensalidade.cancelar')
def financeiro_mensalidade_excluir(id):
    m = Mensalidade.query.get_or_404(id)
    mes, ano = m.mes, m.ano
    db.session.delete(m)  # cascade remove boletos
    db.session.commit()
    flash('Mensalidade removida.', 'success')
    return redirect(url_for('admin.financeiro_mensalidades', mes=mes, ano=ano))


# Plano de pagamento ----------------------------------------------------------

@admin_bp.route('/financeiro/planos/<int:aluno_id>')
@login_required
@requires('financeiro.ver')
def financeiro_plano(aluno_id):
    """Lista todas as matrículas ativas do aluno com seus planos (1 por matrícula).

    Histórico inclui planos cancelados/concluídos de qualquer matrícula do aluno.
    """
    aluno = Aluno.query.get_or_404(aluno_id)
    matriculas_ativas = aluno.vinculos_ativos
    # (matricula, plano_ativo_ou_None) pra cada matrícula ativa
    matriculas_com_plano = [
        (m, services_financeiro.plano_ativo_da_matricula(m))
        for m in matriculas_ativas
    ]
    historico = (PlanoPagamento.query
                 .filter_by(aluno_id=aluno.id)
                 .order_by(PlanoPagamento.criado_em.desc()).all())
    return render_template(
        'admin_financeiro_plano.html',
        aluno=aluno,
        matriculas_com_plano=matriculas_com_plano,
        historico=historico,
        meses=MESES_PT,
    )


@admin_bp.route('/financeiro/planos/matricula/<int:matricula_id>/criar',
                methods=['POST'])
@login_required
@requires('mensalidade.gerar_lote')
def financeiro_plano_criar(matricula_id):
    matricula = MatriculaTurma.query.get_or_404(matricula_id)
    aluno = matricula.aluno
    try:
        n = int(request.form.get('n_parcelas', 12))
        valor = _parse_decimal(request.form.get('valor_parcela'))
        if valor is None:
            raise ValueError('Informe o valor da parcela.')
        dia = int(request.form.get('dia_vencimento', 10))
        mes_ini = request.form.get('mes_inicio')
        ano_ini = request.form.get('ano_inicio')
        mes_ini = int(mes_ini) if mes_ini else None
        ano_ini = int(ano_ini) if ano_ini else None
        observacao = (request.form.get('observacao') or '').strip() or None
        responsavel_id = request.form.get('responsavel_id')
        responsavel_id = int(responsavel_id) if responsavel_id else None

        res = services_financeiro.criar_plano_pagamento(
            matricula=matricula, n_parcelas=n, valor_parcela=valor,
            dia_vencimento=dia, mes_inicio=mes_ini, ano_inicio=ano_ini,
            observacao=observacao, responsavel_id=responsavel_id,
        )
        turma_nome = matricula.turma.nome if matricula.turma else '?'
        msg = (f"Plano criado para {turma_nome}: "
               f"{res['mensalidades_criadas']} mensalidade(s).")
        if res['boleto_emitido']:
            msg += f" Boleto da 1ª parcela emitido (#{res['boleto_emitido'].id})."
        if res['mensalidades_puladas']:
            msg += f" {len(res['mensalidades_puladas'])} já existiam e foram puladas."
        flash(msg, 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except CoraError as e:
        flash(f'Erro do Cora: {e}', 'warning')
    return redirect(url_for('admin.financeiro_plano', aluno_id=aluno.id))


@admin_bp.route('/financeiro/planos/matricula/<int:matricula_id>/cancelar',
                methods=['POST'])
@login_required
@requires('plano_pagamento.cancelar')
def financeiro_plano_cancelar(matricula_id):
    matricula = MatriculaTurma.query.get_or_404(matricula_id)
    aluno = matricula.aluno
    motivo = (request.form.get('motivo') or '').strip() or None
    res = services_financeiro.cancelar_plano_matricula(matricula, motivo=motivo)
    turma_nome = matricula.turma.nome if matricula.turma else '?'
    if not res['plano_cancelado']:
        flash(f'Matrícula em {turma_nome} não tinha plano ativo.', 'warning')
    else:
        msg = (f"Plano de {turma_nome} cancelado. "
               f"{res['mensalidades_canceladas']} mensalidade(s) "
               f"e {res['boletos_cancelados']} boleto(s) cancelados.")
        if res['erros_cora']:
            msg += f" {res['erros_cora']} erro(s) ao cancelar no Cora."
        flash(msg, 'success' if not res['erros_cora'] else 'warning')
    return redirect(url_for('admin.financeiro_plano', aluno_id=aluno.id))


# Boletos ---------------------------------------------------------------------

@admin_bp.route('/financeiro/boletos')
@login_required
@requires('financeiro.ver')
def financeiro_boletos():
    status = request.args.get('status', '')
    q = Boleto.query.order_by(Boleto.vencimento.desc(), Boleto.id.desc())
    if status:
        q = q.filter(Boleto.status == status)
    boletos = q.limit(200).all()
    return render_template('admin_financeiro_boletos.html',
                           boletos=boletos, status_filtro=status)


@admin_bp.route('/financeiro/boletos/emitir/<int:mensalidade_id>', methods=['POST'])
@login_required
@requires('boleto.emitir')
def financeiro_boleto_emitir(mensalidade_id):
    m = Mensalidade.query.get_or_404(mensalidade_id)
    try:
        b = services_financeiro.emitir_boleto(m)
        flash(f'Boleto emitido: {b.cora_boleto_id}', 'success')
    except CoraError as e:
        flash(f'Erro do Cora: {e}', 'danger')
    return redirect(url_for('admin.financeiro_mensalidades', mes=m.mes, ano=m.ano))


@admin_bp.route('/financeiro/boletos/<int:id>/cancelar', methods=['POST'])
@login_required
@requires('boleto.cancelar')
def financeiro_boleto_cancelar(id):
    b = Boleto.query.get_or_404(id)
    if services_financeiro.cancelar_boleto(b):
        flash('Boleto cancelado.', 'success')
    else:
        flash('Não foi possível cancelar (já pago?).', 'warning')
    return redirect(request.referrer or url_for('admin.financeiro_boletos'))


@admin_bp.route('/financeiro/boletos/sincronizar', methods=['POST'])
@login_required
@requires('boleto.sincronizar')
def financeiro_boletos_sincronizar():
    res = services_financeiro.sincronizar_status_boletos()
    flash(f"Sincronização: {res['pagos']} pagos, {res['vencidos']} vencidos, "
          f"{res['erros']} erros.", 'info')
    return redirect(request.referrer or url_for('admin.financeiro_boletos'))


# Cobrança manual (boleto colado / PIX copia-e-cola) --------------------------

@admin_bp.route('/financeiro/cobranca/registrar/<int:mensalidade_id>', methods=['POST'])
@login_required
@requires('boleto.emitir')
def financeiro_cobranca_registrar(mensalidade_id):
    m = Mensalidade.query.get_or_404(mensalidade_id)
    tipo = (request.form.get('tipo') or '').strip()
    if tipo not in ('boleto_manual', 'pix_manual'):
        flash('Tipo de cobrança inválido.', 'danger')
        return redirect(url_for('admin.financeiro_mensalidades', mes=m.mes, ano=m.ano))

    linha = (request.form.get('linha_digitavel') or '').strip() or None
    pix = (request.form.get('pix_copia_cola') or '').strip() or None

    pdf_path = None
    if tipo == 'boleto_manual':
        arquivo = request.files.get('pdf_boleto')
        if arquivo and arquivo.filename:
            ext = arquivo.filename.rsplit('.', 1)[-1].lower() if '.' in arquivo.filename else ''
            if ext != 'pdf':
                flash('PDF do boleto: aceitamos apenas arquivos .pdf.', 'danger')
                return redirect(url_for('admin.financeiro_mensalidades', mes=m.mes, ano=m.ano))
            arquivo.stream.seek(0, 2)
            size = arquivo.stream.tell()
            arquivo.stream.seek(0)
            if size > COMPROVANTE_MAX_BYTES:
                flash('PDF do boleto: tamanho máximo 5 MB.', 'danger')
                return redirect(url_for('admin.financeiro_mensalidades', mes=m.mes, ano=m.ano))
            nome = f'cob_{uuid.uuid4().hex[:12]}.pdf'
            pdf_path = storage.save_upload(arquivo, nome, subdir='cobrancas')

    try:
        services_financeiro.registrar_cobranca_manual(
            mensalidade=m, tipo=tipo,
            linha_digitavel=linha, pix_copia_cola=pix, pdf_path=pdf_path,
        )
        flash('Cobrança registrada.', 'success')
    except ValueError as e:
        if pdf_path:
            storage.delete_upload(pdf_path)
        flash(str(e), 'danger')
    return redirect(url_for('admin.financeiro_mensalidades', mes=m.mes, ano=m.ano))


@admin_bp.route('/financeiro/cobranca/<int:id>/pago', methods=['POST'])
@login_required
@requires('boleto.registrar_pagamento')
def financeiro_cobranca_pago(id):
    boleto = Boleto.query.get_or_404(id)
    if boleto.status == 'pago':
        flash('Esta cobrança já estava marcada como paga.', 'warning')
    else:
        services_financeiro.marcar_cobranca_paga(boleto)
        flash('Cobrança marcada como paga.', 'success')
    return redirect(request.referrer or url_for('admin.financeiro_boletos'))


# Inadimplentes ---------------------------------------------------------------

@admin_bp.route('/financeiro/inadimplentes')
@login_required
@requires('financeiro.ver')
def financeiro_inadimplentes():
    escopo = request.args.get('escopo', 'todos')
    mes = int(request.args.get('mes', date.today().month))
    ano = int(request.args.get('ano', date.today().year))
    lista = services_financeiro.inadimplentes(escopo=escopo, mes=mes, ano=ano)
    return render_template(
        'admin_financeiro_inadimplentes.html',
        inadimplentes=lista, escopo=escopo, mes=mes, ano=ano,
        mes_nome=MESES_PT[mes - 1], meses=MESES_PT,
    )


# Fluxo de caixa --------------------------------------------------------------

@admin_bp.route('/financeiro/fluxo-caixa')
@login_required
@requires('financeiro.ver')
def financeiro_fluxo_caixa():
    mes = int(request.args.get('mes', date.today().month))
    ano = int(request.args.get('ano', date.today().year))
    from calendar import monthrange
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, monthrange(ano, mes)[1])
    fluxo = services_financeiro.fluxo_caixa(inicio, fim)
    categorias = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()
    return render_template(
        'admin_financeiro_fluxo.html',
        fluxo=fluxo, mes=mes, ano=ano, mes_nome=MESES_PT[mes - 1],
        meses=MESES_PT, categorias=categorias, hoje=date.today(),
    )


@admin_bp.route('/financeiro/movimentacao/nova', methods=['POST'])
@login_required
@requires('movimentacao.criar')
def financeiro_movimentacao_nova():
    tipo = request.form.get('tipo', 'saida')
    descricao = request.form.get('descricao', '').strip()
    valor = _parse_decimal(request.form.get('valor'))
    data_str = request.form.get('data')
    categoria_id = request.form.get('categoria_id') or None

    if not descricao or not valor or not data_str or tipo not in ('entrada', 'saida'):
        flash('Preencha tipo, descrição, valor e data.', 'danger')
        return redirect(url_for('admin.financeiro_fluxo_caixa'))

    try:
        data_lanc = date.fromisoformat(data_str)
    except ValueError:
        flash('Data inválida.', 'danger')
        return redirect(url_for('admin.financeiro_fluxo_caixa'))

    # Comprovante opcional
    comprovante_path = None
    arquivo = request.files.get('comprovante')
    if arquivo and arquivo.filename:
        if not _comprovante_valido(arquivo.filename):
            flash('Comprovante: aceitamos apenas PDF, PNG, JPG ou WEBP.', 'danger')
            return redirect(url_for('admin.financeiro_fluxo_caixa'))
        # tamanho
        arquivo.stream.seek(0, 2)
        size = arquivo.stream.tell()
        arquivo.stream.seek(0)
        if size > COMPROVANTE_MAX_BYTES:
            flash('Comprovante: tamanho máximo 5 MB.', 'danger')
            return redirect(url_for('admin.financeiro_fluxo_caixa'))

        ext = arquivo.filename.rsplit('.', 1)[1].lower()
        nome = f'comp_{uuid.uuid4().hex[:12]}.{ext}'
        comprovante_path = storage.save_upload(arquivo, nome, subdir='comprovantes')

    services_financeiro.registrar_movimentacao_manual(
        tipo=tipo, descricao=descricao, valor=valor, data=data_lanc,
        categoria_id=int(categoria_id) if categoria_id else None,
        comprovante_path=comprovante_path,
        criado_por_id=current_user.id,
    )
    flash('Movimentação registrada.', 'success')
    return redirect(url_for('admin.financeiro_fluxo_caixa',
                            mes=data_lanc.month, ano=data_lanc.year))


@admin_bp.route('/financeiro/movimentacao/<int:id>/excluir', methods=['POST'])
@login_required
@requires('movimentacao.excluir')
def financeiro_movimentacao_excluir(id):
    m = Movimentacao.query.get_or_404(id)
    if m.boleto_id:
        flash('Não é possível excluir movimentação vinda de boleto. '
              'Cancele o boleto, se for o caso.', 'warning')
        return redirect(url_for('admin.financeiro_fluxo_caixa'))
    # Apaga o arquivo de comprovante se existir
    if m.comprovante_path:
        storage.delete_upload(m.comprovante_path)
    db.session.delete(m)
    db.session.commit()
    flash('Movimentação removida.', 'success')
    return redirect(url_for('admin.financeiro_fluxo_caixa'))


# Exports financeiros (PDF + Excel) -------------------------------------------

def _nome_sistema():
    cfg = ConfigSistema.query.first()
    return (cfg.nome if cfg and cfg.nome else 'EducaMais')


def _periodo_export():
    """Lê mes/ano da query e clampa em valores válidos."""
    hoje = date.today()
    try:
        mes = int(request.args.get('mes', hoje.month))
        ano = int(request.args.get('ano', hoje.year))
        if not 1 <= mes <= 12:
            mes = hoje.month
        if not 2020 <= ano <= 2099:
            ano = hoje.year
    except ValueError:
        mes, ano = hoje.month, hoje.year
    return mes, ano


@admin_bp.route('/financeiro/fluxo-caixa/export/<formato>')
@login_required
@requires('financeiro.ver')
def financeiro_fluxo_export(formato):
    from calendar import monthrange as _mr
    from app import services_export

    mes, ano = _periodo_export()
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, _mr(ano, mes)[1])
    fluxo = services_financeiro.fluxo_caixa(inicio, fim)

    nome_base = f'fluxo-caixa_{ano}-{mes:02d}'
    if formato == 'pdf':
        buf = services_export.fluxo_para_pdf(fluxo, mes, ano, _nome_sistema())
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=True, download_name=f'{nome_base}.pdf')
    if formato == 'xlsx':
        buf = services_export.fluxo_para_xlsx(fluxo, mes, ano, _nome_sistema())
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name=f'{nome_base}.xlsx')
    abort(404)


@admin_bp.route('/financeiro/mensalidades/export/<formato>')
@login_required
@requires('financeiro.ver')
def financeiro_mensalidades_export(formato):
    from app import services_export
    mes, ano = _periodo_export()
    mensalidades = (Mensalidade.query
                    .filter_by(mes=mes, ano=ano)
                    .join(Aluno).order_by(Aluno.nome).all())

    nome_base = f'mensalidades_{ano}-{mes:02d}'
    if formato == 'pdf':
        buf = services_export.mensalidades_para_pdf(
            mensalidades, mes, ano, _nome_sistema())
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=True, download_name=f'{nome_base}.pdf')
    if formato == 'xlsx':
        buf = services_export.mensalidades_para_xlsx(
            mensalidades, mes, ano, _nome_sistema())
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name=f'{nome_base}.xlsx')
    abort(404)


@admin_bp.route('/financeiro/inadimplentes/export/pdf')
@login_required
@requires('financeiro.ver')
def financeiro_inadimplentes_export_pdf():
    from app import services_export
    escopo = request.args.get('escopo', 'todos')
    mes, ano = _periodo_export()
    lista = services_financeiro.inadimplentes(escopo=escopo, mes=mes, ano=ano)
    buf = services_export.inadimplentes_para_pdf(
        lista, MESES_PT[mes - 1], ano, _nome_sistema(), escopo=escopo,
    )
    sufixo = f'{ano}-{mes:02d}' if escopo == 'mes' else 'todos'
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f'inadimplentes_{sufixo}.pdf')


@admin_bp.route('/financeiro/boletos/export/xlsx')
@login_required
@requires('financeiro.ver')
def financeiro_boletos_export_xlsx():
    from app import services_export
    status = request.args.get('status', '')
    q = Boleto.query.order_by(Boleto.vencimento.desc(), Boleto.id.desc())
    if status:
        q = q.filter(Boleto.status == status)
    boletos = q.limit(2000).all()
    mes, ano = _periodo_export()
    buf = services_export.boletos_para_xlsx(boletos, mes, ano, _nome_sistema())
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name=f'boletos_{ano}-{mes:02d}.xlsx')


# Categorias ------------------------------------------------------------------

@admin_bp.route('/financeiro/categorias', methods=['GET', 'POST'])
@login_required
@requires('categoria_despesa.gerenciar')
def financeiro_categorias():
    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        cor = (request.form.get('cor') or '').strip() or None
        if not nome:
            flash('Informe o nome.', 'danger')
        elif CategoriaDespesa.query.filter_by(nome=nome).first():
            flash('Já existe categoria com esse nome.', 'warning')
        else:
            db.session.add(CategoriaDespesa(nome=nome, cor=cor))
            db.session.commit()
            flash('Categoria criada.', 'success')
        return redirect(url_for('admin.financeiro_categorias'))
    cats = CategoriaDespesa.query.order_by(CategoriaDespesa.nome).all()
    return render_template('admin_financeiro_categorias.html', categorias=cats)


@admin_bp.route('/financeiro/categorias/<int:id>/excluir', methods=['POST'])
@login_required
@requires('categoria_despesa.gerenciar')
def financeiro_categoria_excluir(id):
    cat = CategoriaDespesa.query.get_or_404(id)
    if cat.movimentacoes:
        flash('Categoria em uso por movimentações — desvincule antes.', 'warning')
        return redirect(url_for('admin.financeiro_categorias'))
    db.session.delete(cat)
    db.session.commit()
    flash('Categoria removida.', 'success')
    return redirect(url_for('admin.financeiro_categorias'))


# Cora — webhook + utilidades de mock -----------------------------------------

@admin_bp.route('/financeiro/cora/webhook', methods=['POST'])
def financeiro_cora_webhook():
    """Endpoint público que o Cora chama quando um boleto muda de status.

    Sem login (Cora não vai autenticar) — a segurança vem da validação de
    assinatura HMAC quando ``CORA_MODE=real``. Por enquanto, em modo mock,
    aceita qualquer POST com ``cora_id`` no JSON.
    """
    payload = request.get_json(silent=True) or {}
    cora_id = payload.get('cora_id') or payload.get('id')
    if not cora_id:
        return jsonify({'ok': False, 'erro': 'cora_id ausente'}), 400

    boleto = Boleto.query.filter_by(cora_boleto_id=cora_id).first()
    if not boleto:
        return jsonify({'ok': False, 'erro': 'boleto não encontrado'}), 404

    evento = (payload.get('evento') or 'pago').lower()
    if evento == 'pago':
        services_financeiro.registrar_pagamento_boleto(boleto)
    elif evento == 'cancelado':
        boleto.status = 'cancelado'
        db.session.commit()
    return jsonify({'ok': True, 'boleto_id': boleto.id, 'status': boleto.status})


@admin_bp.route('/financeiro/cora/simular-pagamento/<int:boleto_id>', methods=['POST'])
@login_required
@admin_required
def financeiro_cora_simular_pagamento(boleto_id):
    """Só funciona em modo mock — usado pra testar o fluxo localmente."""
    boleto = Boleto.query.get_or_404(boleto_id)
    cora = get_cora_client()
    if not isinstance(cora, CoraMockClient):
        flash('Simulação só funciona em CORA_MODE=mock.', 'warning')
        return redirect(request.referrer or url_for('admin.financeiro_boletos'))
    if not boleto.cora_boleto_id:
        flash('Boleto sem cora_id (não foi emitido).', 'warning')
        return redirect(request.referrer or url_for('admin.financeiro_boletos'))
    cora.simular_pagamento(boleto.cora_boleto_id)
    services_financeiro.registrar_pagamento_boleto(boleto)
    flash(f'Pagamento simulado para boleto #{boleto.id}.', 'success')
    return redirect(request.referrer or url_for('admin.financeiro_boletos'))


@admin_bp.route('/financeiro/cora/mock-pdf/<cora_id>')
@login_required
@admin_required
def financeiro_cora_mock_pdf(cora_id):
    """Placeholder — em produção o link_pdf vem direto do Cora."""
    return ('PDF fake do boleto %s.\nNo modo real, o Cora devolve um PDF aqui.'
            % cora_id, 200, {'Content-Type': 'text/plain; charset=utf-8'})


@admin_bp.route('/financeiro/cora/mock-boleto/<cora_id>')
@login_required
@admin_required
def financeiro_cora_mock_boleto(cora_id):
    return ('Página fake do boleto %s.\nNo modo real, é a URL pública do Cora.'
            % cora_id, 200, {'Content-Type': 'text/plain; charset=utf-8'})


# Mercado Pago — configuração + cobrança + webhook ----------------------------

@admin_bp.route('/configuracoes/mercadopago', methods=['GET', 'POST'])
@login_required
@requires('configuracao.gerenciar')
def configuracoes_mercadopago():
    integ = services_mercadopago.get_integracao_mp()

    if request.method == 'POST':
        ativo = request.form.get('ativo') == '1'
        ambiente = (request.form.get('ambiente') or 'production').strip()
        if ambiente not in ('production', 'sandbox'):
            ambiente = 'production'
        access_token_in = (request.form.get('access_token') or '').strip()
        webhook_secret_in = (request.form.get('webhook_secret') or '').strip()
        notification_url = (request.form.get('notification_url') or '').strip() or None

        # Token vazio significa "não alterar" — só substitui se o admin colou um novo.
        if access_token_in:
            integ.access_token = access_token_in
        if webhook_secret_in:
            integ.webhook_secret = webhook_secret_in

        # Marcar pra esvaziar (campo "limpar" enviado pelo botão dedicado)
        if request.form.get('limpar_token') == '1':
            integ.access_token = None
        if request.form.get('limpar_secret') == '1':
            integ.webhook_secret = None

        integ.ativo = ativo and bool(integ.access_token)
        integ.ambiente = ambiente
        integ.notification_url = notification_url
        integ.atualizado_por_id = current_user.id

        db.session.commit()
        if ativo and not integ.access_token:
            flash('Não dá pra ativar sem um Access Token. Cole o token e salve novamente.',
                  'warning')
        else:
            flash('Configurações do Mercado Pago salvas.', 'success')
        return redirect(url_for('admin.configuracoes_mercadopago'))

    return render_template(
        'admin_configuracoes_mp.html',
        integ=integ,
        webhook_url_publica=url_for('admin.financeiro_mp_webhook', _external=True),
    )


@admin_bp.route('/configuracoes/mercadopago/testar', methods=['POST'])
@login_required
@requires('configuracao.gerenciar')
def configuracoes_mercadopago_testar():
    integ = services_mercadopago.get_integracao_mp()
    if not (integ.access_token or '').strip():
        flash('Cole um Access Token e salve antes de testar.', 'warning')
        return redirect(url_for('admin.configuracoes_mercadopago'))
    try:
        client = services_mercadopago.MercadoPagoClient(integ)
        client.testar_conexao()
        flash('Conexão com Mercado Pago OK — token válido.', 'success')
    except MercadoPagoError as e:
        flash(f'Falha ao conectar: {e}', 'danger')
    return redirect(url_for('admin.configuracoes_mercadopago'))


@admin_bp.route('/financeiro/cobranca/mp/<int:mensalidade_id>', methods=['POST'])
@login_required
@requires('boleto.emitir')
def financeiro_cobranca_mp(mensalidade_id):
    m = Mensalidade.query.get_or_404(mensalidade_id)
    tipo = (request.form.get('tipo') or '').strip()
    if tipo not in ('pix', 'boleto'):
        flash('Tipo MP inválido. Use pix ou boleto.', 'danger')
        return redirect(url_for('admin.financeiro_mensalidades', mes=m.mes, ano=m.ano))
    try:
        b = services_financeiro.emitir_cobranca_mp(m, tipo)
        flash(f'Cobrança {tipo.upper()} criada no Mercado Pago (id {b.mp_payment_id}).',
              'success')
    except MercadoPagoError as e:
        flash(f'Mercado Pago: {e}', 'danger')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('admin.financeiro_mensalidades', mes=m.mes, ano=m.ano))


@admin_bp.route('/financeiro/mp/webhook', methods=['POST'])
def financeiro_mp_webhook():
    """Endpoint público chamado pelo Mercado Pago a cada mudança de status.

    Sem login (MP chama de fora). Validação via HMAC-SHA256 quando o
    webhook_secret está configurado.
    """
    integ = IntegracaoMercadoPago.query.first()
    if not integ or not integ.ativo:
        return jsonify({'ok': False, 'erro': 'integração inativa'}), 200

    payload = request.get_json(silent=True) or {}
    data_id = ((payload.get('data') or {}).get('id')
               or payload.get('id') or request.args.get('data.id') or '')
    x_signature = request.headers.get('x-signature') or ''
    x_request_id = request.headers.get('x-request-id') or ''

    if integ.webhook_secret and not services_mercadopago.validar_assinatura_webhook(
        integ.webhook_secret, x_signature, x_request_id, data_id,
    ):
        return jsonify({'ok': False, 'erro': 'assinatura inválida'}), 401

    if not data_id:
        return jsonify({'ok': True, 'msg': 'sem data.id'}), 200

    boleto = services_financeiro.boleto_por_mp_payment_id(data_id)
    if not boleto:
        # MP às vezes envia eventos de outros tipos (merchant_order). Aceita silenciosamente.
        return jsonify({'ok': True, 'msg': 'sem boleto correspondente'}), 200

    try:
        client = services_mercadopago.MercadoPagoClient(integ)
        info = client.consultar_pagamento(data_id)
    except MercadoPagoError as e:
        return jsonify({'ok': False, 'erro': str(e)}), 500

    status_mp = (info.get('status') or '').lower()
    if status_mp == 'approved' and boleto.status != 'pago':
        services_financeiro.registrar_pagamento_boleto(boleto)
    elif status_mp in ('cancelled', 'rejected') and boleto.status not in ('pago', 'cancelado'):
        boleto.status = 'cancelado'
        db.session.commit()

    return jsonify({'ok': True, 'boleto_id': boleto.id, 'status': boleto.status})


# ── Avisos / Comunicados ───────────────────────────────────────────────────────

NIVEIS_AVISO = ('info', 'sucesso', 'aviso', 'urgente')
PAPEIS_AVISO = ('admin', 'coordenador', 'gestor', 'secretario', 'professor', 'responsavel', 'aluno')


@admin_bp.route('/avisos', methods=['GET', 'POST'])
@login_required
@requires('aviso.gerenciar')
def avisos_lista():
    if request.method == 'POST':
        titulo = (request.form.get('titulo') or '').strip()
        mensagem = (request.form.get('mensagem') or '').strip()
        nivel = (request.form.get('nivel') or 'info').strip()
        escopo = (request.form.get('escopo') or 'global').strip()
        expira_str = (request.form.get('expira_em') or '').strip()

        if not titulo or not mensagem:
            flash('Título e mensagem são obrigatórios.', 'danger')
            return redirect(url_for('admin.avisos_lista'))
        if nivel not in NIVEIS_AVISO:
            nivel = 'info'

        papeis_alvo = None
        usuarios_alvo = None
        if escopo == 'por_papel':
            papeis = [p for p in request.form.getlist('papeis')
                      if p in PAPEIS_AVISO]
            if not papeis:
                flash('Selecione ao menos um papel.', 'danger')
                return redirect(url_for('admin.avisos_lista'))
            papeis_alvo = ','.join(papeis)
        elif escopo == 'por_usuario':
            ids = [i for i in request.form.getlist('usuarios')
                   if i.isdigit()]
            if not ids:
                flash('Selecione ao menos um usuário.', 'danger')
                return redirect(url_for('admin.avisos_lista'))
            usuarios_alvo = ','.join(ids)
        elif escopo != 'global':
            escopo = 'global'

        expira_em = None
        if expira_str:
            try:
                expira_em = datetime.strptime(expira_str, '%Y-%m-%d')
            except ValueError:
                flash('Data de expiração inválida.', 'warning')

        try:
            services_avisos.criar_aviso(
                titulo=titulo, mensagem=mensagem, nivel=nivel,
                escopo=escopo, papeis_alvo=papeis_alvo,
                usuarios_alvo=usuarios_alvo,
                criado_por_id=current_user.id, expira_em=expira_em,
            )
            flash('Comunicado publicado.', 'success')
        except ValueError as e:
            flash(str(e), 'danger')
        return redirect(url_for('admin.avisos_lista'))

    avisos = (Aviso.query
              .order_by(Aviso.ativo.desc(), Aviso.criado_em.desc())
              .limit(50).all())
    contagens = {a.id: services_avisos.contagem_leituras(a) for a in avisos}
    usuarios = User.query.order_by(User.nome).all()
    return render_template(
        'admin_avisos.html',
        avisos=avisos, contagens=contagens,
        niveis=NIVEIS_AVISO, papeis=PAPEIS_AVISO,
        papeis_label=ROLES_LABEL, usuarios=usuarios,
    )


@admin_bp.route('/avisos/<int:aviso_id>/encerrar', methods=['POST'])
@login_required
@requires('aviso.gerenciar')
def avisos_encerrar(aviso_id):
    aviso = Aviso.query.get_or_404(aviso_id)
    services_avisos.encerrar_aviso(aviso)
    flash('Comunicado encerrado.', 'success')
    return redirect(url_for('admin.avisos_lista'))


@admin_bp.route('/avisos/<int:aviso_id>/excluir', methods=['POST'])
@login_required
@requires('aviso.gerenciar')
def avisos_excluir(aviso_id):
    aviso = Aviso.query.get_or_404(aviso_id)
    services_avisos.excluir_aviso(aviso)
    flash('Comunicado excluído.', 'success')
    return redirect(url_for('admin.avisos_lista'))


# ── Busca global (topbar) ─────────────────────────────────────────────────────

@admin_bp.route('/buscar')
@login_required
def buscar_global():
    """Busca rápida usada no input da topbar.

    Retorna JSON com grupos (alunos, turmas, professores, responsáveis,
    cursos, atividades) — filtrado pelo papel do usuário.
    """
    termo = (request.args.get('q') or '').strip()
    if len(termo) < 2:
        return jsonify({'q': termo, 'grupos': []})

    like = f'%{termo}%'
    digitos = ''.join(ch for ch in termo if ch.isdigit())
    grupos = []

    tipo = current_user.tipo
    admin_like = tipo in ('admin', 'coordenador', 'gestor')

    # --- Alunos --------------------------------------------------------------
    if admin_like:
        q = Aluno.query.filter(
            db.or_(
                Aluno.nome.ilike(like),
                Aluno.cpf == digitos if digitos else db.false(),
                db.cast(Aluno.id, db.String).ilike(f'%{digitos}%') if digitos else db.false(),
            )
        ).order_by(Aluno.nome).limit(8).all()
        if q:
            grupos.append({
                'titulo': 'Alunos', 'icone': 'bi-person-fill',
                'itens': [{
                    'titulo': a.nome,
                    'sub': f'Matrícula #{a.id:04d}' + (f' • {a.cpf_formatado}' if a.cpf else ''),
                    'url': url_for('admin.alunos') + f'#aluno-{a.id}',
                } for a in q],
            })

    # --- Turmas --------------------------------------------------------------
    if admin_like:
        q = Turma.query.filter(Turma.nome.ilike(like)).order_by(Turma.nome).limit(8).all()
        if q:
            grupos.append({
                'titulo': 'Turmas', 'icone': 'bi-people-fill',
                'itens': [{
                    'titulo': t.nome,
                    'sub': f'{len(t.alunos)} aluno(s)',
                    'url': url_for('admin.turma_detalhe', id=t.id),
                } for t in q],
            })

    # --- Professores ---------------------------------------------------------
    if admin_like:
        q = Professor.query.filter(Professor.nome.ilike(like)).order_by(Professor.nome).limit(8).all()
        if q:
            grupos.append({
                'titulo': 'Professores', 'icone': 'bi-mortarboard-fill',
                'itens': [{
                    'titulo': p.nome, 'sub': '',
                    'url': url_for('admin.professores') + f'#prof-{p.id}',
                } for p in q],
            })

    # --- Responsáveis --------------------------------------------------------
    if admin_like:
        q = Responsavel.query.filter(
            db.or_(
                Responsavel.nome.ilike(like),
                Responsavel.cpf == digitos if digitos else db.false(),
            )
        ).order_by(Responsavel.nome).limit(8).all()
        if q:
            grupos.append({
                'titulo': 'Responsáveis', 'icone': 'bi-person-heart',
                'itens': [{
                    'titulo': r.nome,
                    'sub': r.cpf_formatado if r.cpf else '',
                    'url': url_for('admin.responsaveis') + f'#resp-{r.id}',
                } for r in q],
            })

    # --- Cursos --------------------------------------------------------------
    if admin_like:
        q = Curso.query.filter(Curso.titulo.ilike(like)).order_by(Curso.titulo).limit(8).all()
        if q:
            grupos.append({
                'titulo': 'Cursos', 'icone': 'bi-play-btn-fill',
                'itens': [{
                    'titulo': c.titulo, 'sub': '',
                    'url': url_for('admin.curso_detalhe', curso_id=c.id),
                } for c in q],
            })

    # --- Atividades ----------------------------------------------------------
    if admin_like:
        try:
            q = Atividade.query.filter(Atividade.titulo.ilike(like)).order_by(Atividade.titulo).limit(8).all()
            if q:
                grupos.append({
                    'titulo': 'Atividades', 'icone': 'bi-clipboard-fill',
                    'itens': [{
                        'titulo': a.titulo, 'sub': '',
                        'url': '#',  # atividades vivem em professor; sem rota admin dedicada
                    } for a in q],
                })
        except Exception:
            pass

    return jsonify({'q': termo, 'grupos': grupos})
