import os
import bcrypt
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, current_app)
from flask_login import login_required, current_user
from app import db
from app.models import (User, Aluno, Responsavel, Professor, Turma, Disciplina,
                        Curso, Modulo, Videoaula, MatriculaCurso, ConfigSistema)
from app.services import media_turma, frequencia_geral, alunos_baixo_desempenho
from datetime import date

LOGO_EXTENSOES = {'png', 'jpg', 'jpeg', 'webp', 'svg'}


def _extensao_valida(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in LOGO_EXTENSOES)

admin_bp = Blueprint('admin', __name__, template_folder='templates')


def admin_required(func):
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
@admin_required
def dashboard():
    turmas = Turma.query.all()
    relatorios = {
        'media_geral': round(sum([media_turma(t) for t in turmas]) / (len(turmas) or 1), 2),
        'frequencia': frequencia_geral(),
        'baixo_desempenho': alunos_baixo_desempenho(),
    }
    return render_template('dashboard_admin.html', turmas=turmas, relatorios=relatorios)


# ── Alunos ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/alunos', methods=['GET', 'POST'])
@login_required
@admin_required
def alunos():
    if request.method == 'POST':
        nome = request.form.get('nome')
        data_nascimento = date.fromisoformat(request.form.get('data_nascimento'))
        turma_id = request.form.get('turma_id')
        aluno = Aluno(nome=nome, data_nascimento=data_nascimento, turma_id=turma_id or None)
        db.session.add(aluno)
        db.session.commit()
        flash('Aluno cadastrado.', 'success')
        return redirect(url_for('admin.alunos'))

    turmas = Turma.query.all()
    alunos = Aluno.query.order_by(Aluno.nome).all()
    return render_template('admin_alunos.html', alunos=alunos, turmas=turmas)


@admin_bp.route('/alunos/editar/<int:id>', methods=['POST'])
@login_required
@admin_required
def editar_aluno(id):
    aluno = Aluno.query.get_or_404(id)
    aluno.nome = request.form.get('nome')
    aluno.data_nascimento = date.fromisoformat(request.form.get('data_nascimento'))
    turma_id = request.form.get('turma_id')
    aluno.turma_id = turma_id or None
    db.session.commit()
    flash('Aluno atualizado.', 'success')
    return redirect(url_for('admin.alunos'))


@admin_bp.route('/alunos/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_aluno(id):
    aluno = Aluno.query.get_or_404(id)
    db.session.delete(aluno)
    db.session.commit()
    flash('Aluno removido.', 'success')
    return redirect(url_for('admin.alunos'))


# ── Turmas ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/turmas', methods=['GET', 'POST'])
@login_required
@admin_required
def turmas():
    if request.method == 'POST':
        nome = request.form.get('nome')
        turma = Turma(nome=nome)
        db.session.add(turma)
        db.session.commit()
        flash('Turma criada.', 'success')
        return redirect(url_for('admin.turmas'))

    turmas = Turma.query.order_by(Turma.nome).all()
    return render_template('admin_turmas.html', turmas=turmas)


@admin_bp.route('/turmas/editar/<int:id>', methods=['POST'])
@login_required
@admin_required
def editar_turma(id):
    turma = Turma.query.get_or_404(id)
    turma.nome = request.form.get('nome')
    db.session.commit()
    flash('Turma atualizada.', 'success')
    return redirect(url_for('admin.turmas'))


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

@admin_bp.route('/professores', methods=['GET', 'POST'])
@login_required
@admin_required
def professores():
    if request.method == 'POST':
        nome = request.form.get('nome')
        turma_id = request.form.get('turma_id') or None
        disciplina_ids = request.form.getlist('disciplina_ids')

        professor = Professor(nome=nome, turma_id=turma_id)
        db.session.add(professor)
        db.session.flush()

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
    return render_template('admin_professores.html',
                           professores=professores, disciplinas=disciplinas, turmas=turmas)


@admin_bp.route('/professores/editar/<int:id>', methods=['POST'])
@login_required
@admin_required
def editar_professor(id):
    professor = Professor.query.get_or_404(id)
    professor.nome = request.form.get('nome')
    professor.turma_id = request.form.get('turma_id') or None
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
@admin_required
def excluir_professor(id):
    professor = Professor.query.get_or_404(id)
    db.session.delete(professor)
    db.session.commit()
    flash('Professor removido.', 'success')
    return redirect(url_for('admin.professores'))


# ── Disciplinas ────────────────────────────────────────────────────────────────

@admin_bp.route('/disciplinas', methods=['GET', 'POST'])
@login_required
@admin_required
def disciplinas():
    if request.method == 'POST':
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
@admin_required
def responsaveis():
    if request.method == 'POST':
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

            if tipo not in ('professor', 'responsavel', 'aluno'):
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
    emails_com_acesso = {u.email for u in usuarios}
    return render_template('admin_usuarios.html',
                           usuarios=usuarios,
                           professores=professores,
                           responsaveis=responsaveis,
                           alunos_sem_acesso=alunos_sem_acesso,
                           emails_com_acesso=emails_com_acesso)


# ── Cursos ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/cursos', methods=['GET', 'POST'])
@login_required
@admin_required
def cursos():
    if request.method == 'POST':
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
@admin_required
def curso_detalhe(curso_id):
    curso = Curso.query.get_or_404(curso_id)

    if request.method == 'POST':
        action = request.form.get('action')

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

                # Remove logo anterior
                if cfg.logo_path:
                    caminho_antigo = os.path.join(
                        current_app.config['UPLOAD_FOLDER'], cfg.logo_path)
                    if os.path.exists(caminho_antigo):
                        os.remove(caminho_antigo)

                nome_arquivo = f'logo.{ext}'
                logo_file.save(os.path.join(
                    current_app.config['UPLOAD_FOLDER'], nome_arquivo))
                cfg.logo_path = nome_arquivo

            db.session.commit()
            flash('Configurações salvas com sucesso.', 'success')

        elif action == 'remover_logo':
            if cfg.logo_path:
                caminho = os.path.join(
                    current_app.config['UPLOAD_FOLDER'], cfg.logo_path)
                if os.path.exists(caminho):
                    os.remove(caminho)
                cfg.logo_path = None
                db.session.commit()
            flash('Logo removida.', 'success')

        return redirect(url_for('admin.configuracoes'))

    return render_template('admin_configuracoes.html', cfg=cfg)


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
