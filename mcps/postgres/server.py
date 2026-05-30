"""PostgreSQL 向け MCP サーバー(SSE トランスポート)。

複数の PostgreSQL DB をまとめて扱える。接続先は環境変数 POSTGRES_TARGETS で定義する:
    POSTGRES_TARGETS=alias=host:port:user:password:dbname
を改行区切りで複数行記述する。

公開ツール:
- list_databases() : 接続可能な DB(alias)とエンジンバージョンを返す
- list_tables(database) : 指定 DB のテーブル一覧
- describe_table(database, table) : カラム情報
- query(database, sql, limit) : 読み取り専用 SQL を実行
"""

import os
import re
from typing import Any

import psycopg
from mcp.server.fastmcp import FastMCP


def _parse_targets() -> dict[str, dict[str, Any]]:
    raw = os.environ.get("POSTGRES_TARGETS", "").strip()
    if not raw:
        raise RuntimeError("POSTGRES_TARGETS is not set")
    targets: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        alias, _, spec = line.partition("=")
        alias = alias.strip()
        host, port, user, password, dbname = spec.split(":", 4)
        targets[alias] = {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "dbname": dbname,
        }
    return targets


TARGETS = _parse_targets()
mcp = FastMCP("mcp-postgres", host="0.0.0.0", port=8000)


def _connect(alias: str):
    if alias not in TARGETS:
        raise ValueError(f"unknown database alias: {alias}. available: {list(TARGETS)}")
    cfg = TARGETS[alias]
    conninfo = (
        f"host={cfg['host']} port={cfg['port']} user={cfg['user']} "
        f"password={cfg['password']} dbname={cfg['dbname']}"
    )
    return psycopg.connect(conninfo, autocommit=True)


_SELECT_RE = re.compile(r"^\s*(SELECT|WITH|SHOW|EXPLAIN)\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|RENAME|REPLACE)\b", re.IGNORECASE)


@mcp.tool()
def list_databases() -> list[dict[str, str]]:
    """Return PostgreSQL database aliases this server can access, with engine version."""
    result = []
    for alias in TARGETS:
        try:
            with _connect(alias) as conn:
                with conn.cursor() as cur:
                    cur.execute("SHOW server_version")
                    version = cur.fetchone()[0]
            result.append({"alias": alias, "engine": "postgresql", "version": str(version)})
        except Exception as e:
            result.append({"alias": alias, "engine": "postgresql", "version": f"error: {e}"})
    return result


@mcp.tool()
def list_tables(database: str) -> list[str]:
    """List tables in the given PostgreSQL database alias (public schema only)."""
    with _connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
            return [r[0] for r in cur.fetchall()]


@mcp.tool()
def describe_table(database: str, table: str) -> list[dict[str, Any]]:
    """Return column info: name / type / nullable / default."""
    if not re.match(r"^[A-Za-z0-9_]+$", table):
        raise ValueError("invalid table name")
    with _connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s "
                "ORDER BY ordinal_position",
                (table,),
            )
            return [
                {"column": r[0], "type": r[1], "nullable": r[2], "default": r[3]}
                for r in cur.fetchall()
            ]


@mcp.tool()
def query(database: str, sql: str, limit: int = 200) -> dict[str, Any]:
    """Run a read-only SQL (SELECT/WITH/SHOW/EXPLAIN) against a PostgreSQL database alias.

    Returns {columns, rows, row_count}. Non-read statements are rejected.
    A LIMIT is appended automatically if the SQL is a SELECT without one.
    """
    if not _SELECT_RE.match(sql):
        raise ValueError("only SELECT/WITH/SHOW/EXPLAIN are allowed")
    if _FORBIDDEN_RE.search(sql):
        raise ValueError("forbidden keyword detected in SQL")
    if ";" in sql.rstrip().rstrip(";"):
        raise ValueError("multiple statements are not allowed")

    effective_sql = sql.rstrip().rstrip(";")
    if re.match(r"^\s*SELECT\b", effective_sql, re.IGNORECASE) and not re.search(r"\bLIMIT\s+\d+", effective_sql, re.IGNORECASE):
        effective_sql = f"{effective_sql} LIMIT {int(limit)}"

    with _connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(effective_sql)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows = [list(map(_to_python, r)) for r in cur.fetchall()]
            else:
                columns = []
                rows = []
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def _to_python(v: Any) -> Any:
    if hasattr(v, "isoformat"):
        return v.isoformat()
    try:
        import decimal
        if isinstance(v, decimal.Decimal):
            return float(v)
    except Exception:
        pass
    return v


if __name__ == "__main__":
    mcp.run(transport="sse")
