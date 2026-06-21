"""MySQL 向け MCP サーバー(Streamable HTTP トランスポート、ステートレス)。

複数の MySQL DB をまとめて扱える。接続先は環境変数 MYSQL_TARGETS で定義する:
    MYSQL_TARGETS=alias=host:port:user:password:dbname
を改行区切りで複数行記述する。

公開ツール(MCP サーバー間の名前衝突を避けるため mysql_ プレフィックスを付与):
- mysql_list_databases() : 接続可能な DB(alias)とエンジンバージョンを返す
- mysql_list_tables(database) : 指定 DB のテーブル一覧
- mysql_describe_table(database, table) : カラム情報
- mysql_query(database, sql, limit) : 読み取り専用 SELECT を実行
"""

import os
import re
from typing import Any

import mysql.connector
from mcp.server.fastmcp import Context, FastMCP


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
mcp = FastMCP(
    "mcp-mysql",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
    json_response=True,
)


def _connect(alias: str):
    if alias not in TARGETS:
        raise ValueError(f"unknown database alias: {alias}. available: {list(TARGETS)}")
    return mysql.connector.connect(**TARGETS[alias])


# ─── ロールベースの DB アクセス実強制 ─────────────────────────────────
# クライアント(app)は X-Allowed-Databases ヘッダにロールの許可 DB を載せて送る。
# 各ツールが触る DB をこのリストと突合し、許可外なら実行前に拒否する。
# プロンプト層のソフト統制と違い、LLM が推測でツールを呼んでも物理的にブロックされる。


def _allowed_dbs(ctx: Context) -> set[str] | None:
    """リクエストの X-Allowed-Databases ヘッダから許可 DB 集合を取り出す。

    ヘッダ未設定 / 非 HTTP transport(直叩きテスト等)では None を返し、
    その場合は制限なし(後方互換)として扱う。
    """
    request_context = getattr(ctx, "request_context", None)
    req = getattr(request_context, "request", None)
    if req is None:
        return None
    raw = req.headers.get("x-allowed-databases")
    if raw is None:
        return None
    return {d.strip() for d in raw.split(",") if d.strip()}


def _check_db(ctx: Context, *dbs: str) -> None:
    """ツールが触る DB がすべて許可リストに含まれることを検証する。違反時は例外。"""
    allowed = _allowed_dbs(ctx)
    if allowed is None:
        return
    forbidden = sorted({d for d in dbs if d not in allowed})
    if forbidden:
        raise ValueError(
            f"access denied: database(s) {forbidden} not in allowed list {sorted(allowed)}"
        )


_SELECT_RE = re.compile(r"^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|RENAME|REPLACE)\b", re.IGNORECASE)


def _as_int(value: Any, name: str) -> int:
    """引数を整数として検証する。高レベルツールが SQL に値を埋める前段の防御。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    raise ValueError(f"{name} must be an integer, got: {value!r}")


def _as_int_list(values: Any, name: str, max_len: int = 500) -> list[int]:
    """整数リストとして検証する。IN (...) のプレースホルダに束縛する用途。"""
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(f"{name} must be a non-empty list of integers")
    if len(values) > max_len:
        raise ValueError(f"{name} too long (max {max_len})")
    return [_as_int(v, name) for v in values]


@mcp.tool(name="mysql_list_databases")
def list_databases(ctx: Context) -> list[dict[str, str]]:
    """Return MySQL database aliases this server can access, with engine version."""
    allowed = _allowed_dbs(ctx)
    result = []
    for alias in TARGETS:
        if allowed is not None and alias not in allowed:
            continue
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


@mcp.tool(name="mysql_list_tables")
def list_tables(database: str, ctx: Context) -> list[str]:
    """List tables in the given MySQL database alias."""
    _check_db(ctx, database)
    conn = _connect(database)
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return tables


@mcp.tool(name="mysql_describe_table")
def describe_table(database: str, table: str, ctx: Context) -> list[dict[str, Any]]:
    """Return column info for a table: name / type / nullable / key / default."""
    _check_db(ctx, database)
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


@mcp.tool(name="mysql_query")
def query(database: str, sql: str, ctx: Context, limit: int = 200) -> dict[str, Any]:
    """Run a read-only SQL (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN) against a MySQL database alias.

    Returns {columns, rows, row_count}. Non-read statements are rejected.
    A LIMIT is appended automatically if the SQL is a SELECT without one.
    """
    _check_db(ctx, database)
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


def _run(database: str, sql: str, params: tuple = ()) -> dict[str, Any]:
    """高レベルツール内部用: パラメータ束縛済み SQL を実行し {columns, rows, row_count} を返す。

    query() と違い、呼び出し側が組み立てた固定 SQL を bind パラメータ付きで実行する。
    値は事前に _as_int / _as_int_list で検証済みである前提。
    """
    conn = _connect(database)
    cur = conn.cursor()
    cur.execute(sql, params)
    if cur.description:
        columns = [d[0] for d in cur.description]
        rows = [list(map(_to_python, r)) for r in cur.fetchall()]
    else:
        columns = []
        rows = []
    cur.close()
    conn.close()
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


# ─── 高レベル業務ツール(ユースケース特化 API) ───────────────────────────
# 生 SQL を書かずに代表ユースケースを実行するための専用ツール群。
# 各ツールは自分のエンジン(MySQL)内の DB のみを参照し、エンジンを跨ぐ連鎖は
# 呼び出し側がツール間で ID(part_ids)を受け渡すことで行う。


@mcp.tool(name="get_part_engineering_changes")
def get_part_engineering_changes(part_ids: list[int], ctx: Context, duration_months: int = 6) -> dict[str, Any]:
    """[UC①-3] 指定部品の設計変更(ECO)履歴を取得する(ebom_db)。

    engineering_changes を直近 duration_months で part_id 別に取得し、parts を
    JOIN して部品コード・名称を付ける。part_ids は get_top_defect_line の結果を
    そのまま渡せる。対象期間に ECO の無い部品は parts_with_no_eco に列挙する。

    Returns:
        {use_case, part_ids, duration_months, columns, rows, row_count,
         parts_with_no_eco}
    """
    _check_db(ctx, "ebom_db")
    part_ids = _as_int_list(part_ids, "part_ids")
    duration_months = _as_int(duration_months, "duration_months")
    ph = ",".join(["%s"] * len(part_ids))
    sql = (
        "SELECT ec.id, ec.part_id, p.code AS part_code, p.name AS part_name, ec.eco_no, "
        "ec.changed_at, ec.reason, ec.changed_by, ec.status, ec.effective_date, ec.new_revision "
        "FROM engineering_changes ec JOIN parts p ON p.id = ec.part_id "
        f"WHERE ec.part_id IN ({ph}) AND ec.changed_at >= NOW() - INTERVAL %s MONTH "
        "ORDER BY ec.changed_at DESC"
    )
    result = _run("ebom_db", sql, tuple(part_ids) + (duration_months,))

    pid_idx = result["columns"].index("part_id")
    seen = {r[pid_idx] for r in result["rows"]}
    parts_with_no_eco = sorted(set(part_ids) - seen)

    result.update({
        "use_case": "part_engineering_changes",
        "part_ids": part_ids,
        "duration_months": duration_months,
        "parts_with_no_eco": parts_with_no_eco,
    })
    return result


@mcp.tool(name="get_overdue_purchase_orders")
def get_overdue_purchase_orders(
    ctx: Context,
    plant_id: int | None = None,
    min_days_overdue: int = 14,
    top_n: int = 20,
) -> dict[str, Any]:
    """[UC②-1] 発注済みのまま滞留している購買発注(PO)を取得する(procurement_db)。

    status='ordered' かつ発注から min_days_overdue 日以上経過した PO を経過日数の
    降順で返す。plant_id 指定時はその拠点に限定する。返り値の part_ids を
    get_part_inventory / get_part_usage にそのまま渡せる。

    Returns:
        {use_case, plant_id, min_days_overdue, columns, rows, row_count, part_ids}
    """
    _check_db(ctx, "procurement_db")
    min_days_overdue = _as_int(min_days_overdue, "min_days_overdue")
    top_n = _as_int(top_n, "top_n")
    sql = (
        "SELECT po.id, po.supplier_id, po.part_id, po.ordered_at, po.expected_delivery_date, "
        "po.status, po.qty, DATEDIFF(CURDATE(), po.ordered_at) AS days_since_order "
        "FROM purchase_orders po "
        "WHERE po.status = 'ordered' AND DATEDIFF(CURDATE(), po.ordered_at) >= %s "
    )
    params: list[Any] = [min_days_overdue]
    if plant_id is not None:
        plant_id = _as_int(plant_id, "plant_id")
        sql += "AND po.plant_id = %s "
        params.append(plant_id)
    sql += "ORDER BY days_since_order DESC LIMIT %s"
    params.append(top_n)
    result = _run("procurement_db", sql, tuple(params))

    pid_idx = result["columns"].index("part_id")
    part_ids = sorted({r[pid_idx] for r in result["rows"]})
    result.update({
        "use_case": "overdue_purchase_orders",
        "plant_id": plant_id,
        "min_days_overdue": min_days_overdue,
        "part_ids": part_ids,
    })
    return result


@mcp.tool(name="get_part_usage")
def get_part_usage(part_ids: list[int], ctx: Context) -> dict[str, Any]:
    """[UC②-3] 部品がどの製品に使われているかを取得する(ebom_db)。

    parts と products を突合し、部品の所属製品(product_id / product_name)を返す。
    part_ids は get_overdue_purchase_orders の結果をそのまま渡せる。

    Returns:
        {use_case, part_ids, columns, rows, row_count}
    """
    _check_db(ctx, "ebom_db")
    part_ids = _as_int_list(part_ids, "part_ids")
    ph = ",".join(["%s"] * len(part_ids))
    result = _run(
        "ebom_db",
        "SELECT p.id, p.code, p.name, p.product_id, pr.name AS product_name "
        "FROM parts p LEFT JOIN products pr ON pr.id = p.product_id "
        f"WHERE p.id IN ({ph}) ORDER BY p.id",
        tuple(part_ids),
    )
    result.update({"use_case": "part_usage", "part_ids": part_ids})
    return result


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
    mcp.run(transport="streamable-http")
