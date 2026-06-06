"""Entrypoint Vercel — expõe a Flask app como WSGI.

Vercel detecta o callable ``app`` neste arquivo e usa o runtime
``@vercel/python`` pra servir como serverless function.
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from app import create_app
    app = create_app()
except Exception as _boot_err:
    # Expõe o erro de boot via endpoint /healthz para diagnóstico
    import flask as _flask
    app = _flask.Flask(__name__)
    _err_msg = traceback.format_exc()

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def _boot_error(path):
        return _flask.Response(
            f"BOOT ERROR:\n{_err_msg}",
            status=500,
            mimetype='text/plain',
        )
