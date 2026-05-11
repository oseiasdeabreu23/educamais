"""Rotas relacionadas à licença da instância.

- ``GET  /licenca-bloqueada``  → tela pública mostrada quando a licença
  está inválida no modo bloqueio. Template standalone (não herda base.html
  porque base.html exige usuário autenticado).
- ``GET  /admin/licenca``       → painel admin com status detalhado.
- ``POST /admin/licenca``       → força revalidação (botão "Revalidar").
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import current_user

from app.services_licenca import (
    validar_licenca,
    info_licenca,
    obter_machine_id,
    get_config_licenca,
    invalidar_cache,
    RESULTADOS_VALIDOS,
)

# Tipos suportados hoje. Adicionar IBGE/municipio quando o painel suportar.
TIPOS_CLIENTE = [
    ('pessoa_fisica', 'CPF (pessoa física)'),
    ('empresa', 'CNPJ (empresa)'),
]
MODOS = [
    ('bloqueio', 'Bloqueio (recomendado)'),
    ('log', 'Apenas registrar (dev)'),
]

licenca_bp = Blueprint('licenca', __name__, template_folder='templates')


def _admin_required(func):
    """Mesmo papel-restritor de routes_admin, replicado pra evitar import circular."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.tipo != 'admin':
            flash('Acesso apenas para administrador.', 'danger')
            return redirect(url_for('auth.login'))
        return func(*args, **kwargs)

    return wrapper


@licenca_bp.route('/licenca-bloqueada', methods=['GET', 'POST'])
def bloqueada():
    """Tela pública mostrada quando o app está bloqueado por licença.

    POST com ``action=revalidar`` força nova chamada ao painel. Se a licença
    voltou a ficar válida, redireciona pra raiz (``/``) — daí o usuário
    consegue prosseguir pro login normalmente.
    """
    if request.method == 'POST' and request.form.get('action') == 'revalidar':
        estado = validar_licenca(force_refresh=True)
        if estado.get('valido'):
            return redirect(url_for('auth.login'))
        return render_template(
            'licenca_bloqueada.html',
            estado=estado,
            resultados_validos=RESULTADOS_VALIDOS,
            tentou_revalidar=True,
        )

    estado = info_licenca() or {}
    return render_template(
        'licenca_bloqueada.html',
        estado=estado,
        resultados_validos=RESULTADOS_VALIDOS,
        tentou_revalidar=False,
    )


@licenca_bp.route('/admin/licenca', methods=['GET', 'POST'])
@_admin_required
def admin():
    """Painel admin com status da licença, edição da config e revalidação."""
    from app import db
    from flask import current_app

    cfg = get_config_licenca()

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'salvar':
            api_key_in = (request.form.get('api_key') or '').strip()
            documento_in = (request.form.get('documento') or '').strip()
            tipo_cliente_in = (request.form.get('tipo_cliente') or '').strip()
            modo_in = (request.form.get('modo') or 'bloqueio').strip()

            # Só dígitos no documento (CPF/CNPJ)
            documento_in = ''.join(ch for ch in documento_in if ch.isdigit())

            tipos_validos = {t for t, _ in TIPOS_CLIENTE}
            if tipo_cliente_in not in tipos_validos:
                tipo_cliente_in = 'pessoa_fisica'
            if modo_in not in {m for m, _ in MODOS}:
                modo_in = 'bloqueio'

            # API key vazia no form NÃO apaga o valor atual — pra permitir
            # alterar só documento/modo sem precisar re-colar a key.
            if api_key_in:
                cfg.api_key = api_key_in
            cfg.documento = documento_in or None
            cfg.tipo_cliente = tipo_cliente_in
            cfg.modo = modo_in
            cfg.atualizado_por_id = current_user.id
            db.session.commit()

            invalidar_cache()
            estado = validar_licenca(force_refresh=True)
            if estado.get('valido'):
                flash('Configuração salva e licença validada com sucesso.',
                      'success')
            else:
                flash(
                    f'Configuração salva. Resposta do painel: '
                    f'{estado.get("resultado")}.', 'warning')
            return redirect(url_for('licenca.admin'))

        if action == 'revalidar':
            estado = validar_licenca(force_refresh=True)
            if estado.get('valido'):
                flash('Licença válida — sincronizada com o painel.', 'success')
            else:
                flash(f'Resposta do painel: {estado.get("resultado")}',
                      'warning')
            return redirect(url_for('licenca.admin'))

        if action == 'limpar_api_key':
            cfg.api_key = None
            cfg.atualizado_por_id = current_user.id
            db.session.commit()
            invalidar_cache()
            flash('API key removida.', 'info')
            return redirect(url_for('licenca.admin'))

        return redirect(url_for('licenca.admin'))

    estado = info_licenca() or {}

    cfg_resumo = {
        'url': current_app.config.get('PAINEL_LICENCA_URL') or '',
        'api_key_definida': bool(cfg.api_key),
        'api_key_mascarada': cfg.api_key_mascarada,
        'documento': cfg.documento or '',
        'tipo_cliente': cfg.tipo_cliente or 'pessoa_fisica',
        'modo': cfg.modo or 'bloqueio',
        'cache_horas': current_app.config.get('PAINEL_LICENCA_CACHE_HORAS', 6),
        'grace_dias': current_app.config.get('PAINEL_LICENCA_GRACE_DIAS', 3),
        'debug_resultado': current_app.config.get('PAINEL_LICENCA_DEBUG_RESULTADO',
                                                  '') or '',
        'atualizado_em': cfg.atualizado_em,
    }
    try:
        machine_id = obter_machine_id()
    except Exception:
        machine_id = '—'

    return render_template(
        'admin_licenca.html',
        estado=estado,
        cfg=cfg_resumo,
        machine_id=machine_id,
        tipos_cliente=TIPOS_CLIENTE,
        modos=MODOS,
    )
