from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app import db
from app.permissoes import ROLES_ADMIN_LIKE
import bcrypt

auth_bp = Blueprint('auth', __name__, template_folder='templates')


def _dashboard_para(user):
    """Para qual endpoint mandar o usuário após login."""
    tipo = user.tipo
    if tipo in ROLES_ADMIN_LIKE:
        return url_for('admin.dashboard')
    if tipo == 'professor':
        return url_for('professor.dashboard')
    if tipo == 'responsavel':
        return url_for('responsavel.dashboard')
    if tipo == 'aluno':
        return url_for('aluno.dashboard')
    return url_for('auth.login')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_dashboard_para(current_user))

    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        senha = request.form.get('senha')

        user = User.query.filter_by(email=email).first()
        if user and bcrypt.checkpw(senha.encode('utf-8'), user.senha.encode('utf-8')):
            login_user(user)
            return redirect(_dashboard_para(user))

        flash('Email ou senha inválidos.', 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


# Registro público desativado — usuários são criados pelo admin em /admin/usuarios
@auth_bp.route('/register')
def register():
    flash('O cadastro é feito pelo administrador do sistema.', 'info')
    return redirect(url_for('auth.login'))
