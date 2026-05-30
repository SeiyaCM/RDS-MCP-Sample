"""MySQL 向け MCP サーバー(SSE トランスポート)。

複数の MySQL DB をまとめて扱える。接続先は環境変数 MYSQL_TARGETS で定義する:
    MYSQL_TARGETS=alias=host:port:user:password:dbname
を改行区切りで複数行記述する。

公開ツール:
- list_databases() : 接続可能な DB(alias)とエンジンバージョンを返す
- list_tables(database) : 指定 DB のテーブル一覧
- describe_table(database, table) : カラム情報
- query(database, sql, limit) : 読み取り専用 SELECT を実行
"""

import os
import re
from typing import Any

import mysql.connector
from mcp.server.fastmcp import FastMCP


def _parse_targets() -> dict[str, dict[str, Any]]:
    raw = os.environ.get("MYSQL_TARGETS", "").strip()
    if not raw:
        raise RuntimeError("MYSQL_TARGETS is not set")
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
            "database": dbname,
        }
    return targets


TARGETS = _parse_targets()
mcp = FastMCP("mcp-mysql", host="0.0.0.0", port=8000)


def _connect(alias: str):
    if alias not in TARGETS:
        raise ValueError(f"unknown database alias: {alias}. available: {list(TARGETS)}")
    return mysql.connector.connect(**TARGETS[alias])


_SELECT_RE = re.compile(r"^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|RENAME|REPLACE)\b", re.IGNORECASE)


@mcp.tool()
def list_databases() -> list[dict[str, str]]:
    """Return MySQL database aliases this server can access, with engine version."""
    result = []
    for alias in TARGETS:
        try:
            conn = _connect(alias)
            cur = conn.cursor()
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.close()
            conn.close()
            result.append({"alias": alias, "engine": "mysql", "version": str(version)})
        except Exception as e:
            result.append({"alias": alias, "engine": "mysql", "version": f"error: {e}"})
    return result


@mcp.tool()
def list_tables(database: str) -> list[str]:
    """List tables in the given MySQL database alias."""
    conn = _connect(database)
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return tables


@mcp.tool()
def describe_table(database: str, table: str) -> list[dict[str, Any]]:
    """Return column info for a table: name / type / nullable / key / default."""
    if not re.match(r"^[A-Za-z0-9_]+$", table):
        raise ValueError("invalid table name")
    conn = _connect(database)
    cur = conn.cursor()
    cur.execute(f"DESCRIBE `{table}`")
    cols = [
        {"field": r[0], "type": r[1], "null": r[2], "key": r[3], "default": r[4], "extra": r[5]}
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return cols


@mcp.tool()
def query(database: str, sql: str, limit: int = 200) -> dict[str, Any]:
    """Run a read-only SQL (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN) against a MySQL database alias.

    Returns {columns, rows, row_count}. Non-read statements are rejected.
    A LIMIT is appended automatically if the SQL is a SELECT without one.
    """
    if not _SELECT_RE.match(sql):
        raise ValueError("only SELECT/WITH/SHOW/DESCRIBE/EXPLAIN are allowed")
    if _FORBIDDEN_RE.search(sql):
        raise ValueError("forbidden keyword detected in SQL")
    if ";" in sql.rstrip().rstrip(";"):
        raise ValueError("multiple statements are not allowed")

    effective_sql = sql.rstrip().rstrip(";")
    if re.match(r"^\s*SELECT\b", effective_sql, re.IGNORECASE) and not re.search(r"\bLIMIT\s+\d+", effective_sql, re.IGNORECASE):
        effective_sql = f"{effective_sql} LIMIT {int(limit)}"

    conn = _connect(database)
    cur = conn.cursor()
    cur.execute(effective_sql)
    if cur.description:
        columns = [d[0] for d in cur.description]
        rows = [list(map(_to_python, r)) for r in cur.fetchall()]
    else:
        columns = []
        rows = []
    cur.close()
    conn.close()
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
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return v.hex()
    return v


if __name__ == "__main__":
    mcp.run(transport="sse")
