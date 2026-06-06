"""
Driver DBAPI2 puro para Turso via HTTP API.
Usa requests (sem extensão nativa) e o dialeto SQLite do SQLAlchemy.
"""
import requests as _requests

apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"


class Error(Exception):
    pass


def connect(turso_url, auth_token):
    return Connection(turso_url, auth_token)


class Connection:
    def __init__(self, turso_url, auth_token):
        self._url = turso_url.rstrip("/")
        self._hdrs = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }

    def cursor(self):
        return Cursor(self)

    def _run(self, stmts):
        payload = {"requests": [{"type": "execute", "stmt": s} for s in stmts]}
        payload["requests"].append({"type": "close"})
        resp = _requests.post(
            f"{self._url}/v2/pipeline",
            headers=self._hdrs,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["results"]

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    # SQLAlchemy's SQLite dialect tenta registrar funções customizadas
    # (ex: REGEXP) via create_function(). No-op aqui — Turso HTTP não
    # suporta UDFs, mas o app não as usa.
    def create_function(self, name, num_params, func, *args, **kwargs):
        pass

    def create_aggregate(self, name, num_params, agg_class, *args, **kwargs):
        pass


# Comandos que o SQLAlchemy envia para controle de transação/inicialização
# mas que o Turso HTTP API não precisa (é autocommit por natureza).
# ATENÇÃO: não usar "select cast(" genérico — queries reais podem começar com CAST.
_SKIP_PATTERNS = (
    "begin", "commit", "rollback", "pragma",
    "select cast('test",   # teste de conexão do SQLAlchemy pysqlite
    "select 1\n", "select 1 ", "select 1;",  # pings de conexão (não subqueries)
)


class Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self._pos = 0
        self.description = None
        self.rowcount = -1
        self.lastrowid = None

    # ── parameter conversion ──────────────────────────────────────────────

    @staticmethod
    def _to_arg(v):
        if v is None:
            return {"type": "null", "value": None}
        if isinstance(v, bool):
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": v}  # Turso exige número JSON, não string
        return {"type": "text", "value": str(v)}

    def _build_stmt(self, sql, params):
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [self._to_arg(p) for p in params]
        return stmt

    # ── result parsing ────────────────────────────────────────────────────

    def _parse(self, result):
        if result.get("type") == "error":
            raise Error(result.get("error", {}).get("message", str(result)))
        resp = result.get("response", {})
        if resp.get("type") != "execute":
            return
        res = resp.get("result", {})
        cols = res.get("cols", [])
        if cols:
            self.description = [
                (c["name"], None, None, None, None, None, None) for c in cols
            ]
        rows_raw = res.get("rows", [])
        self._rows = []
        for row in rows_raw:
            converted = []
            for cell in row:
                t = cell.get("type")
                v = cell.get("value")
                if t == "null" or v is None:
                    converted.append(None)
                elif t == "integer":
                    converted.append(int(v))
                elif t == "float":
                    converted.append(float(v))
                else:
                    converted.append(v)
            self._rows.append(tuple(converted))
        self.rowcount = res.get("rows_affected", len(self._rows))
        li = res.get("last_insert_rowid")
        if li:
            self.lastrowid = int(li)

    # ── DBAPI2 interface ──────────────────────────────────────────────────

    def execute(self, sql, params=None):
        # Ignora silenciosamente comandos de controle de transação e PRAGMAs
        # que o SQLAlchemy envia para inicialização — Turso HTTP é autocommit.
        sql_lower = (sql or "").strip().lower()
        if any(sql_lower.startswith(p) for p in _SKIP_PATTERNS):
            self._rows = []
            self.description = None
            self.rowcount = 0
            return self

        stmt = self._build_stmt(sql, params)
        results = self._conn._run([stmt])
        self._pos = 0
        self._parse(results[0])
        return self

    def executemany(self, sql, seq_of_params):
        for params in seq_of_params:
            self.execute(sql, params)

    def fetchone(self):
        if self._pos < len(self._rows):
            row = self._rows[self._pos]
            self._pos += 1
            return row
        return None

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def fetchmany(self, size=1):
        rows = self._rows[self._pos: self._pos + size]
        self._pos += len(rows)
        return rows

    def close(self):
        pass

    def __iter__(self):
        return iter(self._rows[self._pos:])
