import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv()

__version__ = '1.0.0'

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'


def _normalize_db_url(url):
    """Normaliza URL do banco.

    Aceita ``postgres://`` (formato legado) e força o driver ``psycopg2``
    pra Postgres — Supabase entrega ``postgresql://`` sem driver explícito.
    """
    if not url:
        return url
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    if url.startswith('postgresql://') and '+psycopg' not in url:
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    return url


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'educomais-secret')
    app.config['SQLALCHEMY_DATABASE_URI'] = _normalize_db_url(
        os.getenv('DATABASE_URL', 'sqlite:///educamais.db'))
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # 5 MB cobre comprovantes; logos têm validação manual de 2 MB no upload
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

    # Config de armazenamento e integrações externas
    app.config['STORAGE_BACKEND'] = os.getenv('STORAGE_BACKEND', 'local')
    app.config['SUPABASE_URL'] = os.getenv('SUPABASE_URL', '')
    app.config['SUPABASE_SERVICE_ROLE_KEY'] = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
    app.config['SUPABASE_STORAGE_BUCKET'] = os.getenv('SUPABASE_STORAGE_BUCKET', 'uploads')
    app.config['BACKUP_ENABLED'] = os.getenv('BACKUP_ENABLED', 'true').lower() == 'true'
    app.config['CORA_MODE'] = os.getenv('CORA_MODE', 'mock')

    # Integração com o Painel de Licenças (validação por instância).
    # Os parâmetros sensíveis (api_key, documento, tipo_cliente, modo)
    # vivem em ConfigLicenca (singleton no banco) — editados em
    # /admin/licenca. Aqui só ficam parâmetros técnicos.
    app.config['PAINEL_LICENCA_URL'] = os.getenv('PAINEL_LICENCA_URL', '')
    app.config['PAINEL_LICENCA_CACHE_HORAS'] = int(
        os.getenv('PAINEL_LICENCA_CACHE_HORAS', '6') or '6')
    app.config['PAINEL_LICENCA_GRACE_DIAS'] = int(
        os.getenv('PAINEL_LICENCA_GRACE_DIAS', '3') or '3')
    # Opcional — força um `resultado` sem bater no painel (testes locais).
    app.config['PAINEL_LICENCA_DEBUG_RESULTADO'] = os.getenv(
        'PAINEL_LICENCA_DEBUG_RESULTADO', '')
    # Fallback de retrocompat — se ConfigLicenca estiver vazia,
    # services_licenca lê dessas envs (instalações antigas).
    app.config['PAINEL_LICENCA_API_KEY'] = os.getenv('PAINEL_LICENCA_API_KEY', '')
    app.config['PAINEL_LICENCA_DOCUMENTO'] = os.getenv('PAINEL_LICENCA_DOCUMENTO', '')
    app.config['PAINEL_LICENCA_TIPO_CLIENTE'] = os.getenv(
        'PAINEL_LICENCA_TIPO_CLIENTE', 'empresa')
    app.config['PAINEL_LICENCA_MODO'] = os.getenv(
        'PAINEL_LICENCA_MODO', 'bloqueio').lower()
    app.config['APP_VERSION'] = __version__

    # Pasta local de uploads (só usada quando STORAGE_BACKEND=local)
    uploads_dir = os.path.join(app.static_folder, 'uploads')
    app.config['UPLOAD_FOLDER'] = uploads_dir
    if app.config['STORAGE_BACKEND'] == 'local':
        try:
            os.makedirs(uploads_dir, exist_ok=True)
        except OSError:
            # Filesystem somente-leitura (ex: Vercel runtime). Em prod usamos
            # storage externo, então ignorar é seguro.
            pass

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)

    from app.models import (User, Aluno, Responsavel, Professor, Turma, Disciplina,
                            Nota, Frequencia, Atividade, Observacao,
                            Curso, Modulo, Videoaula, MatriculaCurso, ProgressoVideoaula,
                            ConfigSistema, ConfigLicenca)
    from app.auth import auth_bp
    from app.routes_admin import admin_bp
    from app.routes_professor import professor_bp
    from app.routes_responsavel import responsavel_bp
    from app.routes_aluno import aluno_bp
    from app.routes_licenca import licenca_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(professor_bp, url_prefix='/professor')
    app.register_blueprint(responsavel_bp, url_prefix='/responsavel')
    app.register_blueprint(aluno_bp, url_prefix='/aluno')
    app.register_blueprint(licenca_bp)

    @app.context_processor
    def inject_config_sistema():
        try:
            cfg = ConfigSistema.query.first()
            if cfg is None:
                cfg = ConfigSistema(nome='EducaMais', logo_path=None)
        except Exception:
            cfg = ConfigSistema(nome='EducaMais', logo_path=None)
        return {'config_sistema': cfg, 'versao_sistema': __version__}

    from datetime import datetime as _dt
    app.jinja_env.globals['now'] = _dt.now
    app.jinja_env.filters['enumerate'] = enumerate

    # URL de upload — abstrai filesystem local vs Supabase Storage
    from app.storage import upload_url
    app.jinja_env.globals['upload_url'] = upload_url

    # Helper de permissões disponível em todos os templates:
    # uso: {% if pode('aluno.editar') %}...{% endif %}
    from app.permissoes import pode as _pode
    from flask_login import current_user as _current_user

    @app.context_processor
    def inject_permissions():
        return {'pode': lambda acao: _pode(_current_user, acao)}

    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    @app.route('/healthz')
    def healthz():
        from flask import jsonify
        return jsonify({'status': 'ok', 'versao': __version__})

    # ── Guarda de licença ────────────────────────────────────────────────
    # Endpoints que NUNCA são bloqueados:
    # - static (assets)
    # - rotas de licença (a própria tela de bloqueio e o painel admin)
    # - auth (login/logout/register) — admin precisa entrar pra resolver
    # - healthz (uptime monitor)
    _ENDPOINTS_LIVRES = {
        'static',
        'healthz',
        'licenca.bloqueada',
        'licenca.admin',
        'auth.login',
        'auth.logout',
        'auth.register',
    }

    @app.before_request
    def _guarda_licenca():
        from flask import g, request, redirect, url_for
        from app.services_licenca import validar_licenca, modo_atual

        endpoint = request.endpoint or ''
        if not endpoint or endpoint in _ENDPOINTS_LIVRES:
            return None

        try:
            estado = validar_licenca()
        except Exception as e:
            # Nunca derrubar o app por causa da licença — só loga.
            app.logger.exception('[licenca] erro inesperado validando: %s', e)
            return None

        g.licenca = estado
        if estado.get('valido'):
            return None

        # Modo efetivo: ConfigLicenca.modo (banco) > env > default bloqueio.
        try:
            modo = modo_atual()
        except Exception:
            modo = app.config.get('PAINEL_LICENCA_MODO', 'bloqueio')
        if modo == 'bloqueio':
            return redirect(url_for('licenca.bloqueada'))

        # modo=log: avisa e segue
        app.logger.warning(
            '[licenca] %s — seguindo (MODO=log)', estado.get('resultado'))
        return None

    return app
