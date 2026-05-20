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
    1. Adicionar no ``PERMISSOES_CATALOGO`` (recurso + ação + label).
    2. Incluir nos sets dos papéis que devem tê-la por padrão.
    3. Usar ``@requires('relatorio.exportar')`` na rota ou
       ``{% if pode('relatorio.exportar') %}`` no template.
"""
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user


# ----------------------------------------------------------------------
# Catálogo de permissões: fonte da verdade pra UI de customização.
# Cada item: ('grupo amigável', [(chave, label), ...]).
# A ordem é a ordem de exibição na UI.
# ----------------------------------------------------------------------
PERMISSOES_CATALOGO = [
    ('Alunos', [
        ('aluno.ver',     'Visualizar alunos'),
        ('aluno.criar',   'Criar aluno'),
        ('aluno.editar',  'Editar aluno'),
        ('aluno.excluir', 'Excluir aluno'),
    ]),
    ('Professores', [
        ('professor.ver',     'Visualizar professores'),
        ('professor.criar',   'Criar professor'),
        ('professor.editar',  'Editar professor'),
        ('professor.excluir', 'Excluir professor'),
    ]),
    ('Responsáveis', [
        ('responsavel.ver',     'Visualizar responsáveis'),
        ('responsavel.criar',   'Criar responsável'),
        ('responsavel.editar',  'Editar responsável'),
        ('responsavel.excluir', 'Excluir responsável'),
    ]),
    ('Turmas', [
        ('turma.ver',     'Visualizar turmas'),
        ('turma.criar',   'Criar turma'),
        ('turma.editar',  'Editar turma'),
        ('turma.excluir', 'Excluir turma'),
    ]),
    ('Disciplinas', [
        ('disciplina.ver',     'Visualizar disciplinas'),
        ('disciplina.criar',   'Criar disciplina'),
        ('disciplina.editar',  'Editar disciplina'),
        ('disciplina.excluir', 'Excluir disciplina'),
    ]),
    ('Cursos', [
        ('curso.ver',     'Visualizar cursos'),
        ('curso.criar',   'Criar curso'),
        ('curso.editar',  'Editar curso (módulos/vídeos)'),
        ('curso.excluir', 'Excluir curso'),
    ]),
    ('Matrículas', [
        ('matricula_turma.gerenciar', 'Gerenciar matrículas em turma (matricular/formar/evadir/transferir)'),
        ('matricula_curso.gerenciar', 'Gerenciar matrículas em curso'),
    ]),
    ('Aniversariantes', [
        ('aniversariante.ver', 'Visualizar aniversariantes'),
    ]),
    ('Dashboard e Relatórios', [
        ('dashboard.ver',     'Visualizar dashboard'),
        ('relatorio.ver',     'Visualizar relatórios'),
        ('relatorio.exportar', 'Exportar relatórios (PDF)'),
    ]),
    ('Financeiro — leitura', [
        ('financeiro.ver', 'Visualizar financeiro (KPIs, mensalidades, boletos, inadimplentes, fluxo)'),
    ]),
    ('Financeiro — mensalidades e boletos', [
        ('mensalidade.gerar_lote',      'Gerar lote mensal de mensalidades'),
        ('mensalidade.cancelar',        'Cancelar/excluir mensalidade'),
        ('boleto.emitir',               'Emitir boleto'),
        ('boleto.cancelar',             'Cancelar boleto'),
        ('boleto.sincronizar',          'Sincronizar status de boletos com o Cora'),
        ('boleto.registrar_pagamento',  'Registrar pagamento manual (boleto pago fora do sistema)'),
        ('plano_pagamento.cancelar',    'Cancelar plano de pagamento parcelado'),
    ]),
    ('Financeiro — fluxo de caixa', [
        ('movimentacao.criar',         'Lançar movimentação (entrada/saída)'),
        ('movimentacao.excluir',       'Excluir movimentação manual'),
        ('categoria_despesa.gerenciar', 'Gerenciar categorias de despesa'),
    ]),
    ('Administração do sistema', [
        ('usuario.gerenciar',     'Gerenciar usuários (criar/editar/excluir contas)'),
        ('configuracao.gerenciar', 'Configurações do sistema (nome, logo, Mercado Pago)'),
        ('backup.gerenciar',      'Criar/restaurar/excluir backups'),
        ('aviso.gerenciar',       'Gerenciar avisos do sistema'),
    ]),
]


# Set plano de todas as chaves válidas (para validação e UI).
PERMISSOES_TODAS = {
    chave
    for _, itens in PERMISSOES_CATALOGO
    for chave, _ in itens
}

PERMISSOES_LABEL = {
    chave: label
    for _, itens in PERMISSOES_CATALOGO
    for chave, label in itens
}


# ----------------------------------------------------------------------
# Matriz de permissões por papel. Wildcard '*' = todas.
# ----------------------------------------------------------------------
PERMISSOES = {
    'admin': {'*'},

    'coordenador': {
        # Cadastros: ver + criar (não edita nem exclui)
        'aluno.ver', 'aluno.criar',
        'professor.ver', 'professor.criar',
        'responsavel.ver', 'responsavel.criar',
        'turma.ver',
        'disciplina.ver',
        'curso.ver',
        # Matrículas
        'matricula_turma.gerenciar',
        'matricula_curso.gerenciar',
        # Visualizações
        'aniversariante.ver',
        'dashboard.ver',
        'relatorio.ver', 'relatorio.exportar',
        # Financeiro: leitura + gerar lote + emitir boleto
        'financeiro.ver',
        'mensalidade.gerar_lote',
        'boleto.emitir',
    },

    'gestor': {
        # Só leitura — foco em análise
        'aluno.ver', 'professor.ver', 'responsavel.ver',
        'turma.ver', 'disciplina.ver', 'curso.ver',
        'aniversariante.ver',
        'dashboard.ver',
        'relatorio.ver', 'relatorio.exportar',
        'financeiro.ver',
    },

    'secretario': {
        # Cadastros: ver + criar + editar (não exclui)
        'aluno.ver', 'aluno.criar', 'aluno.editar',
        'professor.ver', 'professor.criar', 'professor.editar',
        'responsavel.ver', 'responsavel.criar', 'responsavel.editar',
        'turma.ver', 'turma.criar', 'turma.editar',
        'disciplina.ver',
        'curso.ver',
        # Matrículas
        'matricula_turma.gerenciar',
        'matricula_curso.gerenciar',
        # Visualizações
        'aniversariante.ver',
        'dashboard.ver',
        'relatorio.ver', 'relatorio.exportar',
        # Financeiro do dia-a-dia (sem cancelar nada)
        'financeiro.ver',
        'mensalidade.gerar_lote',
        'boleto.emitir',
        'boleto.sincronizar',
        'boleto.registrar_pagamento',
        'movimentacao.criar',
    },

    # Papéis com UI própria (blueprints /professor, /responsavel, /aluno).
    # Não usam a matriz — seus decorators próprios cuidam.
    'professor':   set(),
    'responsavel': set(),
    'aluno':       set(),
}


ROLES_LABEL = {
    'admin':       'Administrador',
    'coordenador': 'Coordenador',
    'gestor':      'Gestor',
    'secretario':  'Secretário(a)',
    'professor':   'Professor',
    'responsavel': 'Responsável',
    'aluno':       'Aluno',
}


# Papéis que usam o painel /admin/* (com permissões filtradas).
# Login redireciona estes pra admin.dashboard.
ROLES_ADMIN_LIKE = {'admin', 'coordenador', 'gestor', 'secretario'}

# Papéis criáveis por admin em /admin/usuarios.
# (Aluno/Professor/Responsável têm fluxo próprio com vínculo de cadastro.)
ROLES_CRIAVEIS_ADMIN = ('coordenador', 'gestor', 'secretario', 'professor', 'responsavel', 'aluno')


def pode(usuario, acao):
    """Retorna True se ``usuario`` pode executar ``acao``.

    Ordem de avaliação:
    1. Admin sempre pode (wildcard imutável — protege "último admin").
    2. Se ``permissoes_customizadas == True``, consulta o snapshot em
       ``UsuarioPermissao`` (modelo aditivo: ausência = negada).
    3. Senão, usa o set padrão do papel em ``PERMISSOES``.

    Aceita o ``current_user`` do Flask-Login (anônimo ou autenticado).
    """
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return False

    tipo = getattr(usuario, 'tipo', None)

    # Admin sempre tem tudo — wildcard imutável.
    if tipo == 'admin':
        return True

    # Customização ativa: usa snapshot do banco.
    if getattr(usuario, 'permissoes_customizadas', False):
        # Cache no objeto pra evitar N queries por request.
        cache = getattr(usuario, '_perms_cache', None)
        if cache is None:
            # Lazy import: permissoes.py não pode importar models no topo
            # (cria ciclo via app/__init__.py).
            from app.models import UsuarioPermissao
            cache = {p.chave for p in
                     UsuarioPermissao.query.filter_by(user_id=usuario.id).all()}
            usuario._perms_cache = cache
        return acao in cache

    perms = PERMISSOES.get(tipo, set())
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
