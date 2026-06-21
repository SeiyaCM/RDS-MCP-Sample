"""PostgreSQL 向け MCP サーバー(Streamable HTTP トランスポート、ステートレス)。

複数の PostgreSQL DB をまとめて扱える。接続先は環境変数 POSTGRES_TARGETS で定義する:
    POSTGRES_TARGETS=alias=host:port:user:password:dbname
を改行区切りで複数行記述する。

公開ツール(MCP サーバー間の名前衝突を避けるため postgres_ プレフィックスを付与):
- postgres_list_databases() : 接続可能な DB(alias)とエンジンバージョンを返す
- postgres_list_tables(database) : 指定 DB のテーブル一覧
- postgres_describe_table(database, table) : カラム情報
- postgres_query(database, sql, limit) : 読み取り専用 SQL を実行
"""

import os
import re
from typing import Any

import psycopg
from mcp.server.fastmcp import Context, FastMCP


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
mcp = FastMCP(
    "mcp-postgres",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
    json_response=True,
)


def _connect(alias: str):
    if alias not in TARGETS:
        raise ValueError(f"unknown database alias: {alias}. available: {list(TARGETS)}")
    cfg = TARGETS[alias]
    conninfo = (
        f"host={cfg['host']} port={cfg['port']} user={cfg['user']} "
        f"password={cfg['password']} dbname={cfg['dbname']}"
    )
    return psycopg.connect(conninfo, autocommit=True)


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


_SELECT_RE = re.compile(r"^\s*(SELECT|WITH|SHOW|EXPLAIN)\b", re.IGNORECASE)
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


@mcp.tool(name="postgres_list_databases")
def list_databases(ctx: Context) -> list[dict[str, str]]:
    """Return PostgreSQL database aliases this server can access, with engine version."""
    allowed = _allowed_dbs(ctx)
    result = []
    for alias in TARGETS:
        if allowed is not None and alias not in allowed:
            continue
        try:
            with _connect(alias) as conn:
                with conn.cursor() as cur:
                    cur.execute("SHOW server_version")
                    version = cur.fetchone()[0]
            result.append({"alias": alias, "engine": "postgresql", "version": str(version)})
        except Exception as e:
            result.append({"alias": alias, "engine": "postgresql", "version": f"error: {e}"})
    return result


@mcp.tool(name="postgres_list_tables")
def list_tables(database: str, ctx: Context) -> list[str]:
    """List tables in the given PostgreSQL database alias (public schema only)."""
    _check_db(ctx, database)
    with _connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
            return [r[0] for r in cur.fetchall()]


@mcp.tool(name="postgres_describe_table")
def describe_table(database: str, table: str, ctx: Context) -> list[dict[str, Any]]:
    """Return column info: name / type / nullable / default."""
    _check_db(ctx, database)
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


@mcp.tool(name="postgres_query")
def query(database: str, sql: str, ctx: Context, limit: int = 200) -> dict[str, Any]:
    """Run a read-only SQL (SELECT/WITH/SHOW/EXPLAIN) against a PostgreSQL database alias.

    Returns {columns, rows, row_count}. Non-read statements are rejected.
    A LIMIT is appended automatically if the SQL is a SELECT without one.
    """
    _check_db(ctx, database)
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


def _run(database: str, sql: str, params: tuple = ()) -> dict[str, Any]:
    """高レベルツール内部用: パラメータ束縛済み SQL を実行し {columns, rows, row_count} を返す。

    query() と違い、呼び出し側が組み立てた固定 SQL を bind パラメータ付きで実行する。
    値は事前に _as_int / _as_int_list / fromisoformat で検証済みである前提。
    """
    with _connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows = [list(map(_to_python, r)) for r in cur.fetchall()]
            else:
                columns = []
                rows = []
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


# ─── 高レベル業務ツール(ユースケース特化 API) ───────────────────────────
# 生 SQL を書かずに代表ユースケースを実行するための専用ツール群。
# 各ツールは自分のエンジン(PostgreSQL)内の DB のみを参照し、エンジンを跨ぐ
# 連鎖は呼び出し側がツール間で ID(line_id / part_ids)を受け渡すことで行う。


@mcp.tool(name="get_top_defect_line")
def get_top_defect_line(
    ctx: Context,
    duration_days: int = 30,
    factory_id: int | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """[UC①-1] 直近の不良件数が多い生産ラインを特定する(qms_db + scada_db)。

    qms_db の defect_records を直近 duration_days で line 別に集計し、scada_db の
    lines/factories でライン名・工場名を解決して返す。factory_id を指定すると
    その工場のラインに限定する(qms_db には factory_id 列が無いため scada_db で絞る)。
    返り値の各 line の part_ids を get_part_engineering_changes にそのまま渡せる。

    Args:
        duration_days: 遡る日数(NOW() 起点)。既定 30。
        factory_id: 拠点スコープ。単一拠点ロールは自拠点 ID を渡すこと。
        top_n: 不良件数降順で返すライン数。既定 5。

    Returns:
        {use_case, duration_days, factory_id, lines:[{line_id, line_name,
         factory_id, factory_name, defect_count, part_ids}], row_count}
    """
    _check_db(ctx, "qms_db", "scada_db")
    duration_days = _as_int(duration_days, "duration_days")
    top_n = _as_int(top_n, "top_n")

    # 手順 A: factory_id 指定時は scada_db で対象 line_id を先に絞る
    allowed_line_ids: list[int] | None = None
    if factory_id is not None:
        factory_id = _as_int(factory_id, "factory_id")
        lines = _run("scada_db", "SELECT id FROM lines WHERE factory_id = %s", (factory_id,))
        allowed_line_ids = [r[0] for r in lines["rows"]]
        if not allowed_line_ids:
            return {"use_case": "top_defect_line", "duration_days": duration_days,
                    "factory_id": factory_id, "lines": [], "row_count": 0}

    # 手順 B: qms_db で line 別の不良件数 + 関与部品 ID を集計
    sql = (
        "SELECT i.line_id, COUNT(d.id) AS defect_count, "
        "ARRAY_AGG(DISTINCT d.part_id ORDER BY d.part_id) AS part_ids "
        "FROM defect_records d JOIN inspections i ON i.id = d.inspection_id "
        "WHERE i.inspected_at >= NOW() - (%s || ' days')::interval "
    )
    params: list[Any] = [duration_days]
    if allowed_line_ids is not None:
        sql += "AND i.line_id = ANY(%s) "
        params.append(allowed_line_ids)
    sql += "GROUP BY i.line_id ORDER BY defect_count DESC LIMIT %s"
    params.append(top_n)
    counts = _run("qms_db", sql, tuple(params))

    line_ids = [r[0] for r in counts["rows"]]
    if not line_ids:
        return {"use_case": "top_defect_line", "duration_days": duration_days,
                "factory_id": factory_id, "lines": [], "row_count": 0}

    # 手順 C: scada_db でライン名・工場名を解決
    name_rows = _run(
        "scada_db",
        "SELECT l.id, l.name, l.factory_id, f.name AS factory_name "
        "FROM lines l JOIN factories f ON f.id = l.factory_id WHERE l.id = ANY(%s)",
        (line_ids,),
    )
    name_map = {r[0]: (r[1], r[2], r[3]) for r in name_rows["rows"]}

    lines_out = []
    for line_id, defect_count, part_ids in counts["rows"]:
        line_name, fid, factory_name = name_map.get(line_id, (None, None, None))
        lines_out.append({
            "line_id": line_id,
            "line_name": line_name,
            "factory_id": fid,
            "factory_name": factory_name,
            "defect_count": defect_count,
            "part_ids": list(part_ids) if part_ids else [],
        })

    return {
        "use_case": "top_defect_line",
        "duration_days": duration_days,
        "factory_id": factory_id,
        "lines": lines_out,
        "row_count": len(lines_out),
    }


@mcp.tool(name="get_line_alarms_timeline")
def get_line_alarms_timeline(line_id: int, ctx: Context, duration_days: int = 30, limit: int = 200) -> dict[str, Any]:
    """[UC①-2] 指定ラインの設備アラームを時系列で取得する(scada_db)。

    そのラインに属する全 equipment のアラームを time_on 昇順で返す。
    line_id は get_top_defect_line の結果をそのまま渡せる。

    Returns:
        {use_case, line_id, duration_days, columns, rows, row_count}
    """
    _check_db(ctx, "scada_db")
    line_id = _as_int(line_id, "line_id")
    duration_days = _as_int(duration_days, "duration_days")
    limit = _as_int(limit, "limit")
    result = _run(
        "scada_db",
        "SELECT a.id, e.id AS equipment_id, e.name AS equipment_name, "
        "a.alarm_code, a.severity, a.time_on, a.time_ack, a.time_off, "
        "a.duration_s, a.description "
        "FROM alarms a JOIN equipment e ON e.id = a.equipment_id "
        "WHERE e.line_id = %s AND a.time_on >= NOW() - (%s || ' days')::interval "
        "ORDER BY a.time_on LIMIT %s",
        (line_id, duration_days, limit),
    )
    result.update({"use_case": "line_alarms_timeline", "line_id": line_id, "duration_days": duration_days})
    return result


@mcp.tool(name="get_part_inventory")
def get_part_inventory(part_ids: list[int], ctx: Context, warehouse_id: int | None = None) -> dict[str, Any]:
    """[UC②-2] 部品の現在庫と直近 7 日の消費ペースを取得する(wms_db)。

    各 part の在庫合計(inventory.qty)と、直近 7 日の出庫(direction='out')から
    日次消費量・在庫日数を算出する。warehouse_id 指定時はその倉庫に限定する。
    part_ids は get_overdue_purchase_orders の結果をそのまま渡せる。

    Returns:
        {use_case, warehouse_id, columns, rows, row_count}
        rows の各行: [part_id, total_qty, daily_consumption, days_of_stock]
    """
    _check_db(ctx, "wms_db")
    part_ids = _as_int_list(part_ids, "part_ids")
    ph = ",".join(["%s"] * len(part_ids))

    inv_sql = f"SELECT i.part_id, SUM(i.qty) AS total_qty FROM inventory i "
    inv_params: list[Any] = []
    if warehouse_id is not None:
        warehouse_id = _as_int(warehouse_id, "warehouse_id")
        inv_sql += "JOIN locations l ON l.id = i.location_id WHERE l.warehouse_id = %s AND i.part_id IN (" + ph + ") "
        inv_params.append(warehouse_id)
        inv_params.extend(part_ids)
    else:
        inv_sql += "WHERE i.part_id IN (" + ph + ") "
        inv_params.extend(part_ids)
    inv_sql += "GROUP BY i.part_id"
    inv = _run("wms_db", inv_sql, tuple(inv_params))
    qty_map = {r[0]: r[1] for r in inv["rows"]}

    # 直近 7 日の出庫量(消費ペース)。warehouse_id 指定時は locations 経由で絞る。
    out_sql = (
        "SELECT sm.part_id, SUM(sm.qty) AS out_qty FROM stock_movements sm "
    )
    out_params: list[Any] = []
    if warehouse_id is not None:
        out_sql += "JOIN locations l ON l.id = sm.location_id WHERE l.warehouse_id = %s AND sm.part_id IN (" + ph + ") "
        out_params.append(warehouse_id)
        out_params.extend(part_ids)
    else:
        out_sql += "WHERE sm.part_id IN (" + ph + ") "
        out_params.extend(part_ids)
    out_sql += "AND sm.direction = 'out' AND sm.moved_at >= NOW() - INTERVAL '7 days' GROUP BY sm.part_id"
    out = _run("wms_db", out_sql, tuple(out_params))
    out_map = {r[0]: r[1] for r in out["rows"]}

    rows = []
    for pid in part_ids:
        total_qty = qty_map.get(pid, 0) or 0
        out_qty = out_map.get(pid, 0) or 0
        daily = round(out_qty / 7.0, 2)
        days_of_stock = round(total_qty / daily, 1) if daily > 0 else None
        rows.append([pid, total_qty, daily, days_of_stock])

    return {
        "use_case": "part_inventory",
        "warehouse_id": warehouse_id,
        "columns": ["part_id", "total_qty", "daily_consumption", "days_of_stock"],
        "rows": rows,
        "row_count": len(rows),
    }


@mcp.tool(name="get_line_downtime_events")
def get_line_downtime_events(line_id: int, ctx: Context, duration_days: int = 1) -> dict[str, Any]:
    """[UC③-1] 指定ラインの停止・保全イベントを時系列で取得する(scada_db)。

    production_events から event_type が stopped / maintenance のものを返し、
    停止時間帯の最小・最大時刻を window_hint として併せて返す。window_hint は
    get_stock_movements_in_window の start_at / end_at にそのまま使える。

    Returns:
        {use_case, line_id, duration_days, columns, rows, row_count,
         window_hint:{start_at, end_at}}
    """
    _check_db(ctx, "scada_db")
    line_id = _as_int(line_id, "line_id")
    duration_days = _as_int(duration_days, "duration_days")
    result = _run(
        "scada_db",
        "SELECT id, occurred_at, event_type, produced_qty, defect_qty "
        "FROM production_events "
        "WHERE line_id = %s AND event_type IN ('stopped','maintenance') "
        "AND occurred_at >= NOW() - (%s || ' days')::interval "
        "ORDER BY occurred_at",
        (line_id, duration_days),
    )
    occ_idx = result["columns"].index("occurred_at")
    times = [r[occ_idx] for r in result["rows"]]
    window_hint = {"start_at": min(times), "end_at": max(times)} if times else {"start_at": None, "end_at": None}
    result.update({
        "use_case": "line_downtime_events",
        "line_id": line_id,
        "duration_days": duration_days,
        "window_hint": window_hint,
    })
    return result


@mcp.tool(name="get_stock_movements_in_window")
def get_stock_movements_in_window(
    factory_id: int,
    start_at: str,
    end_at: str,
    ctx: Context,
    direction: str = "out",
) -> dict[str, Any]:
    """[UC③-2] 指定時間帯・拠点の入出庫を取得する(wms_db)。

    stock_movements を direction と [start_at, end_at] の時間窓で絞り、
    warehouses.factory_id で拠点フィルタする。start_at / end_at は ISO8601 文字列
    (例 '2026-06-14T09:00:00+00:00')で、get_line_downtime_events の window_hint を流用可。

    Returns:
        {use_case, factory_id, direction, start_at, end_at, columns, rows, row_count}
    """
    _check_db(ctx, "wms_db")
    factory_id = _as_int(factory_id, "factory_id")
    if direction not in ("in", "out"):
        raise ValueError("direction must be 'in' or 'out'")
    from datetime import datetime
    start_dt = datetime.fromisoformat(start_at)
    end_dt = datetime.fromisoformat(end_at)

    result = _run(
        "wms_db",
        "SELECT sm.id, sm.part_id, sm.moved_at, sm.direction, sm.qty, sm.reason, w.factory_id "
        "FROM stock_movements sm "
        "JOIN locations l ON l.id = sm.location_id "
        "JOIN warehouses w ON w.id = l.warehouse_id "
        "WHERE w.factory_id = %s AND sm.direction = %s "
        "AND sm.moved_at >= %s AND sm.moved_at <= %s "
        "ORDER BY sm.moved_at",
        (factory_id, direction, start_dt, end_dt),
    )
    result.update({
        "use_case": "stock_movements_in_window",
        "factory_id": factory_id,
        "direction": direction,
        "start_at": start_at,
        "end_at": end_at,
    })
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
    return v


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
