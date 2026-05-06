"""Bootstrap do banco em produção (Postgres remoto via Supabase).

Cria todas as tabelas a partir dos models e marca as migrations como
aplicadas (stamp head). Idempotente — pode rodar múltiplas vezes sem
quebrar nada.

Uso (rodar localmente apontando pro DB de produção):

    Windows PowerShell:
        $env:DATABASE_URL = "postgresql+psycopg2://postgres.SEU_REF:SENHA@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"
        $env:STORAGE_BACKEND = "supabase"
        venv\\Scripts\\python.exe scripts\\init_prod.py

    Para também criar um admin inicial, defina antes:
        $env:ADMIN_EMAIL = "admin@arvorecer.org"
        $env:ADMIN_SENHA = "TROQUE_DEPOIS_NO_PRIMEIRO_LOGIN"
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bcrypt  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models import User  # noqa: E402
from flask_migrate import stamp  # noqa: E402


def main():
    app = create_app()
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('postgresql'):
        print(f'AVISO: DATABASE_URL não aponta pra Postgres.\n  Atual: {uri}\n'
              '  Esperado: postgresql+psycopg2://...\n'
              'Defina DATABASE_URL antes de rodar.')
        sys.exit(1)

    print(f'Conectando em: {uri.split("@")[-1] if "@" in uri else uri}')

    with app.app_context():
        print('Criando tabelas via db.create_all()...')
        db.create_all()
        print('  ok.')

        print('Marcando migrations como aplicadas (alembic stamp head)...')
        try:
            stamp(revision='head')
            print('  ok.')
        except Exception as e:
            print(f'  aviso: {e} — pode ser que já estavam stampadas.')

        admin_email = os.getenv('ADMIN_EMAIL')
        admin_senha = os.getenv('ADMIN_SENHA')
        if admin_email and admin_senha:
            existente = User.query.filter_by(email=admin_email).first()
            if existente:
                print(f'Admin {admin_email} já existe — pulando seed.')
            else:
                hashed = bcrypt.hashpw(admin_senha.encode('utf-8'),
                                       bcrypt.gensalt()).decode('utf-8')
                admin = User(nome='Administrador',
                             email=admin_email,
                             senha=hashed,
                             tipo='admin')
                db.session.add(admin)
                db.session.commit()
                print(f'Admin criado: {admin_email}')
                print('  ATENÇÃO: troque a senha após o primeiro login.')
        else:
            print('ADMIN_EMAIL/ADMIN_SENHA não definidos — não criou admin.')

    print('\nBootstrap concluído.')


if __name__ == '__main__':
    main()
