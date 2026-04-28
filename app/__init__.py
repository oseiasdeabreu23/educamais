import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'educomais-secret')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///educamais.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB

    uploads_dir = os.path.join(app.static_folder, 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = uploads_dir

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)

    from app.models import (User, Aluno, Responsavel, Professor, Turma, Disciplina,
                            Nota, Frequencia, Atividade, Observacao,
                            Curso, Modulo, Videoaula, MatriculaCurso, ProgressoVideoaula,
                            ConfigSistema)
    from app.auth import auth_bp
    from app.routes_admin import admin_bp
    from app.routes_professor import professor_bp
    from app.routes_responsavel import responsavel_bp
    from app.routes_aluno import aluno_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(professor_bp, url_prefix='/professor')
    app.register_blueprint(responsavel_bp, url_prefix='/responsavel')
    app.register_blueprint(aluno_bp, url_prefix='/aluno')

    @app.context_processor
    def inject_config_sistema():
        try:
            cfg = ConfigSistema.query.first()
            if cfg is None:
                cfg = ConfigSistema(nome='EducaMais', logo_path=None)
        except Exception:
            cfg = ConfigSistema(nome='EducaMais', logo_path=None)
        return {'config_sistema': cfg}

    from datetime import datetime as _dt
    app.jinja_env.globals['now'] = _dt.now
    app.jinja_env.filters['enumerate'] = enumerate

    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    return app
