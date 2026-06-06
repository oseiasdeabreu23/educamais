import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.update({'DATABASE_URL':'libsql://educamais-oseiasdeabreu23.aws-us-west-2.turso.io',
'TURSO_AUTH_TOKEN':'eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3ODA3MDc1MjUsImlkIjoiMDE5ZTlhNzAtNWEwMS03MThjLWFlNTktOTI4ZWQ2OWQyMjY2IiwicmlkIjoiODliYzg1ZjYtZDcyMC00N2YwLWIwMGYtZDNjNDA4MDVjZGU1In0.wBes8_EoaAzWdpnGVxYWTfzYb9t9pkMJCoIF2UYmxdLC2kvJJPJkuWDyTNtE4bnmr84PQ7aOozjvUNEQ1wE7Bg',
'PAINEL_LICENCA_URL':'','SECRET_KEY':'test'})

from app import create_app
from app import services_relatorios as sr

app = create_app()
with app.app_context():
    for fn_name, fn in [('kpis_status_alunos', sr.kpis_status_alunos),
                        ('distribuicao_por_turma', sr.distribuicao_por_turma),
                        ('historico_anual', sr.historico_anual),
                        ('snapshot_completo', sr.snapshot_completo)]:
        try:
            r = fn()
            print(f"OK  {fn_name}: {type(r).__name__}")
        except Exception as e:
            print(f"ERR {fn_name}: {e}")
            traceback.print_exc()
