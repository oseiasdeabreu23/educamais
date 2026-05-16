"""Endpoints comuns para o usuário interagir com avisos: entendi / lembrar.

Admin gerencia (criar/listar/excluir) em ``/admin/avisos`` — ver
``routes_admin.py``. Este blueprint é só pra ação do destinatário.
"""
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user

from app.models import Aviso
from app import services_avisos


avisos_bp = Blueprint('avisos', __name__, url_prefix='/avisos')


def _eh_destinatario(aviso, user):
    """Mesma lógica do filtro do service, mas no Python pra checar um único."""
    if aviso.escopo == 'global':
        return True
    if aviso.escopo == 'por_papel':
        return (user.tipo or '') in aviso.lista_papeis()
    if aviso.escopo == 'por_usuario':
        return user.id in aviso.lista_usuarios()
    return False


@avisos_bp.route('/<int:aviso_id>/entendi', methods=['POST'])
@login_required
def entendi(aviso_id):
    aviso = Aviso.query.get_or_404(aviso_id)
    if not _eh_destinatario(aviso, current_user):
        abort(403)
    services_avisos.marcar_entendi(aviso, current_user)
    return jsonify({'ok': True, 'status': 'entendi'})


@avisos_bp.route('/<int:aviso_id>/lembrar', methods=['POST'])
@login_required
def lembrar(aviso_id):
    aviso = Aviso.query.get_or_404(aviso_id)
    if not _eh_destinatario(aviso, current_user):
        abort(403)
    services_avisos.marcar_lembrar_depois(aviso, current_user)
    return jsonify({'ok': True, 'status': 'lembrar_depois'})


@avisos_bp.route('/pendentes')
@login_required
def pendentes():
    """JSON usado pelo dropdown do sininho (polling opcional)."""
    pend = services_avisos.avisos_pendentes_para(current_user)
    return jsonify({
        'total': len(pend),
        'avisos': [
            {
                'id': a.id, 'titulo': a.titulo, 'mensagem': a.mensagem,
                'nivel': a.nivel,
                'criado_em': a.criado_em.isoformat() if a.criado_em else None,
            } for a in pend
        ],
    })
