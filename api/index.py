"""Entrypoint Vercel — expõe a Flask app como WSGI."""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_boot_error = None

try:
    from app import create_app
    app = create_app()
except Exception:
    _boot_error = traceback.format_exc()
    print("BOOT ERROR:\n" + _boot_error, flush=True)
    # Cria app mínimo para Vercel não rejeitar (precisa de top-level `app`)
    import flask as _flask
    app = _flask.Flask(__name__)

if _boot_error:
    _captured = _boot_error

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def _show_boot_error(path):
        import flask as _flask
        return _flask.Response(
            "BOOT ERROR:\n" + _captured,
            status=500,
            mimetype='text/plain',
        )
