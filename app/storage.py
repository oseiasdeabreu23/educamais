"""Abstração de armazenamento de uploads.

Em dev (``STORAGE_BACKEND=local``, default), salva no filesystem em
``app/static/uploads/``. Em prod (``STORAGE_BACKEND=supabase``), envia
pra um bucket público do Supabase Storage. Os caminhos persistidos no
banco são os mesmos nos dois modos — o que muda é só a URL pública.
"""
import os

import requests
from flask import current_app, url_for


def _backend():
    return current_app.config.get('STORAGE_BACKEND', 'local')


def _bucket():
    return current_app.config.get('SUPABASE_STORAGE_BUCKET', 'uploads')


def _supabase_url():
    return (current_app.config.get('SUPABASE_URL') or '').rstrip('/')


def _service_key():
    return current_app.config.get('SUPABASE_SERVICE_ROLE_KEY') or ''


def save_upload(file_storage, target_name, subdir=''):
    """Salva um upload e devolve o path opaco a persistir no banco.

    Args:
        file_storage: ``werkzeug.FileStorage`` da request.
        target_name: nome de destino sem path (ex.: ``logo.png``).
        subdir: subpasta opcional (ex.: ``comprovantes``).

    Returns:
        str: caminho relativo (ex.: ``logo.png`` ou ``comprovantes/comp_xxx.pdf``).
    """
    rel_path = f'{subdir}/{target_name}' if subdir else target_name

    if _backend() == 'supabase':
        url = f'{_supabase_url()}/storage/v1/object/{_bucket()}/{rel_path}'
        try:
            file_storage.stream.seek(0)
        except Exception:
            pass
        data = file_storage.stream.read()
        content_type = file_storage.mimetype or 'application/octet-stream'
        r = requests.post(
            url,
            headers={
                'Authorization': f'Bearer {_service_key()}',
                'Content-Type': content_type,
                'x-upsert': 'true',
            },
            data=data,
            timeout=30,
        )
        r.raise_for_status()
        return rel_path

    folder = current_app.config['UPLOAD_FOLDER']
    if subdir:
        folder = os.path.join(folder, subdir)
        os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, target_name))
    return rel_path


def delete_upload(rel_path):
    """Remove um upload. Idempotente — não falha se o arquivo não existe."""
    if not rel_path:
        return
    if _backend() == 'supabase':
        url = f'{_supabase_url()}/storage/v1/object/{_bucket()}/{rel_path}'
        try:
            requests.delete(
                url,
                headers={'Authorization': f'Bearer {_service_key()}'},
                timeout=15,
            )
        except requests.RequestException:
            pass
        return
    full = os.path.join(current_app.config['UPLOAD_FOLDER'], rel_path)
    if os.path.exists(full):
        try:
            os.remove(full)
        except OSError:
            pass


def upload_url(rel_path):
    """URL pública pra exibir o upload no front. ``None`` se vazio."""
    if not rel_path:
        return None
    if _backend() == 'supabase':
        return f'{_supabase_url()}/storage/v1/object/public/{_bucket()}/{rel_path}'
    return url_for('static', filename=f'uploads/{rel_path}')
