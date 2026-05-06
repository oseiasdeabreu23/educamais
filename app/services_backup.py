"""Backup e restauração do sistema.

O backup é um zip contendo:
- ``educamais.db`` — cópia atômica do banco SQLite (via sqlite3.backup API,
  funciona mesmo com conexões abertas)
- ``uploads/`` — todos os arquivos de ``app/static/uploads/`` (logos)
- ``manifest.json`` — metadados (versão, data, arquivos)

Arquivos ficam em ``instance/backups/``.
"""
import os
import io
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from app import db

MANIFEST_NAME = 'manifest.json'
MANIFEST_VERSION = 1


def _instance_dir(app):
    return Path(app.instance_path)


def _backups_dir(app):
    p = _instance_dir(app) / 'backups'
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # Filesystem read-only (ex: Vercel runtime). Em produção usamos os
        # backups automáticos do Supabase — esse módulo só é útil em dev.
        raise RuntimeError(
            'Backup local desativado: filesystem somente-leitura ou indisponível. '
            'Use os backups automáticos do Supabase em produção.'
        ) from e
    return p


def _db_path(app):
    """Resolve o caminho do arquivo SQLite a partir da SQLALCHEMY_DATABASE_URI.

    URIs ``sqlite:///foo.db`` (3 barras) são caminhos relativos resolvidos pelo
    Flask-SQLAlchemy a partir de ``app.instance_path``.
    URIs ``sqlite:////abs/foo.db`` (4 barras) são absolutos.
    """
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite:'):
        raise RuntimeError(
            'Backup atualmente suporta apenas SQLite. URI atual: ' + uri)
    raw = uri.replace('sqlite:///', '', 1) if uri.startswith('sqlite:///') else uri.replace('sqlite://', '', 1)
    p = Path(raw)
    if not p.is_absolute():
        p = Path(app.instance_path) / raw
    return p


def _uploads_dir(app):
    return Path(app.root_path) / 'static' / 'uploads'


def listar_backups(app):
    """Devolve lista de dicts {nome, tamanho_kb, data} ordenada do mais recente.

    Em ambientes onde backup local não está disponível (filesystem read-only),
    devolve lista vazia em vez de levantar — a página de backup mostra estado
    vazio e a tentativa de criar deixa o erro aparecer no flash.
    """
    try:
        backups_dir = _backups_dir(app)
    except RuntimeError:
        return []
    out = []
    for f in sorted(backups_dir.glob('*.zip'), reverse=True):
        st = f.stat()
        out.append({
            'nome': f.name,
            'tamanho_kb': round(st.st_size / 1024, 1),
            'data': datetime.fromtimestamp(st.st_mtime),
        })
    return out


def criar_backup(app, prefixo='backup'):
    """Cria um zip com o estado atual do sistema. Devolve o Path gerado."""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    nome = f'{prefixo}_{timestamp}.zip'
    destino = _backups_dir(app) / nome

    db_src = _db_path(app)
    if not db_src.exists():
        raise FileNotFoundError(f'Banco não encontrado: {db_src}')

    # Snapshot atômico do SQLite (suporta conexões abertas)
    db_buf = io.BytesIO()
    src_conn = sqlite3.connect(str(db_src))
    try:
        tmp_path = destino.with_suffix('.dbtmp')
        dst_conn = sqlite3.connect(str(tmp_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
        with open(tmp_path, 'rb') as f:
            db_buf.write(f.read())
        tmp_path.unlink()
    finally:
        src_conn.close()

    uploads = _uploads_dir(app)
    arquivos_uploads = []

    manifest = {
        'version': MANIFEST_VERSION,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'app': 'EducaMais',
        'db_size_bytes': db_buf.getbuffer().nbytes,
        'uploads': [],
    }

    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('educamais.db', db_buf.getvalue())
        if uploads.exists():
            for up in uploads.iterdir():
                if up.is_file():
                    arcname = f'uploads/{up.name}'
                    zf.write(up, arcname)
                    arquivos_uploads.append(up.name)
        manifest['uploads'] = arquivos_uploads
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))

    return destino


def restaurar_backup(app, file_storage):
    """Restaura backup a partir de um upload (werkzeug FileStorage).

    Antes de restaurar, gera um pre-backup automático do estado atual
    (prefixo ``pre-restore``) — assim dá pra reverter em caso de problema.

    Devolve dict {ok, mensagem, pre_backup}.
    """
    # Lê o upload na memória
    raw = file_storage.read()
    if not raw:
        return {'ok': False, 'mensagem': 'Arquivo vazio.', 'pre_backup': None}

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return {'ok': False, 'mensagem': 'Arquivo inválido (não é um zip).', 'pre_backup': None}

    nomes = set(zf.namelist())
    if 'educamais.db' not in nomes:
        return {
            'ok': False,
            'mensagem': 'Backup inválido: faltando educamais.db.',
            'pre_backup': None,
        }

    # Pre-backup do estado atual (rede de segurança)
    pre = criar_backup(app, prefixo='pre-restore')

    # Fecha pool de conexões SQLAlchemy antes de sobrescrever o arquivo
    db.session.close()
    db.engine.dispose()

    # Sobrescreve o banco
    db_dst = _db_path(app)
    db_dst.parent.mkdir(parents=True, exist_ok=True)
    with zf.open('educamais.db') as src, open(db_dst, 'wb') as dst:
        shutil.copyfileobj(src, dst)

    # Sobrescreve os uploads (limpa antes pra não deixar lixo de antes)
    uploads = _uploads_dir(app)
    uploads.mkdir(parents=True, exist_ok=True)
    for f in uploads.iterdir():
        if f.is_file():
            f.unlink()
    for nome in nomes:
        if nome.startswith('uploads/') and not nome.endswith('/'):
            destino_arquivo = uploads / Path(nome).name
            with zf.open(nome) as src, open(destino_arquivo, 'wb') as dst:
                shutil.copyfileobj(src, dst)

    return {
        'ok': True,
        'mensagem': 'Backup restaurado com sucesso. Faça login novamente.',
        'pre_backup': pre.name,
    }


def excluir_backup(app, nome):
    """Remove um backup específico. Bloqueia path traversal."""
    if '/' in nome or '\\' in nome or '..' in nome or not nome.endswith('.zip'):
        raise ValueError('Nome de arquivo inválido.')
    alvo = _backups_dir(app) / nome
    if alvo.exists():
        alvo.unlink()
        return True
    return False


def caminho_backup(app, nome):
    """Resolve caminho seguro de um backup pra download."""
    if '/' in nome or '\\' in nome or '..' in nome or not nome.endswith('.zip'):
        raise ValueError('Nome de arquivo inválido.')
    return _backups_dir(app) / nome
