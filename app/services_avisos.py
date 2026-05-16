"""Regras de negócio do sistema de avisos/comunicados internos.

Conceitos:
- Cada ``Aviso`` tem escopo (`global` | `por_papel` | `por_usuario`).
- Para cada (aviso, usuário) há no máximo uma ``AvisoLeitura`` registrando
  o estado: ``entendi`` (fim) ou ``lembrar_depois`` (com `lembrete_para`).
- Pendente = sem leitura **OU** com `status='lembrar_depois'` e
  `lembrete_para <= now`. Avisos expirados (``expira_em < now``) ou
  marcados como ``ativo=False`` deixam de aparecer.
"""
from datetime import datetime, timedelta

from sqlalchemy import or_

from app import db
from app.models import Aviso, AvisoLeitura


SNOOZE_PADRAO = timedelta(hours=2)


def _filtra_para_usuario(query, user):
    """Aplica filtro de escopo (global / papel / usuário específico)."""
    tipo = getattr(user, 'tipo', None) or ''
    uid_str = str(getattr(user, 'id', '') or '')
    return query.filter(
        or_(
            Aviso.escopo == 'global',
            db.and_(
                Aviso.escopo == 'por_papel',
                Aviso.papeis_alvo.isnot(None),
                # match exato em CSV: ",professor," contém ",professor,"
                db.func.lower(',' + Aviso.papeis_alvo + ',').contains(
                    f',{tipo.lower()},'
                ),
            ),
            db.and_(
                Aviso.escopo == 'por_usuario',
                Aviso.usuarios_alvo.isnot(None),
                (',' + Aviso.usuarios_alvo + ',').contains(f',{uid_str},'),
            ),
        )
    )


def _filtra_ativos(query, agora=None):
    agora = agora or datetime.utcnow()
    return query.filter(
        Aviso.ativo.is_(True),
        or_(Aviso.expira_em.is_(None), Aviso.expira_em > agora),
    )


def avisos_pendentes_para(user, agora=None):
    """Retorna lista de Avisos pendentes para o usuário (mais novos primeiro)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return []
    agora = agora or datetime.utcnow()

    q = Aviso.query.outerjoin(
        AvisoLeitura,
        db.and_(
            AvisoLeitura.aviso_id == Aviso.id,
            AvisoLeitura.usuario_id == user.id,
        )
    )
    q = _filtra_ativos(q, agora)
    q = _filtra_para_usuario(q, user)
    q = q.filter(
        or_(
            AvisoLeitura.id.is_(None),
            db.and_(
                AvisoLeitura.status == 'lembrar_depois',
                or_(
                    AvisoLeitura.lembrete_para.is_(None),
                    AvisoLeitura.lembrete_para <= agora,
                ),
            ),
        )
    )
    return q.order_by(Aviso.criado_em.desc()).all()


def total_pendentes_para(user):
    return len(avisos_pendentes_para(user))


def avisos_visiveis_para(user, limite=20):
    """Histórico recente (lidos + pendentes) para o dropdown do sininho."""
    if not user or not getattr(user, 'is_authenticated', False):
        return []
    q = _filtra_ativos(_filtra_para_usuario(Aviso.query, user))
    return q.order_by(Aviso.criado_em.desc()).limit(limite).all()


def estado_para(aviso, user):
    """Devolve 'pendente' | 'entendi' | 'lembrar_depois'."""
    leitura = AvisoLeitura.query.filter_by(
        aviso_id=aviso.id, usuario_id=user.id).first()
    if leitura is None:
        return 'pendente'
    if leitura.status == 'entendi':
        return 'entendi'
    agora = datetime.utcnow()
    if (leitura.lembrete_para is None) or (leitura.lembrete_para <= agora):
        return 'pendente'
    return 'lembrar_depois'


def marcar_entendi(aviso, user):
    leitura = AvisoLeitura.query.filter_by(
        aviso_id=aviso.id, usuario_id=user.id).first()
    if leitura is None:
        leitura = AvisoLeitura(aviso_id=aviso.id, usuario_id=user.id)
        db.session.add(leitura)
    leitura.status = 'entendi'
    leitura.lembrete_para = None
    leitura.atualizado_em = datetime.utcnow()
    db.session.commit()
    return leitura


def marcar_lembrar_depois(aviso, user, snooze=None):
    snooze = snooze or SNOOZE_PADRAO
    leitura = AvisoLeitura.query.filter_by(
        aviso_id=aviso.id, usuario_id=user.id).first()
    if leitura is None:
        leitura = AvisoLeitura(aviso_id=aviso.id, usuario_id=user.id)
        db.session.add(leitura)
    leitura.status = 'lembrar_depois'
    leitura.lembrete_para = datetime.utcnow() + snooze
    leitura.atualizado_em = datetime.utcnow()
    db.session.commit()
    return leitura


def criar_aviso(*, titulo, mensagem, nivel='info', escopo='global',
                papeis_alvo=None, usuarios_alvo=None, criado_por_id=None,
                expira_em=None):
    """Cria um aviso novo. Strings de alvo são CSV simples (sem espaços)."""
    if escopo == 'por_papel' and not papeis_alvo:
        raise ValueError('Escopo por_papel exige ao menos um papel.')
    if escopo == 'por_usuario' and not usuarios_alvo:
        raise ValueError('Escopo por_usuario exige ao menos um usuário.')

    aviso = Aviso(
        titulo=titulo.strip(),
        mensagem=mensagem.strip(),
        nivel=nivel,
        escopo=escopo,
        papeis_alvo=papeis_alvo,
        usuarios_alvo=usuarios_alvo,
        criado_por_id=criado_por_id,
        expira_em=expira_em,
        ativo=True,
    )
    db.session.add(aviso)
    db.session.commit()
    return aviso


def encerrar_aviso(aviso):
    aviso.ativo = False
    db.session.commit()
    return aviso


def excluir_aviso(aviso):
    db.session.delete(aviso)
    db.session.commit()


def contagem_leituras(aviso):
    """Retorna (entendidos, snoozes, total_leituras) — para a UI admin."""
    leituras = AvisoLeitura.query.filter_by(aviso_id=aviso.id).all()
    entendidos = sum(1 for l in leituras if l.status == 'entendi')
    snoozes = sum(1 for l in leituras if l.status == 'lembrar_depois')
    return entendidos, snoozes, len(leituras)
