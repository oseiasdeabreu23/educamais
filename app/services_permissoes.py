"""Operações sobre o snapshot de permissões customizadas por usuário.

A matriz padrão (em ``permissoes.PERMISSOES``) define o comportamento
default de cada papel. Quando o admin quer dar a um usuário específico
permissões diferentes do papel, fazemos um **snapshot** dessas permissões
em ``UsuarioPermissao`` e marcamos ``User.permissoes_customizadas = True``.

A função ``pode()`` em ``permissoes.py`` consulta esse snapshot quando a
flag está ligada (e admin é sempre o wildcard, independentemente).

Regras importantes:
- Admin não pode ser customizado (proteção de "último admin").
- Restaurar o padrão apaga o snapshot e desliga a flag — o usuário volta
  a herdar tudo do papel.
- ``salvar_permissoes_customizadas`` filtra contra ``PERMISSOES_TODAS``
  pra ignorar chaves desconhecidas (form rotation, typos, etc.).
"""
from app import db
from app.models import User, UsuarioPermissao
from app.permissoes import PERMISSOES, PERMISSOES_TODAS


class PermissoesError(ValueError):
    """Erro de regra de negócio do RBAC customizado."""


def _validar_alvo(user):
    if user is None:
        raise PermissoesError('Usuário inválido.')
    if user.tipo == 'admin':
        raise PermissoesError(
            'Admins têm acesso total imutável — não podem ser customizados.'
        )


def permissoes_efetivas(user):
    """Retorna o set de chaves que o usuário tem na prática agora.

    Útil pra UI (pré-marcar checkboxes) e pra auditoria.
    """
    if user.tipo == 'admin':
        return {'*'}
    if user.permissoes_customizadas:
        return {p.chave for p in user.permissoes_personalizadas.all()}
    return set(PERMISSOES.get(user.tipo, set()))


def snapshot_permissoes_papel(user):
    """Marca user como customizado e copia o set default do papel pro banco.

    Use isso quando o admin clicar "Personalizar permissões" pela primeira
    vez: o estado inicial são exatamente as permissões que o usuário já
    tinha pelo papel. Depois o admin ajusta na UI.
    """
    _validar_alvo(user)

    # Limpa qualquer registro anterior (idempotente).
    UsuarioPermissao.query.filter_by(user_id=user.id).delete()

    # Defaults do papel atual.
    perms = PERMISSOES.get(user.tipo, set())
    for chave in perms:
        if chave == '*':
            continue  # wildcard nunca persistido
        db.session.add(UsuarioPermissao(user_id=user.id, chave=chave))

    user.permissoes_customizadas = True
    _invalidar_cache(user)
    db.session.commit()


def restaurar_padrao_papel(user):
    """Remove customização e volta a usar o set default do papel."""
    if user is None:
        raise PermissoesError('Usuário inválido.')

    UsuarioPermissao.query.filter_by(user_id=user.id).delete()
    user.permissoes_customizadas = False
    _invalidar_cache(user)
    db.session.commit()


def salvar_permissoes_customizadas(user, chaves):
    """Substitui completamente o snapshot pelas chaves recebidas.

    Marca o usuário como customizado se ainda não estava. Chaves
    desconhecidas (não presentes em ``PERMISSOES_TODAS``) são descartadas
    silenciosamente.
    """
    _validar_alvo(user)

    chaves_validas = set(chaves) & PERMISSOES_TODAS

    UsuarioPermissao.query.filter_by(user_id=user.id).delete()
    for chave in chaves_validas:
        db.session.add(UsuarioPermissao(user_id=user.id, chave=chave))

    user.permissoes_customizadas = True
    _invalidar_cache(user)
    db.session.commit()
    return chaves_validas


def _invalidar_cache(user):
    """Limpa o cache de permissões no objeto (caso o user em sessão seja o alvo)."""
    if hasattr(user, '_perms_cache'):
        try:
            del user._perms_cache
        except AttributeError:
            pass
