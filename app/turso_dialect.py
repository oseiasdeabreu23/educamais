"""
Dialeto SQLAlchemy customizado para Turso via HTTP API.

Herda a geração de SQL do SQLite (pysqlite) mas bypassa
TODA a inicialização de conexão que não funciona via HTTP:
- Sem PRAGMA
- Sem create_function / create_aggregate
- Sem BEGIN / COMMIT / ROLLBACK explícitos
- Autocommit puro (cada query HTTP é independente)
"""
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite


class TursoHTTPDialect(SQLiteDialect_pysqlite):
    name = "sqlite"  # continua usando geração de SQL do SQLite
    driver = "turso_http"

    # ── Inicialização de conexão ──────────────────────────────────────────

    def on_connect(self):
        """Pula TODA inicialização — sem PRAGMAs, sem create_function."""
        return None

    # ── Controle de transação ─────────────────────────────────────────────
    # Turso HTTP é autocommit por natureza — cada pipeline é atômico.
    # SQLAlchemy chama esses métodos; ignorá-los é seguro.

    def do_begin(self, dbapi_connection):
        pass

    def do_commit(self, dbapi_connection):
        pass

    def do_rollback(self, dbapi_connection):
        pass

    def do_begin_twophase(self, connection, xid):
        pass

    def do_prepare_twophase(self, connection, xid):
        pass

    def do_rollback_twophase(self, connection, xid, is_prepared=True, recover=False):
        pass

    def do_commit_twophase(self, connection, xid, is_prepared=True, recover=False):
        pass

    # ── Execução ─────────────────────────────────────────────────────────

    def do_execute(self, cursor, statement, parameters, context=None):
        """Bypass de statements de controle que o SQLAlchemy pode enviar."""
        sql_lower = (statement or "").strip().lower()
        skip = ("begin", "commit", "rollback", "savepoint", "release", "pragma")
        if any(sql_lower.startswith(s) for s in skip):
            return
        cursor.execute(statement, parameters)

    def do_execute_no_params(self, cursor, statement, context=None):
        sql_lower = (statement or "").strip().lower()
        skip = ("begin", "commit", "rollback", "savepoint", "release", "pragma")
        if any(sql_lower.startswith(s) for s in skip):
            return
        cursor.execute(statement)
