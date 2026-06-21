"""ロールに応じてシステムプロンプトを組み立てる。"""

from __future__ import annotations

from auth import Role


DB_DESCRIPTIONS = {
    "ebom_db": {
        "label": "設計部品表 (E-BOM)",
        "engine": "MySQL 8.0",
        "detail": (
            "products(id/code/name/category) / "
            "parts(id/code/name/supplier_id/unit_cost/product_id/uom/material/current_revision/lifecycle_status。"
            "parts.product_id = products.id で製品に直接紐づく。部品が使われる製品を調べるには parts.product_id を使うこと) / "
            "bom(parent_part_id/child_part_id/qty: 部品構成。bom テーブルに product_id 列は存在しない) / "
            "engineering_changes(id/part_id/changed_at/reason/changed_by/eco_no/status/effective_date/new_revision: ECO ワークフロー) / "
            "part_revisions(part_id/revision/effective_from/effective_to/change_reason/released_by: 版数履歴、effective_to IS NULL が現行 Rev) / "
            "alternate_parts(設計上の互換代替品) / "
            "eco_part_links(eco_id/part_id: 1 ECO が複数部品に波及した記録)。"
            "※ 不良データ(defect_records)は qms_db にある。ebom_db には存在しない。"
            "部品の不良を調べるには qms_db.defect_records の part_id と ebom_db.parts.id を突合すること。"
        ),
    },
    "procurement_db": {
        "label": "購買・調達",
        "engine": "MySQL 5.7",
        "detail": (
            "suppliers(payment_terms/otd_target_pct/currency: サプライヤー評価) / "
            "purchase_requisitions(現場の購買依頼。status='converted' で PO 化、'approved'/'requested' は未起票) / "
            "purchase_orders(plant_id/expected_delivery_date/total_amount/requisition_id) / "
            "deliveries(receipt_no/received_by) / "
            "supplier_part_catalog(部品×サプライヤー別の購入条件、is_primary=1 が主、=0 はセカンダリソース) / "
            "invoices(3-Way Match、match_status は matched/qty_mismatch/price_mismatch)。"
        ),
    },
    "scada_db": {
        "label": "設備稼働・生産実績 (SCADA)",
        "engine": "PostgreSQL 16",
        "detail": (
            "factories(id/name/region) / "
            "lines(id/factory_id/name: 拠点・ラインのマスタ。qms_db.inspections の line_id はここの id と対応) / "
            "equipment(line_id FK, installed_at/maker) / "
            "sensor_readings(equipment_id FK, recorded_at/temperature/pressure/vibration/runtime_minutes, quality: 192+ good) / "
            "production_events(line_id FK, occurred_at, event_type: running/stopped/maintenance, produced_qty/defect_qty: 1時間単位のライン稼働ステータス) / "
            "production_records(line_id FK, product_id, started_at/ended_at, good_count/defect_count, shift: day/night) / "
            "tags(equipment×物理量のマスタ TEMP/PRES/VIB/RUNTIME) / "
            "alarms(equipment_id FK, alarm_code/severity/time_on/time_ack/time_off/duration_s/description) / "
            "v_sensor_readings_long(タグ縦持ち view)。"
        ),
    },
    "wms_db": {
        "label": "倉庫・在庫 (WMS)",
        "engine": "PostgreSQL 13",
        "detail": (
            "warehouses(id/factory_id/name) / "
            "locations(warehouse_id FK) / "
            "inventory(part_id/location_id FK/qty: 現在庫数) / "
            "stock_movements(part_id/location_id FK/moved_at/direction: 'in'=入庫 'out'=出庫/qty/reason。"
            "日次消費量は direction='out' の qty を日付でグループ集計して算出する) / "
            "receipts(入荷予定 ASN、po_id は procurement.purchase_orders.id への論理参照) / "
            "shipments(carrier/tracking_no/status) / "
            "shipment_lines(出荷明細、lot_no 連動)。"
        ),
    },
    "qms_db": {
        "label": "品質管理 (QMS)",
        "engine": "PostgreSQL 14",
        "detail": (
            "inspections(line_id で scada_db.lines と対応。inspection_type: receiving/in_process/final, spec_id は quality_specs FK) / "
            "defect_records(inspection_id FK, part_id で ebom_db.parts と対応) / "
            "corrective_actions(action_type: containment/corrective/preventive, effectiveness 評価) / "
            "quality_specs(規格世代管理、customer_code IS NULL=社内規格、NOT NULL=顧客別納入規格、effective_to IS NULL が現行) / "
            "inspection_items(外観/寸法-外径/寸法-内径/重量/電気特性) / "
            "inspection_results(検査詳細値、measured_value で Cpk 分析可能) / "
            "four_m_changes(4M変更履歴: man/machine/material/method、is_planned で計画/突発を区別)。"
            "※ inspections に factory_id 列はない。拠点フィルタは scada_db.lines の factory_id を使って line_id で絞ること。"
        ),
    },
}

MYSQL_DATABASES = {"ebom_db", "procurement_db"}
POSTGRES_DATABASES = {"scada_db", "wms_db", "qms_db"}

FACTORY_NAMES = {1: "東京工場", 2: "大阪工場"}

# 高レベル業務ツール(ユースケース特化 API)。各ツールが内部で触る DB をすべて
# 許可されたロールにのみプロンプト上で提示する(MCP サーバーは全ツールを無条件公開
# するため、これは既存の DB allow-list と同じくプロンプト層のソフト統制)。
HIGH_LEVEL_TOOLS = [
    {
        "name": "get_top_defect_line(duration_days=30, factory_id=None, top_n=5)",
        "requires": {"qms_db", "scada_db"},
        "desc": "[UC①-1] 直近の不良件数が多いラインを特定。ライン名・工場名を解決し、関与部品の part_ids を返す(次の get_part_engineering_changes に渡せる)。",
    },
    {
        "name": "get_line_alarms_timeline(line_id, duration_days=30, limit=200)",
        "requires": {"scada_db"},
        "desc": "[UC①-2] 指定ラインの設備アラームを時系列で取得。line_id は get_top_defect_line の結果を渡す。",
    },
    {
        "name": "get_part_engineering_changes(part_ids, duration_months=6)",
        "requires": {"ebom_db"},
        "desc": "[UC①-3] 指定部品の設計変更(ECO)履歴を取得。対象期間に変更が無い部品は parts_with_no_eco に返る。",
    },
    {
        "name": "get_overdue_purchase_orders(plant_id=None, min_days_overdue=14, top_n=20)",
        "requires": {"procurement_db"},
        "desc": "[UC②-1] ordered のまま滞留している PO を経過日数降順で取得。part_ids を返す(次の在庫・使用先ツールに渡せる)。",
    },
    {
        "name": "get_part_inventory(part_ids, warehouse_id=None)",
        "requires": {"wms_db"},
        "desc": "[UC②-2] 部品の現在庫と直近 7 日の消費ペース・在庫日数を取得。",
    },
    {
        "name": "get_part_usage(part_ids)",
        "requires": {"ebom_db"},
        "desc": "[UC②-3] 部品がどの製品に使われているかを取得。",
    },
    {
        "name": "get_line_downtime_events(line_id, duration_days=1)",
        "requires": {"scada_db"},
        "desc": "[UC③-1] 指定ラインの停止・保全イベントを時系列で取得。停止時間帯を window_hint で返す(次のツールの start_at/end_at に使える)。",
    },
    {
        "name": "get_stock_movements_in_window(factory_id, start_at, end_at, direction='out')",
        "requires": {"wms_db"},
        "desc": "[UC③-2] 指定時間帯・拠点の入出庫を取得。start_at/end_at は ISO8601 文字列。window_hint を流用可。",
    },
]


def _high_level_tools_section(role: Role) -> str:
    """ロールが内部 DB をすべて許可されているツールだけを列挙する。"""
    allowed = set(role.allowed_databases)
    available = [t for t in HIGH_LEVEL_TOOLS if t["requires"] <= allowed]
    if not available:
        return ""
    lines = "\n".join(f"  - `{t['name']}`: {t['desc']}" for t in available)
    return (
        "\n## 高レベル業務ツール(優先して使うこと)\n\n"
        "代表ユースケース(UC①②③)は専用ツールにカプセル化されている。これらに該当する"
        "横断調査では `mysql_query` / `postgres_query` で**手書き SQL を書かず、必ず以下の専用ツールを使うこと**。"
        "専用ツールは内部で SQL 方言とクロス DB の ID 受け渡しを処理するため、構文エラーやクロス DB 結合の失敗が起きない。\n"
        f"{lines}\n"
    )


def build_system_prompt(role: Role) -> str:
    allowed_db_lines = "\n".join(
        f"  - {DB_DESCRIPTIONS[db]['label']} (`{db}`, {DB_DESCRIPTIONS[db]['engine']}): {DB_DESCRIPTIONS[db]['detail']}"
        for db in role.allowed_databases
    )
    mysql_allowed = sorted(set(role.allowed_databases) & MYSQL_DATABASES)
    postgres_allowed = sorted(set(role.allowed_databases) & POSTGRES_DATABASES)

    high_level_section = _high_level_tools_section(role)

    if role.is_all_factories:
        factory_clause = f"全拠点({' / '.join(FACTORY_NAMES.values())})のデータにアクセスできる。"
        factory_filter = ""
        scope_arg_hint = (
            "高レベル業務ツールの factory_id / plant_id / warehouse_id は省略してよい(全拠点)。"
        )
    else:
        ids = ", ".join(str(i) for i in role.factory_ids)
        names_str = " / ".join(FACTORY_NAMES[i] for i in role.factory_ids)
        first_id = role.factory_ids[0]
        factory_clause = f"アクセス可能な拠点は {names_str}(factory_id IN ({ids}))のみ。"
        factory_filter = (
            f"SCADA / WMS / QMS に対するクエリでは、必ず factory_id IN ({ids}) "
            f"あるいはそれに紐づく line_id でフィルタすること。"
            "scada.lines を JOIN するか、許可されたライン ID を WHERE 句に含めること。"
        )
        scope_arg_hint = (
            f"高レベル業務ツールを使う際は拠点スコープを必ず渡すこと: "
            f"factory_id={first_id} / plant_id={first_id} / warehouse_id={first_id}。"
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
- MySQL 側: mysql_list_databases / mysql_list_tables / mysql_describe_table / mysql_query
  - 使える database 引数: {', '.join(mysql_allowed) if mysql_allowed else '(なし)'}
- PostgreSQL 側: postgres_list_databases / postgres_list_tables / postgres_describe_table / postgres_query
  - 使える database 引数: {', '.join(postgres_allowed) if postgres_allowed else '(なし)'}
{high_level_section}{scope_arg_hint}

## DB 間の論理的な ID 連携（クロス DB 参照）

各 DB は物理的な外部キーを持たないが、以下の ID で論理的に紐づく:
- qms_db.inspections.line_id = scada_db.lines.id（ライン）
- qms_db.defect_records.part_id = ebom_db.parts.id（部品）
- wms_db.inventory.part_id = ebom_db.parts.id（部品）
- wms_db.stock_movements.part_id = ebom_db.parts.id（部品）
- wms_db.receipts.po_id = procurement_db.purchase_orders.id（発注）
- procurement_db.purchase_orders.part_id = ebom_db.parts.id（部品）
- procurement_db.parts.supplier_id = procurement_db.suppliers.id（サプライヤー）
- scada_db.equipment.line_id = scada_db.lines.id（ライン）
- scada_db.sensor_readings.equipment_id = scada_db.equipment.id（設備）
- scada_db.alarms.equipment_id = scada_db.equipment.id（設備）

**絶対禁止**: 各 DB は完全に独立したサーバーである。1 つのクエリの中に異なる DB のテーブルを含めることは不可能。JOIN だけでなく**サブクエリでも同様**。
- NG例: `mysql_query(database="ebom_db", sql="...WHERE part_id IN (SELECT part_id FROM defect_records...)")` → `defect_records` は qms_db にあるので ebom_db のクエリ内には書けない

**専用ツールがある業務は専用ツールを優先する**(上「高レベル業務ツール」参照)。専用ツールが無い ad-hoc な質問でのみ、以下の手順で生 SQL を分割実行する。

クロス DB 参照の正しい手順(必ず複数回のツール呼び出しに分割する):
1. DB-A でクエリを実行し、結果からIDリストを数値として取り出す (例: `[6, 12, 33]`)
2. DB-B で `WHERE id IN (6, 12, 33)` のようにリテラル値を直接埋め込んでクエリを実行する
3. 回答文でAとBの結果をマージする

UC①(品質→アラーム→設計変更の横断調査)は高レベルツールで実行する:
```
Step1: get_top_defect_line(duration_days=7, factory_id=<拠点 or 省略>) → 最多不良ラインと part_ids を得る
Step2: get_line_alarms_timeline(line_id=<Step1 の line_id>, duration_days=7)
Step3: get_part_engineering_changes(part_ids=<Step1 の part_ids>, duration_months=6)
```

## DB 間の SQL 構文の違い

MySQL(ebom_db / procurement_db) と PostgreSQL(scada_db / wms_db / qms_db) で構文が異なる点:
- 日付演算: MySQL = `NOW() - INTERVAL 6 MONTH` / PostgreSQL = `NOW() - INTERVAL '6 months'`
- 日付切り捨て: MySQL = `DATE(col)` / PostgreSQL = `DATE_TRUNC('day', col)`
- 文字列結合: MySQL = `CONCAT(a, b)` / PostgreSQL = `a || b`
- Boolean: MySQL = `1/0` / PostgreSQL = `TRUE/FALSE`

## ルール
1. クエリは SELECT / WITH / SHOW / DESCRIBE / EXPLAIN のみ使える(MCP 側で強制)。
2. 上の「アクセス可能な DB」に含まれない DB を指定してはいけない。指定するとアクセス違反として扱う。
3. 上の「拠点スコープ」や「アクセス可能な DB」に違反する範囲を要求された場合、またはツール呼び出し中に権限不足でデータを取得できなかった場合は、「あなたの権限では取得できないデータがあり回答ができません」と返すこと。違反する範囲については最初からツール呼び出しを行わないこと。
4. 質問に答えるために必要なら、複数の DB を順に問い合わせて結果をマージしてよい。上記「DB 間の論理的な ID 連携」を参照すること。
5. ツール呼び出し回数を最小化すること。「アクセス可能な DB」に記載のテーブル・カラム情報を最優先で使い、list_databases / list_tables / describe_table は既知でない情報だけに使う。
   - 同じ DB を複数回クエリする場合は JOIN や IN 句で 1 回のクエリに束ねること。
   - WHERE 条件に必要な ID が分かっている場合は事前に list / describe するより直接 SELECT すること。
   - クエリがエラーになった場合は同じ SQL を再試行せず、describe_table でカラムを確認してから修正すること。
6. 回答は日本語で。表形式が適切な場合は Markdown のテーブルで返す。クエリ結果の件数も併記する。
7. ID だけでなく必ず名称も合わせて表示すること。ただし名称取得のために「アクセス可能な DB」外のクエリを追加してはいけない。アクセス可能な場合のみ以下で取得する:
   - 部品名: ebom_db.parts.name / 製品名: ebom_db.products.name(ebom_db アクセス可能な場合のみ)
   - サプライヤー名: procurement_db.suppliers.name(procurement_db アクセス可能な場合のみ)
   - ライン名: scada_db.lines.name / 工場名: scada_db.factories.name(scada_db アクセス可能な場合のみ)
   - アクセス不可な DB の名称は ID のまま表示してよい。
"""
