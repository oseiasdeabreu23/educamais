"""Cliente do Mercado Pago — auth via Access Token (Bearer).

A interface :class:`MercadoPagoClient` cria pagamentos PIX e Boleto via
``POST /v1/payments``. As credenciais ficam na tabela singleton
:class:`IntegracaoMercadoPago` — não em variáveis de ambiente — pra que o
admin possa configurar pela interface sem mexer no servidor.

Diferente do Cora (mTLS + cert), o MP usa só Bearer Token, então a
configuração é "cole e pronto".

Webhook: o MP manda POST com header ``x-signature`` e ``x-request-id``.
A assinatura é HMAC-SHA256 do manifesto ``id:<data.id>;request-id:<x-req-id>;ts:<ts>;``
com o segredo registrado no portal MP.
"""
import hashlib
import hmac
import uuid
from decimal import Decimal

import requests
from flask import current_app

from app import db
from app.models import IntegracaoMercadoPago


MP_API_BASE = 'https://api.mercadopago.com'
MP_TIMEOUT = 20  # segundos


class MercadoPagoError(Exception):
    """Erro de operação contra a API do Mercado Pago."""


# --------------------------------------------------------------------------- #
# Configuração (singleton no banco)
# --------------------------------------------------------------------------- #
def get_integracao_mp():
    """Retorna a configuração singleton (cria registro vazio se não existir)."""
    integ = IntegracaoMercadoPago.query.first()
    if integ is None:
        integ = IntegracaoMercadoPago(ativo=False, ambiente='production')
        db.session.add(integ)
        db.session.commit()
    return integ


def is_mp_active():
    """True se a integração está marcada como ativa e tem access_token."""
    integ = IntegracaoMercadoPago.query.first()
    return bool(integ and integ.ativo and (integ.access_token or '').strip())


# --------------------------------------------------------------------------- #
# Client HTTP
# --------------------------------------------------------------------------- #
class MercadoPagoClient:
    """Wrapper HTTP simples sobre a API REST do Mercado Pago.

    Construído a partir de uma instância de :class:`IntegracaoMercadoPago`.
    Todos os métodos podem levantar :class:`MercadoPagoError`.
    """

    def __init__(self, integracao):
        if not integracao or not (integracao.access_token or '').strip():
            raise MercadoPagoError('Mercado Pago não configurado.')
        self.access_token = integracao.access_token.strip()
        self.notification_url = (integracao.notification_url or '').strip() or None
        self.ambiente = integracao.ambiente or 'production'

    def _headers(self, idempotency_key=None):
        h = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }
        if idempotency_key:
            h['X-Idempotency-Key'] = idempotency_key
        return h

    def _post(self, path, payload, idempotency_key=None):
        url = f'{MP_API_BASE}{path}'
        try:
            r = requests.post(
                url, json=payload,
                headers=self._headers(idempotency_key=idempotency_key),
                timeout=MP_TIMEOUT,
            )
        except requests.RequestException as e:
            raise MercadoPagoError(f'Falha de rede: {e}') from e
        if r.status_code >= 400:
            raise MercadoPagoError(
                f'MP {r.status_code}: {_extrair_mensagem_erro(r)}'
            )
        return r.json()

    def _get(self, path):
        url = f'{MP_API_BASE}{path}'
        try:
            r = requests.get(url, headers=self._headers(), timeout=MP_TIMEOUT)
        except requests.RequestException as e:
            raise MercadoPagoError(f'Falha de rede: {e}') from e
        if r.status_code >= 400:
            raise MercadoPagoError(
                f'MP {r.status_code}: {_extrair_mensagem_erro(r)}'
            )
        return r.json()

    # --- Operações ----------------------------------------------------------
    def testar_conexao(self):
        """Bate em /v1/payment_methods só pra validar o token."""
        return self._get('/v1/payment_methods')

    def criar_pagamento_pix(self, valor, descricao, pagador, vencimento=None):
        """Cria pagamento PIX. Retorna dict com payment_id, copia_cola, qr_base64.

        Args:
            valor: Decimal/float do valor.
            descricao: texto curto que aparece pro pagador.
            pagador: dict {email, first_name, last_name, cpf}.
            vencimento: datetime opcional pra date_of_expiration.
        """
        payload = {
            'transaction_amount': float(Decimal(str(valor))),
            'description': descricao,
            'payment_method_id': 'pix',
            'payer': _montar_payer_pix(pagador),
        }
        if vencimento is not None:
            payload['date_of_expiration'] = _formatar_vencimento_mp(vencimento)
        if self.notification_url:
            payload['notification_url'] = self.notification_url

        data = self._post(
            '/v1/payments', payload,
            idempotency_key=str(uuid.uuid4()),
        )
        poi = (data.get('point_of_interaction') or {}).get('transaction_data') or {}
        return {
            'payment_id': str(data.get('id') or ''),
            'status': data.get('status') or 'pending',
            'copia_cola': poi.get('qr_code') or '',
            'qr_base64': poi.get('qr_code_base64') or '',
            'ticket_url': poi.get('ticket_url') or '',
            'raw': data,
        }

    def criar_pagamento_boleto(self, valor, descricao, pagador, vencimento=None):
        """Cria pagamento Boleto Bradesco. Retorna dict com payment_id e linha digitável."""
        payload = {
            'transaction_amount': float(Decimal(str(valor))),
            'description': descricao,
            'payment_method_id': 'bolbradesco',
            'payer': _montar_payer_boleto(pagador),
        }
        if vencimento is not None:
            payload['date_of_expiration'] = _formatar_vencimento_mp(vencimento)
        if self.notification_url:
            payload['notification_url'] = self.notification_url

        data = self._post(
            '/v1/payments', payload,
            idempotency_key=str(uuid.uuid4()),
        )
        td = data.get('transaction_details') or {}
        barcode = data.get('barcode') or {}
        return {
            'payment_id': str(data.get('id') or ''),
            'status': data.get('status') or 'pending',
            'linha_digitavel': barcode.get('content') or '',
            'pdf_url': td.get('external_resource_url') or '',
            'raw': data,
        }

    def consultar_pagamento(self, payment_id):
        """GET /v1/payments/<id>. Retorna dict normalizado com status."""
        data = self._get(f'/v1/payments/{payment_id}')
        return {
            'payment_id': str(data.get('id') or ''),
            'status': data.get('status') or 'pending',
            'date_approved': data.get('date_approved'),
            'raw': data,
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _extrair_mensagem_erro(response):
    """Tenta tirar uma mensagem amigável do response de erro do MP."""
    try:
        body = response.json()
    except (ValueError, AttributeError):
        return (response.text or '')[:200]
    if isinstance(body, dict):
        if 'message' in body:
            return body['message']
        if 'error' in body:
            return body['error']
        if 'cause' in body and body['cause']:
            primeira = body['cause'][0] if isinstance(body['cause'], list) else body['cause']
            return primeira.get('description') or primeira.get('code') or str(primeira)
    return str(body)[:200]


def _formatar_vencimento_mp(d):
    """Formata uma date como ISO 8601 com offset -03:00 (Brasília, sem horário de verão)."""
    # MP exige 'YYYY-MM-DDTHH:MM:SS.sss-03:00'
    return d.strftime('%Y-%m-%dT23:59:59.000-03:00')


def _montar_payer_pix(pagador):
    """Monta o objeto payer pro PIX. Email é obrigatório — usa fallback se faltar."""
    email = (pagador.get('email') or '').strip() or 'pagador@arvorecer.local'
    first = (pagador.get('first_name') or pagador.get('nome') or 'Pagador').strip()
    last = (pagador.get('last_name') or '').strip() or 'Arvorecer'
    payer = {
        'email': email,
        'first_name': first,
        'last_name': last,
    }
    cpf = (pagador.get('cpf') or '').strip()
    if cpf:
        payer['identification'] = {'type': 'CPF', 'number': cpf}
    return payer


def _montar_payer_boleto(pagador):
    """Monta payer pro boleto. CPF e endereço são obrigatórios."""
    if not (pagador.get('cpf') or '').strip():
        raise MercadoPagoError(
            'Boleto Mercado Pago exige CPF do pagador. '
            'Cadastre o CPF do aluno antes de gerar.'
        )
    if not (pagador.get('cep') or '').strip():
        raise MercadoPagoError(
            'Boleto Mercado Pago exige endereço completo (CEP). '
            'Atualize o cadastro do aluno antes de gerar.'
        )

    email = (pagador.get('email') or '').strip() or 'pagador@arvorecer.local'
    return {
        'email': email,
        'first_name': (pagador.get('first_name') or pagador.get('nome') or 'Pagador').strip(),
        'last_name': (pagador.get('last_name') or '').strip() or 'Arvorecer',
        'identification': {'type': 'CPF', 'number': pagador['cpf'].strip()},
        'address': {
            'zip_code': pagador['cep'].strip(),
            'street_name': (pagador.get('logradouro') or '').strip() or 'Não informado',
            'street_number': (pagador.get('numero') or '').strip() or 'S/N',
            'neighborhood': (pagador.get('bairro') or '').strip() or 'Não informado',
            'city': (pagador.get('cidade') or '').strip() or 'Não informado',
            'federal_unit': (pagador.get('uf') or '').strip().upper() or 'SP',
        },
    }


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
def validar_assinatura_webhook(secret, x_signature, x_request_id, data_id):
    """Valida HMAC-SHA256 do webhook do MP.

    Manifesto: ``id:<data_id>;request-id:<x_request_id>;ts:<ts>;``
    O ``x_signature`` chega como ``ts=1700000000,v1=abcdef...``.

    Retorna True se válido, False senão. Se ``secret`` for vazio, retorna
    True (validação opcional — em prod sempre configurar).
    """
    if not secret:
        return True
    if not x_signature:
        return False

    partes = {}
    for item in x_signature.split(','):
        if '=' in item:
            chave, valor = item.strip().split('=', 1)
            partes[chave] = valor

    ts = partes.get('ts')
    v1 = partes.get('v1')
    if not ts or not v1:
        return False

    manifesto = f'id:{data_id};request-id:{x_request_id};ts:{ts};'
    esperado = hmac.new(
        secret.encode('utf-8'),
        manifesto.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(esperado, v1)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def get_mp_client():
    """Devolve um :class:`MercadoPagoClient` configurado a partir do banco.

    Raises:
        MercadoPagoError: se MP não está ativo ou sem token.
    """
    integ = IntegracaoMercadoPago.query.first()
    if not integ or not integ.ativo:
        raise MercadoPagoError('Integração com Mercado Pago está desativada.')
    return MercadoPagoClient(integ)
