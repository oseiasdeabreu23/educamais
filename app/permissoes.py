"""Controle de acesso por papel (RBAC simples baseado em matriz).

Mantemos o campo ``User.tipo`` como string, mas a verificação de
"o que cada papel pode fazer" sai de ``PERMISSOES`` — uma única fonte
da verdade fácil de revisar e estender.

Como adicionar um papel novo:
    1. Adicionar a chave em ``PERMISSOES`` com o set de permissões.
    2. Adicionar o label amigável em ``ROLES_LABEL``.
    3. Se for um papel administrativo, incluir em ``ROLES_ADMIN_LIKE``
       para o sistema redirecionar pra ``/admin/dashboard`` após login.

Como adicionar uma permissão nova:
    1. Crie a chave (ex: ``'relatorio.exportar'``) e inclua no set dos
       papéis que devem tê-la.
    2. Use ``@requires('relatorio.exportar')`` na rota ou
       ``{% if pode('relatorio.exportar') %}`` no template.
"""
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user


# ----------------------------------------------------------------------
# Matriz de permissões. Wildcard '*' = todas as permissões.
# Papéis "admin-like" (admin, coordenador, gestor) compartilham a UI de
# administração; cada um filtrado pela permissão específica.
# ----------------------------------------------------------------------
PERMISSOES = {
    'admin': {'*'},

    'coordenador': {
        # Cadastros (só ver + criar — nunca editar ou excluir)
        'aluno.ver', 'aluno.criar',
        'professor.ver', 'professor.criar',
        'responsavel.ver', 'responsavel.criar',
        'turma.ver', 'disciplina.ver',
        'curso.ver', 'matricula.gerenciar',
        # Dashboard
        'dashboard.ver',
        # Financeiro — pode gerar mensalidades em lote e emitir boleto
        'financeiro.ver',
        'mensalidade.gerar',
        'boleto.emitir',
    },

    'gestor': {
        # Só leitura — foco em análise
        'dashboard.ver', 'relatorio.ver',
        'aluno.ver', 'professor.ver', 'responsavel.ver',
        'turma.ver', 'disciplina.ver', 'curso.ver',
        'financeiro.ver',
    },

    # Papéis com UI própria (blueprints /professor, /responsavel, /aluno).
    # Não precisam de chaves aqui — seus decorators próprios cuidam.
    'professor':   set(),
    'responsavel': set(),
    'aluno':       set(),
}


ROLES_LABEL = {
    'admin':       'Administrador',
    'coordenador': 'Coordenador',
    'gestor':      'Gestor',
    'professor':   'Professor',
    'responsavel': 'Responsável',
    'aluno':       'Aluno',
}


# Papéis que usam o painel /admin/* (com permissões filtradas).
# Login redireciona estes pra admin.dashboard.
ROLES_ADMIN_LIKE = {'admin', 'coordenador', 'gestor'}

# Papéis criáveis por admin em /admin/usuarios.
# (Aluno/Professor/Responsável têm fluxo próprio com vínculo de cadastro.)
ROLES_CRIAVEIS_ADMIN = ('coordenador', 'gestor', 'professor', 'responsavel', 'aluno')


def pode(usuario, acao):
    """Retorna True se ``usuario`` pode executar ``acao``.

    Aceita o ``current_user`` do Flask-Login (anônimo ou autenticado).
    """
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return False
    perms = PERMISSOES.get(getattr(usuario, 'tipo', None), set())
    return '*' in perms or acao in perms


def requires(acao):
    """Decorator de rota: exige ``acao`` no current_user.

    - Anônimo → redireciona pro login.
    - Logado sem permissão → flash + 403.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not pode(current_user, acao):
                flash('Você não tem permissão para acessar esta área.', 'danger')
                abort(403)
            return func(*args, **kwargs)
        return wrapper
    return decorator
