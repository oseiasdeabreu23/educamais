import os
from app import create_app, db

app = create_app()


def _bootstrap_dev_db():
    """Cria tabelas locais via ``db.create_all()`` em dev.

    Em prod (Postgres), o esquema é populado via ``scripts/init_prod.py``
    (db.create_all + stamp head). Aqui mantemos ``create_all`` só pra dev
    SQLite onde clones novos do repo precisam de um banco utilizável de
    primeira sem rodar migrations.
    """
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite'):
        return
    with app.app_context():
        db.create_all()


_bootstrap_dev_db()


if __name__ == '__main__':
    porta = int(os.getenv('PORTA', 5000))
    app.run(debug=True, port=porta)
