"""ロールに応じてシステムプロンプトを組み立てる。"""

from __future__ import annotations

from auth import Role


DB_DESCRIPTIONS = {
    "ebom_db": {
        "label": "設計部品表 (E-BOM)",
        "engine": "MySQL 8.0",
        "detail": (
            "products / parts(uom/material/current_revision/lifecycle_status) / bom / "
            "engineering_changes(eco_no/status/effective_date/new_revision: ECO ワークフロー) / "
            "part_revisions(版数履歴、effective_to IS NULL が現行 Rev) / "
            "alternate_parts(設計上の互換代替品) / "
            "eco_part_links(1 ECO が複数部品に波及した記録)。"
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
            "factories / lines / equipment(installed_at/maker) / "
            "sensor_readings(quality 列追加: 192+ が good、64-191 uncertain、0-63 bad) / "
            "production_events(ライン×1時間ステータス: running/stopped/maintenance) / "
            "tags(equipment×物理量のマスタ TEMP/PRES/VIB/RUNTIME) / "
            "alarms(time_on/time_ack/time_off の状態遷移、duration_s は GENERATED) / "
            "production_records(ライン×シフトの実績、product_id 紐付き、good/defect_count は production_events と整合) / "
            "v_sensor_readings_long(タグ縦持ち view)。"
            "拠点・ラインのマスタはここが正。"
        ),
    },
    "wms_db": {
        "label": "倉庫・在庫 (WMS)",
        "engine": "PostgreSQL 13",
        "detail": (
            "warehouses / locations(zone/shelf に加え aisle/rack/bin/capacity_cubic_feet の4階層) / "
            "inventory(lot_no/expiry_date/status: available/allocated/shipped/quarantined) / "
            "stock_movements(reason は 納品/返品/引当/引当キャンセル/出荷確定 等) / "
            "receipts(入荷予定 ASN、po_id は procurement.purchase_orders.id への論理参照) / "
            "shipments(carrier/tracking_no/status) / "
            "shipment_lines(出荷明細、lot_no 連動)。"
        ),
    },
    "qms_db": {
        "label": "品質管理 (QMS)",
        "engine": "PostgreSQL 14",
        "detail": (
            "inspections(inspection_type: receiving/in_process/final, spec_id は quality_specs FK) / "
            "defect_records / "
            "corrective_actions(action_type: containment/corrective/preventive, effectiveness 評価) / "
            "quality_specs(規格世代管理、customer_code IS NULL=社内規格、NOT NULL=顧客別納入規格、effective_to IS NULL が現行) / "
            "inspection_items(外観/寸法-外径/寸法-内径/重量/電気特性) / "
            "inspection_results(検査詳細値、measured_value で Cpk 分析可能) / "
            "four_m_changes(4M変更履歴: man/machine/material/method、is_planned で計画/突発を区別)。"
        ),
    },
}

MYSQL_DATABASES = {"ebom_db", "procurement_db"}
POSTGRES_DATABASES = {"scada_db", "wms_db", "qms_db"}

FACTORY_NAMES = {1: "東京工場", 2: "大阪工場"}


def build_system_prompt(role: Role) -> str:
    allowed_db_lines = "\n".join(
        f"  - {DB_DESCRIPTIONS[db]['label']} (`{db}`, {DB_DESCRIPTIONS[db]['engine']}): {DB_DESCRIPTIONS[db]['detail']}"
        for db in role.allowed_databases
    )
    mysql_allowed = sorted(set(role.allowed_databases) & MYSQL_DATABASES)
    postgres_allowed = sorted(set(role.allowed_databases) & POSTGRES_DATABASES)

    if role.is_all_factories:
        factory_clause = f"全拠点({' / '.join(FACTORY_NAMES.values())})のデータにアクセスできる。"
        factory_filter = ""
    else:
        ids = ", ".join(str(i) for i in role.factory_ids)
        names_str = " / ".join(FACTORY_NAMES[i] for i in role.factory_ids)
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
- MySQL 側: mysql_list_databases / mysql_list_tables / mysql_describe_table / mysql_query
  - 使える database 引数: {', '.join(mysql_allowed) if mysql_allowed else '(なし)'}
- PostgreSQL 側: postgres_list_databases / postgres_list_tables / postgres_describe_table / postgres_query
  - 使える database 引数: {', '.join(postgres_allowed) if postgres_allowed else '(なし)'}

## ルール
1. クエリは SELECT / WITH / SHOW / DESCRIBE / EXPLAIN のみ使える(MCP 側で強制)。
2. 上の「アクセス可能な DB」に含まれない DB を指定してはいけない。指定するとアクセス違反として扱う。
3. 上の「拠点スコープ」や「アクセス可能な DB」に違反する範囲を要求された場合、またはツール呼び出し中に権限不足でデータを取得できなかった場合は、「あなたの権限では取得できないデータがあり回答ができません」と返すこと。違反する範囲については最初からツール呼び出しを行わないこと。
4. 質問に答えるために必要なら、複数の DB を順に問い合わせて結果をマージしてよい(クロス DB の論理的な ID 連携については `docs/database.md` を参照)。
5. テーブル構造が不明なら describe_table 系か list_tables 系を先に呼んで確認すること。MySQL の DB には mysql_ プレフィックスのツールを、PostgreSQL の DB には postgres_ プレフィックスのツールを使うこと。
6. 回答は日本語で。表形式が適切な場合は Markdown のテーブルで返す。クエリ結果の件数も併記する。
"""
