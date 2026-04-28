from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app import db
import bcrypt

auth_bp = Blueprint('auth', __name__, template_folder='templates')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.tipo == 'admin':
            return redirect(url_for('admin.dashboard'))
        if current_user.tipo == 'professor':
            return redirect(url_for('professor.dashboard'))
        if current_user.tipo == 'responsavel':
            return redirect(url_for('responsavel.dashboard'))
        if current_user.tipo == 'aluno':
            return redirect(url_for('aluno.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        senha = request.form.get('senha')

        user = User.query.filter_by(email=email).first()
        if user and bcrypt.checkpw(senha.encode('utf-8'), user.senha.encode('utf-8')):
            login_user(user)
            if user.tipo == 'admin':
                return redirect(url_for('admin.dashboard'))
            if user.tipo == 'professor':
                return redirect(url_for('professor.dashboard'))
            if user.tipo == 'responsavel':
                return redirect(url_for('responsavel.dashboard'))
            if user.tipo == 'aluno':
                return redirect(url_for('aluno.dashboard'))

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
