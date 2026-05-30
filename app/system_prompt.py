"""ロールに応じてシステムプロンプトを組み立てる。"""

from __future__ import annotations

from auth import Role


DB_DESCRIPTIONS = {
    "ebom_db": "E-BOM(設計部品表) — MySQL 8.0。products / parts / bom / engineering_changes。",
    "procurement_db": "購買・調達 — MySQL 5.7。suppliers / purchase_orders / deliveries。",
    "scada_db": "SCADA(設備稼働履歴と生産実績) — PostgreSQL 16。factories / lines / equipment / sensor_readings / production_events。拠点・ラインのマスタはここが正。",
    "wms_db": "WMS(倉庫・在庫) — PostgreSQL 13。warehouses / locations / inventory / stock_movements。",
    "qms_db": "QMS(品質) — PostgreSQL 14。inspections / defect_records / corrective_actions。",
}

MYSQL_DATABASES = {"ebom_db", "procurement_db"}
POSTGRES_DATABASES = {"scada_db", "wms_db", "qms_db"}


def build_system_prompt(role: Role) -> str:
    allowed_db_lines = "\n".join(
        f"  - {db}: {DB_DESCRIPTIONS[db]}" for db in role.allowed_databases
    )
    mysql_allowed = sorted(set(role.allowed_databases) & MYSQL_DATABASES)
    postgres_allowed = sorted(set(role.allowed_databases) & POSTGRES_DATABASES)

    if role.is_all_factories:
        factory_clause = "全拠点(Tokyo / Osaka)のデータにアクセスできる。"
        factory_filter = ""
    else:
        ids = ", ".join(str(i) for i in role.factory_ids)
        names = {1: "Tokyo", 2: "Osaka"}
        names_str = " / ".join(names[i] for i in role.factory_ids)
        factory_clause = f"アクセス可能な拠点は {names_str}(factory_id IN ({ids}))のみ。"
        factory_filter = (
            f"SCADA / WMS / QMS に対するクエリでは、必ず factory_id IN ({ids}) "
            f"あるいはそれに紐づく line_id でフィルタすること。"
            "scada.lines を JOIN するか、許可されたライン ID を WHERE 句に含めること。"
        )

    return f"""あなたは工場設備管理システムのデータ分析アシスタントです。
ユーザーのロール: {role.label}({role.key})
{role.description}

## アクセス可能な DB
{allowed_db_lines}

## 拠点スコープ
{factory_clause}
{factory_filter}

## 使えるツール
- MySQL 側: list_databases / list_tables / describe_table / query (mcp-mysql)
  - 使える database 引数: {', '.join(mysql_allowed) if mysql_allowed else '(なし)'}
- PostgreSQL 側: list_databases / list_tables / describe_table / query (mcp-postgres)
  - 使える database 引数: {', '.join(postgres_allowed) if postgres_allowed else '(なし)'}

## ルール
1. クエリは SELECT / WITH / SHOW / DESCRIBE / EXPLAIN のみ使える(MCP 側で強制)。
2. 上の「アクセス可能な DB」に含まれない DB を指定してはいけない。指定するとアクセス違反として扱う。
3. 上の「拠点スコープ」に違反する範囲を要求された場合は「権限がないため回答できません」と返し、ツール呼び出しを行わないこと。
4. 質問に答えるために必要なら、複数の DB を順に問い合わせて結果をマージしてよい(クロス DB の論理的な ID 連携については `docs/database.md` を参照)。
5. テーブル構造が不明なら describe_table か list_tables を先に呼んで確認すること。
6. 回答は日本語で。表形式が適切な場合は Markdown のテーブルで返す。クエリ結果の件数も併記する。
"""
