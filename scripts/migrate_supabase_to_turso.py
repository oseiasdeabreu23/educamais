"""
Migração completa: Supabase (PostgreSQL) → Turso (libSQL)
Exporta via PostgREST API e insere via Turso HTTP pipeline.
Uso: python scripts/migrate_supabase_to_turso.py
"""
import json, requests, sys, time

# ── Credenciais ──────────────────────────────────────────────────────────────
SUPABASE_URL  = "https://gvknsdtmiriahtkhydvr.supabase.co"
SUPABASE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd2a25zZHRtaXJpYWh0a2h5ZHZyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgwOTY5ODcsImV4cCI6MjA5MzY3Mjk4N30.0Fst8EMC4td0kEj3ouAasMASY7W-R-oxyByrxBOdqAE"

TURSO_URL     = "https://educamais-oseiasdeabreu23.aws-us-west-2.turso.io"
TURSO_TOKEN   = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3ODA3MDc1MjUsImlkIjoiMDE5ZTlhNzAtNWEwMS03MThjLWFlNTktOTI4ZWQ2OWQyMjY2IiwicmlkIjoiODliYzg1ZjYtZDcyMC00N2YwLWIwMGYtZDNjNDA4MDVjZGU1In0.wBes8_EoaAzWdpnGVxYWTfzYb9t9pkMJCoIF2UYmxdLC2kvJJPJkuWDyTNtE4bnmr84PQ7aOozjvUNEQ1wE7Bg"

SUPABASE_HDRS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
TURSO_HDRS    = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}

# Ordem de inserção respeitando chaves estrangeiras
TABLE_ORDER = [
    "alembic_version",
    "usuarios",
    "turmas",
    "disciplinas",
    "responsaveis",
    "cursos",
    "categorias_despesa",
    "config_sistema",
    "config_licenca",
    "alunos",
    "professores",
    "professor_disciplina",
    "professor_turma",
    "aluno_responsavel",
    "matriculas_turma",
    "matriculas_curso",
    "modulos",
    "videoaulas",
    "progresso_videoaulas",
    "planos_pagamento",
    "mensalidades",
    "boletos",
    "movimentacoes",
    "notas",
    "frequencias",
    "atividades",
    "observacoes",
    "cora_mock_boletos",
    "cora_mock_movimentacoes",
    "integracao_mercadopago",
    "encontros_turma",
    "avisos",
    "aviso_leituras",
    "usuario_permissao",
]

# alembic_version não está no PostgREST (tabela interna) — inserir manualmente
ALEMBIC_VERSION = "d7a8e2c3f1b9"  # última migration conhecida


def fetch_table(table, page_size=1000):
    """Exporta todos os registros de uma tabela via PostgREST com paginação."""
    rows = []
    offset = 0
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select=*&limit={page_size}&offset={offset}"
        resp = requests.get(url, headers=SUPABASE_HDRS, timeout=30)
        if resp.status_code == 404:
            print(f"  {table}: tabela não exposta no PostgREST (pulando)")
            return []
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def sql_val(v):
    """Converte valor Python → literal SQL seguro."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list)):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


def turso_batch(stmts):
    """Envia lote de statements ao Turso."""
    if not stmts:
        return
    payload = {"requests": [{"type": "execute", "stmt": {"sql": s}} for s in stmts]}
    payload["requests"].append({"type": "close"})
    resp = requests.post(f"{TURSO_URL}/v2/pipeline", headers=TURSO_HDRS,
                         json=payload, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    errors = [r for r in results if r.get("type") == "error"]
    if errors:
        # Imprime erro mas continua (duplicatas são esperadas em reruns)
        for e in errors:
            msg = e.get("error", {}).get("message", str(e))
            if "UNIQUE constraint" not in msg and "already exists" not in msg:
                print(f"    AVISO Turso: {msg}")


def insert_table(table, rows, batch_size=50):
    """Gera e executa INSERT OR IGNORE para todos os registros."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    col_list = ", ".join(cols)
    stmts = []
    for row in rows:
        vals = ", ".join(sql_val(row.get(c)) for c in cols)
        stmts.append(f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({vals})")

    for i in range(0, len(stmts), batch_size):
        turso_batch(stmts[i:i + batch_size])

    return len(rows)


def main():
    total = 0
    print("=" * 60)
    print("Migracao Supabase -> Turso")
    print("=" * 60)

    for table in TABLE_ORDER:
        # alembic_version: inserção manual
        if table == "alembic_version":
            turso_batch([f"INSERT OR IGNORE INTO alembic_version (version_num) VALUES ('{ALEMBIC_VERSION}')"])
            print(f"  alembic_version: 1 linha (manual)")
            total += 1
            continue

        print(f"  {table}: exportando...", end=" ", flush=True)
        try:
            rows = fetch_table(table)
        except Exception as e:
            print(f"ERRO ao exportar: {e}")
            continue

        if not rows:
            print("0 linhas")
            continue

        try:
            n = insert_table(table, rows)
            print(f"{n} linhas inseridas")
            total += n
        except Exception as e:
            print(f"ERRO ao inserir: {e}")

    print("=" * 60)
    print(f"Migração concluída! Total: {total} registros")
    print("=" * 60)


if __name__ == "__main__":
    main()
