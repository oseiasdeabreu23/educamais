"""Entrypoint Vercel — expõe a Flask app como WSGI.

Vercel detecta o callable ``app`` neste arquivo e usa o runtime
``@vercel/python`` pra servir como serverless function.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402

app = create_app()
