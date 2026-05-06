"""Vincula Users tipo='professor' aos registros Professor por nome.

Para cada User com tipo='professor':
  1. Se já tem Professor.user_id apontando pra ele, ignora.
  2. Se existe um Professor sem user_id e com mesmo nome, vincula.
  3. Caso contrário, cria um novo Professor com esse user_id.

Idempotente — pode rodar várias vezes sem efeitos colaterais.

Uso:
    set PYTHONPATH=.
    venv\\Scripts\\python.exe scripts\\vincular_professores.py
"""
from app import create_app, db
from app.models import User, Professor

app = create_app()
with app.app_context():
    users_prof = User.query.filter_by(tipo='professor').all()
    vinculados = 0
    criados = 0
    ja_ok = 0

    for u in users_prof:
        ja_vinculado = Professor.query.filter_by(user_id=u.id).first()
        if ja_vinculado:
            ja_ok += 1
            continue

        match = Professor.query.filter_by(nome=u.nome, user_id=None).first()
        if match:
            match.user_id = u.id
            vinculados += 1
            print(f'  vinculado: {u.email} -> Professor#{match.id} ({match.nome})')
        else:
            novo = Professor(nome=u.nome, user_id=u.id)
            db.session.add(novo)
            criados += 1
            print(f'  criado:    {u.email} -> novo Professor "{u.nome}"')

    db.session.commit()
    print(f'\nResumo: {ja_ok} já estavam ok, {vinculados} vinculados, {criados} criados.')
