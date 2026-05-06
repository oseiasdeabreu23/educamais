"""Cliente do Banco Cora — interface única, com implementações mock e real.

A interface :class:`CoraClient` define os 4 métodos que o restante do app
conhece. Trocar do mock pra integração real é configurar ``CORA_MODE=real``
no .env (quando o :class:`CoraRealClient` estiver implementado).

O mock persiste estado **no próprio banco** (tabelas ``cora_mock_boletos``
e ``cora_mock_movimentacoes``) — assim funciona idêntico em dev e em
produção serverless (Vercel) sem depender de filesystem.
Expõe ``simular_pagamento()`` extra que **não existe** no client real —
só pra desenvolvimento/teste do fluxo de notificação.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from flask import current_app

from app import db
from app.models import CoraMockBoleto, CoraMockMovimentacao


class CoraError(Exception):
    """Erro genérico de operação com a API do Cora."""


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class CoraClient:
    """Interface comum entre mock e real. Métodos podem levantar :class:`CoraError`."""

    def criar_boleto(self, valor, vencimento, pagador, descricao=''):
        raise NotImplementedError

    def consultar_boleto(self, cora_id):
        raise NotImplementedError

    def cancelar_boleto(self, cora_id):
        raise NotImplementedError

    def listar_movimentacoes(self, de, ate):
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Mock
# --------------------------------------------------------------------------- #
class CoraMockClient(CoraClient):
    """Implementação fake — guarda boletos e movimentações no banco.

    Útil pra desenvolver toda a UI e regras de negócio sem credenciais reais.
    Quando o CoraPro for ativado, troca ``CORA_MODE`` pra ``real`` e o app
    passa a falar com a API de verdade.
    """

    def __init__(self, app=None):
        # Estado vive no DB; nada a carregar aqui.
        pass

    def criar_boleto(self, valor, vencimento, pagador, descricao=''):
        cora_id = f'mock_{uuid.uuid4().hex[:16]}'
        b = CoraMockBoleto(
            cora_id=cora_id,
            status='aberto',
            valor=Decimal(str(valor)),
            vencimento=vencimento,
            pagador=pagador or {},
            descricao=descricao,
        )
        db.session.add(b)
        db.session.commit()
        return {
            'cora_id': cora_id,
            'status': 'aberto',
            'link_pdf': f'/admin/financeiro/cora/mock-pdf/{cora_id}',
            'link_boleto': f'/admin/financeiro/cora/mock-boleto/{cora_id}',
            'valor': Decimal(str(valor)),
            'vencimento': vencimento,
        }

    def consultar_boleto(self, cora_id):
        b = CoraMockBoleto.query.filter_by(cora_id=cora_id).first()
        if not b:
            raise CoraError(f'Boleto {cora_id} não encontrado no mock.')
        # Promove pra 'vencido' se passou da data e ainda está aberto
        if b.status == 'aberto' and b.vencimento < date.today():
            b.status = 'vencido'
            db.session.commit()
        return {
            'cora_id': cora_id,
            'status': b.status,
            'pago_em': b.pago_em,
            'valor': b.valor,
            'vencimento': b.vencimento,
        }

    def cancelar_boleto(self, cora_id):
        b = CoraMockBoleto.query.filter_by(cora_id=cora_id).first()
        if not b or b.status == 'pago':
            return False
        b.status = 'cancelado'
        db.session.commit()
        return True

    def listar_movimentacoes(self, de, ate):
        movs = CoraMockMovimentacao.query.filter(
            CoraMockMovimentacao.data >= de,
            CoraMockMovimentacao.data <= ate,
        ).all()
        return [{
            'id': m.mov_id,
            'tipo': m.tipo,
            'valor': m.valor,
            'descricao': m.descricao,
            'data': m.data,
        } for m in movs]

    # --- Específico do mock (não existe no client real) ---------------------
    def simular_pagamento(self, cora_id):
        """Marca o boleto como pago e gera uma movimentação fake de entrada.

        Substitui o webhook do Cora real durante o desenvolvimento local.
        """
        b = CoraMockBoleto.query.filter_by(cora_id=cora_id).first()
        if not b:
            raise CoraError(f'Boleto {cora_id} não encontrado.')
        if b.status == 'pago':
            return False
        b.status = 'pago'
        b.pago_em = datetime.utcnow()
        db.session.add(CoraMockMovimentacao(
            mov_id=f'mov_{uuid.uuid4().hex[:12]}',
            tipo='entrada',
            valor=b.valor,
            descricao=f'Boleto {cora_id} - {b.descricao or ""}',
            data=date.today(),
            cora_boleto_id=cora_id,
        ))
        db.session.commit()
        return True


# --------------------------------------------------------------------------- #
# Real (placeholder — implementar quando CoraPro estiver ativo)
# --------------------------------------------------------------------------- #
class CoraRealClient(CoraClient):
    """Cliente real do Cora. Não implementado ainda.

    Quando ativar:
    - Auth: OAuth2 client_credentials + mTLS (cert + chave em ``app.config``).
    - Endpoints: ``api.cora.com.br/invoices``, ``/balance``, ``/statement``.
    - Idempotency-Key header em criação de boleto.
    """

    def __init__(self, app):
        raise NotImplementedError(
            'CoraRealClient ainda não implementado. '
            'Mantenha CORA_MODE=mock até concluir a integração real.'
        )


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def get_cora_client():
    """Devolve o client configurado via env (default: mock)."""
    mode = current_app.config.get('CORA_MODE', 'mock')
    if mode == 'real':
        return CoraRealClient(current_app)
    return CoraMockClient(current_app)
