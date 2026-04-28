"""
Migração: adiciona coluna 'mes' na tabela notas e recria constraint.
Execute uma vez: python migrar_notas.py
"""
import sqlite3, os

DB = os.path.join(os.path.dirname(__file__), 'instance', 'educamais.db')
if not os.path.exists(DB):
    # tenta na raiz
    DB = os.path.join(os.path.dirname(__file__), 'educamais.db')

print(f"Banco: {DB}")

conn = sqlite3.connect(DB)
cur  = conn.cursor()

# Verifica se a coluna 'mes' já existe
cur.execute("PRAGMA table_info(notas)")
colunas = [row[1] for row in cur.fetchall()]

if 'mes' in colunas:
    print("Coluna 'mes' já existe. Nada a fazer.")
else:
    cur.execute("ALTER TABLE notas ADD COLUMN mes INTEGER NOT NULL DEFAULT 1")
    conn.commit()
    print("Coluna 'mes' adicionada com sucesso.")

conn.close()
print("Concluído.")
