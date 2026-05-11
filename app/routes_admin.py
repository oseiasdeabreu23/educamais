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
                        PlanoPagamento, IntegracaoMercadoPago, EncontroTurma)
from app.services import (media_turma, frequencia_geral, alunos_baixo_desempenho,
                          cpf_valido, cep_valido, uf_valida, so_digitos, UFS_BR)
from app import services_backup, services_financeiro, services_mercadopago, storage
from app.services_cora import get_cora_client, CoraError, CoraMockClient
from app.services_mercadopago import MercadoPagoError
from app.permissoes import requires, pode, ROLES_CRIAVEIS_ADMIN, ROLES_LABEL
from datetime import date, datetime
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
    relatorios = {
        'media_geral': round(sum([media_turma(t) for t in turmas]) / (len(turmas) or 1), 2),
        'frequencia': frequencia_geral(),
        'baixo_desempenho': alunos_baixo_desempenho(),
    }
    return render_template('dashboard_admin.html', turmas=turmas, relatorios=relatorios)


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
            db.session.commit()
            flash('Aluno cadastrado.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('CPF já cadastrado para outro aluno.', 'danger')
        return redirect(url_for('admin.alunos'))

    filtro_status = request.args.get('status', '')
    turmas = Turma.query.order_by(Turma.nome).all()
    cursos = Curso.query.order_by(Curso.titulo).all()
    q = Aluno.query
    if filtro_status in STATUS_ALUNO_CHOICES:
        q = q.filter_by(status=filtro_status)
    alunos = q.order_by(Aluno.nome).all()
    return render_template('admin_alunos.html',
                           alunos=alunos, turmas=turmas, cursos=cursos,
                           sexos=SEXOS_CHOICES, cor_racas=COR_RACA_CHOICES,
                           status_choices=STATUS_ALUNO_CHOICES, ufs=UFS_BR,
                           filtro_status=filtro_status)


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
    db.session.delete(aluno)
    db.session.commit()
    flash('Aluno removido.', 'success')
    return redirect(url_for('admin.alunos'))


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

    # Remove os atuais e regrava (mais simples que diff incremental)
    for enc in list(turma.encontros):
        db.session.delete(enc)
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
@admin_required
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
@admin_required
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
@admin_required
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

        # Coordenador pode matricular/desmatricular alunos no curso, mas
        # não pode editar conteúdo do curso (módulos, vídeos, dados).
        if action in ('matricular', 'desmatricular'):
            if not pode(current_user, 'matricula.gerenciar'):
                abort(403)
        else:
            if current_user.tipo != 'admin':
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
@admin_required
def excluir_curso(curso_id):
    curso = Curso.query.get_or_404(curso_id)
    db.session.delete(curso)
    db.session.commit()
    flash('Curso removido.', 'success')
    return redirect(url_for('admin.cursos'))


# ── Configurações do Sistema ───────────────────────────────────────────────────

@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
@admin_required
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

    from app.services_licenca import info_licenca
    licenca_estado = info_licenca() or {}
    return render_template('admin_configuracoes.html', cfg=cfg,
                           licenca_estado=licenca_estado)


# ── Vincular aluno/turma ───────────────────────────────────────────────────────

@admin_bp.route('/vincular', methods=['POST'])
@login_required
@admin_required
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
@admin_required
def backup():
    backups = services_backup.listar_backups(current_app)
    return render_template('admin_backup.html', backups=backups)


@admin_bp.route('/backup/criar', methods=['POST'])
@login_required
@admin_required
def backup_criar():
    try:
        caminho = services_backup.criar_backup(current_app)
        flash(f'Backup criado: {caminho.name}', 'success')
    except Exception as e:
        flash(f'Erro ao criar backup: {e}', 'danger')
    return redirect(url_for('admin.backup'))


@admin_bp.route('/backup/baixar/<nome>')
@login_required
@admin_required
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
@admin_required
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
@admin_required
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
    mes, ano = _periodo_atual()
    kpis = services_financeiro.kpis_mes(mes, ano)
    # Últimas 8 movimentações pra contexto
    ult = (Movimentacao.query
           .order_by(Movimentacao.data.desc(), Movimentacao.id.desc())
           .limit(8).all())
    return render_template(
        'admin_financeiro.html',
        kpis=kpis, mes=mes, ano=ano, mes_nome=MESES_PT[mes - 1],
        ultimas_movs=ult,
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
@requires('mensalidade.gerar')
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
@admin_required
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
    aluno = Aluno.query.get_or_404(aluno_id)
    plano_ativo = services_financeiro.plano_ativo_do_aluno(aluno)
    historico = (PlanoPagamento.query
                 .filter_by(aluno_id=aluno.id)
                 .order_by(PlanoPagamento.criado_em.desc()).all())
    return render_template(
        'admin_financeiro_plano.html',
        aluno=aluno, plano_ativo=plano_ativo, historico=historico,
        meses=MESES_PT,
    )


@admin_bp.route('/financeiro/planos/<int:aluno_id>/criar', methods=['POST'])
@login_required
@requires('mensalidade.gerar')
def financeiro_plano_criar(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
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

        res = services_financeiro.criar_plano_pagamento(
            aluno=aluno, n_parcelas=n, valor_parcela=valor,
            dia_vencimento=dia, mes_inicio=mes_ini, ano_inicio=ano_ini,
            observacao=observacao,
        )
        msg = (f"Plano criado: {res['mensalidades_criadas']} mensalidade(s).")
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


@admin_bp.route('/financeiro/planos/<int:aluno_id>/cancelar', methods=['POST'])
@login_required
@admin_required
def financeiro_plano_cancelar(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    motivo = (request.form.get('motivo') or '').strip() or None
    res = services_financeiro.cancelar_plano_aluno(aluno, motivo=motivo)
    if not res['plano_cancelado']:
        flash('Aluno não tinha plano ativo.', 'warning')
    else:
        msg = (f"Plano cancelado. {res['mensalidades_canceladas']} mensalidade(s) "
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
@admin_required
def financeiro_boleto_cancelar(id):
    b = Boleto.query.get_or_404(id)
    if services_financeiro.cancelar_boleto(b):
        flash('Boleto cancelado.', 'success')
    else:
        flash('Não foi possível cancelar (já pago?).', 'warning')
    return redirect(request.referrer or url_for('admin.financeiro_boletos'))


@admin_bp.route('/financeiro/boletos/sincronizar', methods=['POST'])
@login_required
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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


# Categorias ------------------------------------------------------------------

@admin_bp.route('/financeiro/categorias', methods=['GET', 'POST'])
@login_required
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
