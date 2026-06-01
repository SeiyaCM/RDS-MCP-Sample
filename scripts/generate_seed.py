"""Seed SQL ファイルを生成するスクリプト。

実行: python scripts/generate_seed.py

5 つの DB 用の 02-seed.sql を db-init/ 配下に出力する。
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
DB_INIT = ROOT / "db-init"

START = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
DAYS = 30


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def write_sql(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(statements) + "\n"
    path.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)} ({len(statements)} statements, {len(body)} bytes)")


# ---------- マスタ定義(全 DB で共有する ID 体系) ----------

FACTORIES = [(1, "東京工場", "east"), (2, "大阪工場", "west")]
LINES = [
    (1, 1, "第1ライン"), (2, 1, "第2ライン"), (3, 1, "第3ライン"),
    (4, 2, "第1ライン"), (5, 2, "第2ライン"), (6, 2, "第3ライン"),
]
EQUIPMENT_TYPES = ["press", "weld", "assembly", "inspect"]
EQUIPMENT: list[tuple[int, int, str, str]] = []
for li in LINES:
    line_id = li[0]
    for i, t in enumerate(EQUIPMENT_TYPES):
        eq_id = (line_id - 1) * 4 + i + 1
        EQUIPMENT.append((eq_id, line_id, f"EQ-{line_id:02d}-{t[:3].upper()}", t))

SUPPLIERS = [
    (1, "東京製鋼株式会社", "日本", 3, "sales@tokyosteel.example.jp"),
    (2, "大阪ベアリング工業", "日本", 5, "info@osakabearings.example.jp"),
    (3, "深圳電子有限公司", "中国", 14, "trade@sze.example.cn"),
    (4, "バイエルン精密機械", "ドイツ", 21, "hello@bavpre.example.de"),
    (5, "デトロイト鋳造", "アメリカ", 28, "sales@detcast.example.com"),
    (6, "ハノイ樹脂工業", "ベトナム", 18, "ops@hanoiplast.example.vn"),
    (7, "プネ部品", "インド", 25, "biz@punecomp.example.in"),
    (8, "ソウルセンサ", "韓国", 10, "global@seoulsensors.example.kr"),
    (9, "台北電線", "台湾", 12, "info@taipeiwire.example.tw"),
    (10, "メキシコ工具", "メキシコ", 20, "ventas@mxtool.example.mx"),
]

PRODUCTS = [
    (1, "PROD-A", "小型EVモーター", "assembly"),
    (2, "PROD-B", "産業用ロボットアーム", "assembly"),
    (3, "PROD-C", "スマートインバータユニット", "module"),
]

# 部品 50 個
PART_KINDS = [
    ("bolt", "ボルト"), ("nut", "ナット"), ("shaft", "シャフト"), ("bearing", "ベアリング"),
    ("plate", "プレート"), ("frame", "フレーム"), ("cover", "カバー"), ("gear", "ギア"),
    ("coil", "コイル"), ("magnet", "マグネット"),
]
PARTS: list[tuple[int, str, str, int, float, int | None]] = []
pid = 1
for kind_code, kind_name in PART_KINDS:
    for n in range(1, 6):
        supplier_id = ((pid - 1) % 10) + 1
        cost = round(random.uniform(50, 2500), 2)
        product_id = ((pid - 1) % 3) + 1
        PARTS.append((pid, f"P-{kind_code.upper()}-{n:02d}", f"{kind_name} {n}", supplier_id, cost, product_id))
        pid += 1


# ---------- 共通ヘルパー(EBOM/Procurement で再利用) ----------

# 部品 kind → 物理単位(UoM)
KIND_UOM = {
    "bolt": "pcs", "nut": "pcs", "shaft": "pcs", "bearing": "pcs",
    "plate": "pcs", "frame": "pcs", "cover": "pcs", "gear": "pcs",
    "coil": "pcs", "magnet": "pcs",
}

# 部品 kind → 想定材質候補(意味型コードから派生)
KIND_MATERIALS = {
    "bolt": ["SUS304", "S45C"],
    "nut": ["SUS304", "S45C"],
    "shaft": ["S45C", "SCM440"],
    "bearing": ["SUJ2", "SUS440C"],
    "plate": ["SPCC", "A5052"],
    "frame": ["A6063", "SS400"],
    "cover": ["A5052", "ABS"],
    "gear": ["S45C", "SCM435"],
    "coil": ["Cu", "Al"],
    "magnet": ["NdFeB", "Ferrite"],
}

# 国 → 通貨
CURRENCY_BY_COUNTRY = {
    "日本": "JPY", "中国": "CNY", "ドイツ": "EUR", "アメリカ": "USD",
    "ベトナム": "VND", "インド": "INR", "韓国": "KRW", "台湾": "TWD",
    "メキシコ": "MXN",
}

# OTD 目標(納期遵守率)を国別に
OTD_TARGET_BY_COUNTRY = {
    "中国": 90.00, "ベトナム": 90.00, "インド": 90.00,
}

# 支払条件
PAYMENT_TERMS_BY_COUNTRY = {
    "日本": "NET30", "アメリカ": "NET30", "ドイツ": "NET30",
    "中国": "NET45", "ベトナム": "NET45", "インド": "NET45",
    "韓国": "NET30", "台湾": "NET30", "メキシコ": "NET45",
}


def part_kind(code: str) -> str:
    """部品コード 'P-BOLT-01' から kind 'bolt' を取り出す"""
    return code.split("-")[1].lower()


def part_material(code: str, rng: random.Random) -> str:
    """部品コードから材質を 1 つ選ぶ(決定論寄り)"""
    kind = part_kind(code)
    candidates = KIND_MATERIALS.get(kind, ["S45C"])
    # コードのハッシュで選択して、同じコードなら必ず同じ材質
    return candidates[hash(code) % len(candidates)]


def part_uom(code: str) -> str:
    return KIND_UOM.get(part_kind(code), "pcs")


def plant_for_part(part_id: int) -> int:
    """part_id 偶奇で 1=東京 / 2=大阪"""
    return 1 if part_id % 2 == 1 else 2


# ---------- 1. E-BOM (MySQL 8.0) ----------

def gen_ebom() -> None:
    stmts: list[str] = []

    stmts.append("-- products")
    vals = ",\n  ".join(f"({i},'{c}','{n}','{cat}')" for (i, c, n, cat) in PRODUCTS)
    stmts.append(f"INSERT INTO products (id, code, name, category) VALUES\n  {vals};")

    # 専用 RNG を使い、既存 SCADA/Procurement の random 系列に影響を与えない
    rng = random.Random(101)

    # ---- リビジョン履歴を先に確定。current_revision はその最終値と整合させる ----
    rev_rows: list[tuple[int, int, str, str, str | None, str, str]] = []
    # (id, part_id, revision, effective_from, effective_to|None, change_reason, released_by, released_at)
    # → タプルだと型が長いので簡易化
    rev_records: list[dict] = []
    rev_id = 1
    rev_reasons = ["初期リリース", "材質変更", "公差調整", "コスト削減", "品質改善"]
    rev_authors = ["東京設計者", "大阪設計者", "管理者"]
    part_current_rev: dict[int, str] = {}
    for part in PARTS:
        revs = ["A"]
        if rng.random() < 0.50:
            revs.append("B")
            if rng.random() < 0.20:
                revs.append("C")
        # effective ranges
        rev_dates: list[tuple[str, str | None]] = []
        # Rev.A は 2026-01-01 から
        cursor = datetime(2026, 1, 1)
        for idx, r in enumerate(revs):
            if idx < len(revs) - 1:
                # 次の Rev までの期間
                next_start = cursor + timedelta(days=rng.randint(30, 90))
                eff_to = (next_start - timedelta(days=1)).strftime("%Y-%m-%d")
                rev_dates.append((cursor.strftime("%Y-%m-%d"), eff_to))
                cursor = next_start
            else:
                rev_dates.append((cursor.strftime("%Y-%m-%d"), None))
        for r, (eff_from, eff_to) in zip(revs, rev_dates):
            released_at = datetime.strptime(eff_from, "%Y-%m-%d").replace(hour=rng.randint(9, 17))
            rev_records.append({
                "id": rev_id,
                "part_id": part[0],
                "revision": r,
                "effective_from": eff_from,
                "effective_to": eff_to,
                "change_reason": rev_reasons[0] if r == "A" else rng.choice(rev_reasons[1:]),
                "released_by": rng.choice(rev_authors),
                "released_at": fmt_dt(released_at),
            })
            rev_id += 1
        part_current_rev[part[0]] = revs[-1]

    # ---- parts (列追加版で INSERT) ----
    # lifecycle_status: 47=active / 2=eol / 1=obsolete
    lifecycle_overrides: dict[int, str] = {}
    eol_targets = rng.sample([p[0] for p in PARTS], 3)
    lifecycle_overrides[eol_targets[0]] = "eol"
    lifecycle_overrides[eol_targets[1]] = "eol"
    lifecycle_overrides[eol_targets[2]] = "obsolete"

    stmts.append("-- parts")
    parts_vals = []
    for (i, c, n, sup, cost, prod) in PARTS:
        uom = part_uom(c)
        material = part_material(c, rng)
        cur_rev = part_current_rev[i]
        lifecycle = lifecycle_overrides.get(i, "active")
        parts_vals.append(
            f"({i},'{c}','{n}',{sup},{cost},{prod},"
            f"'{uom}','{material}','{cur_rev}','{lifecycle}')"
        )
    vals = ",\n  ".join(parts_vals)
    stmts.append(
        "INSERT INTO parts (id, code, name, supplier_id, unit_cost, product_id, "
        "uom, material, current_revision, lifecycle_status) VALUES\n  "
        + vals + ";"
    )

    bom_rows: list[tuple[int, int, int, int]] = []
    bid = 1
    parents = [p for p in PARTS if p[5] is not None]
    children_pool = [p[0] for p in PARTS]
    for parent in parents:
        n_children = random.randint(1, 3)
        chosen = random.sample([c for c in children_pool if c != parent[0]], n_children)
        for child_id in chosen:
            qty = random.randint(1, 6)
            bom_rows.append((bid, parent[0], child_id, qty))
            bid += 1
    # 重複(parent, child)を取り除く
    seen = set()
    unique_bom = []
    for r in bom_rows:
        key = (r[1], r[2])
        if key in seen:
            continue
        seen.add(key)
        unique_bom.append(r)
    bom_rows = [(i + 1,) + r[1:] for i, r in enumerate(unique_bom)]

    stmts.append("-- bom")
    vals = ",\n  ".join(f"({i},{p},{c},{q})" for (i, p, c, q) in bom_rows)
    stmts.append(f"INSERT INTO bom (id, parent_part_id, child_part_id, qty) VALUES\n  {vals};")

    # ---- engineering_changes (拡張版) ----
    # 最初の 20 件は applied(過去日)、最後の 10 件は approved/requested で未来日 effective_date
    ec_rows = []
    reasons = ["材質変更", "公差調整", "コスト削減", "サプライヤー変更", "品質改善"]
    authors = ["東京設計者", "大阪設計者", "管理者"]
    for i in range(1, 31):
        part = random.choice(PARTS)
        offset_days = random.randint(0, DAYS - 1)
        when = START + timedelta(days=offset_days, hours=random.randint(8, 17))
        if i <= 20:
            status = "applied"
            eff_date = (when + timedelta(days=rng.randint(0, 5))).strftime("%Y-%m-%d")
        else:
            status = "approved" if rng.random() < 0.7 else "requested"
            eff_date = (when + timedelta(days=rng.randint(7, 30))).strftime("%Y-%m-%d")
        eco_no = f"ECO-2026-{i:04d}"
        # 新 Rev: 対象部品の current_revision を採用(=「この ECO で current にした」想定)
        new_rev = part_current_rev[part[0]]
        ec_rows.append({
            "id": i,
            "part_id": part[0],
            "changed_at": fmt_dt(when),
            "reason": random.choice(reasons),
            "changed_by": random.choice(authors),
            "eco_no": eco_no,
            "status": status,
            "effective_date": eff_date,
            "new_revision": new_rev,
        })

    stmts.append("-- engineering_changes")
    ec_vals = ",\n  ".join(
        f"({r['id']},{r['part_id']},'{r['changed_at']}','{r['reason']}','{r['changed_by']}',"
        f"'{r['eco_no']}','{r['status']}','{r['effective_date']}','{r['new_revision']}')"
        for r in ec_rows
    )
    stmts.append(
        "INSERT INTO engineering_changes (id, part_id, changed_at, reason, changed_by, "
        "eco_no, status, effective_date, new_revision) VALUES\n  "
        + ec_vals + ";"
    )

    # ---- part_revisions ----
    stmts.append("-- part_revisions")
    rev_vals = ",\n  ".join(
        f"({r['id']},{r['part_id']},'{r['revision']}','{r['effective_from']}',"
        + ("NULL" if r["effective_to"] is None else f"'{r['effective_to']}'")
        + f",'{r['change_reason']}','{r['released_by']}','{r['released_at']}')"
        for r in rev_records
    )
    stmts.append(
        "INSERT INTO part_revisions (id, part_id, revision, effective_from, effective_to, "
        "change_reason, released_by, released_at) VALUES\n  "
        + rev_vals + ";"
    )

    # ---- alternate_parts (同 kind ペアから 12 件) ----
    kind_buckets: dict[str, list[int]] = {}
    for p in PARTS:
        kind_buckets.setdefault(part_kind(p[1]), []).append(p[0])
    alt_pairs: list[tuple[int, int]] = []
    kinds_with_multiple = [k for k, v in kind_buckets.items() if len(v) >= 2]
    while len(alt_pairs) < 12 and kinds_with_multiple:
        k = rng.choice(kinds_with_multiple)
        bucket = kind_buckets[k]
        a, b = rng.sample(bucket, 2)
        pair = (min(a, b), max(a, b))
        if pair not in [(x, y) for (x, y) in alt_pairs] and (pair[1], pair[0]) not in alt_pairs:
            alt_pairs.append((a, b))
    compatibilities = ["full", "full", "full", "full", "form_fit", "form_fit", "functional"]
    stmts.append("-- alternate_parts")
    alt_vals = ",\n  ".join(
        f"({idx + 1},{a},{b},'{rng.choice(compatibilities)}','同 kind 内の互換品')"
        for idx, (a, b) in enumerate(alt_pairs)
    )
    stmts.append(
        "INSERT INTO alternate_parts (id, primary_part_id, alternate_part_id, compatibility, note) VALUES\n  "
        + alt_vals + ";"
    )

    # ---- eco_part_links (各 ECO に主部品 1 件 + 20% で同 kind の追加 1-2 件) ----
    link_rows: list[tuple[int, int, str]] = []
    for ec in ec_rows:
        eco_id = ec["id"]
        main_part = ec["part_id"]
        link_rows.append((eco_id, main_part, "changed"))
        if rng.random() < 0.20:
            main_kind = part_kind(next(p[1] for p in PARTS if p[0] == main_part))
            bucket = [pid for pid in kind_buckets.get(main_kind, []) if pid != main_part]
            extras = rng.sample(bucket, min(rng.randint(1, 2), len(bucket)))
            for x in extras:
                link_rows.append((eco_id, x, rng.choice(["changed", "changed", "added"])))
    stmts.append("-- eco_part_links")
    link_vals = ",\n  ".join(f"({e},{p},'{imp}')" for (e, p, imp) in link_rows)
    stmts.append(
        "INSERT INTO eco_part_links (eco_id, part_id, impact) VALUES\n  "
        + link_vals + ";"
    )

    write_sql(DB_INIT / "ebom" / "02-seed.sql", stmts)


# ---------- 2. 購買・調達 (MySQL 5.7) ----------

def gen_procurement() -> dict:
    """Procurement の seed を出力し、WMS 側に渡すための PO/Delivery 情報を返す。

    戻り値: {"po_rows": [...], "delivery_rows": [...]}
    """
    stmts: list[str] = []
    rng = random.Random(202)  # procurement 拡張用の独立 RNG

    # ---- suppliers (列追加) ----
    stmts.append("-- suppliers")
    sup_vals = []
    for (i, n, c, lt, e) in SUPPLIERS:
        currency = CURRENCY_BY_COUNTRY.get(c, "JPY")
        terms = PAYMENT_TERMS_BY_COUNTRY.get(c, "NET30")
        otd = OTD_TARGET_BY_COUNTRY.get(c, 95.00)
        sup_vals.append(
            f"({i},'{n}','{c}',{lt},'{e}','{terms}',{otd:.2f},'{currency}',1)"
        )
    stmts.append(
        "INSERT INTO suppliers (id, name, country, lead_time_days, contact_email, "
        "payment_terms, otd_target_pct, currency, is_active) VALUES\n  "
        + ",\n  ".join(sup_vals) + ";"
    )

    # ---- 先に PO の中身を組み立てる(req とのリンクに使う) ----
    po_rows: list[tuple[int, int, int, datetime, int, float, str]] = []
    poid = 1
    for d in range(DAYS):
        n_orders = random.randint(5, 8)
        for _ in range(n_orders):
            part = random.choice(PARTS)
            supplier_id = part[3]
            ordered = START + timedelta(days=d, hours=random.randint(8, 17))
            qty = random.choice([20, 30, 50, 100, 200])
            unit_price = round(part[4] * random.uniform(0.9, 1.05), 2)
            elapsed = (START + timedelta(days=DAYS - 1)) - ordered
            if elapsed.days > 14:
                status = random.choices(["delivered", "partial", "cancelled"], weights=[80, 15, 5])[0]
            elif elapsed.days > 5:
                status = random.choices(["delivered", "partial", "ordered"], weights=[40, 35, 25])[0]
            else:
                status = "ordered"
            po_rows.append((poid, supplier_id, part[0], ordered, qty, unit_price, status))
            poid += 1

    # ---- purchase_requisitions ----
    # 80% の PO に対応する converted な依頼を生成
    requisitions: list[dict] = []
    req_id = 1
    po_id_to_req_id: dict[int, int] = {}
    plant_names = {1: "東京工場", 2: "大阪工場"}
    requesters = {1: ["東京購買A", "東京購買B", "東京設計者"], 2: ["大阪購買A", "大阪購買B", "大阪設計者"]}
    for po in po_rows:
        po_id, supplier_id, part_id_, ordered, qty, _, _ = po
        plant_id = plant_for_part(part_id_)
        if rng.random() < 0.80:
            requested_at = ordered - timedelta(days=rng.randint(3, 10))
            needed_by = (ordered + timedelta(days=SUPPLIERS[supplier_id - 1][3])).date()
            requisitions.append({
                "id": req_id,
                "no": f"PR-2026-{req_id:06d}",
                "plant_id": plant_id,
                "part_id": part_id_,
                "qty": qty,
                "requested_by": rng.choice(requesters[plant_id]),
                "requested_at": fmt_dt(requested_at),
                "needed_by": needed_by.strftime("%Y-%m-%d"),
                "status": "converted",
            })
            po_id_to_req_id[po_id] = req_id
            req_id += 1

    # PO に紐付かない approved (PO 未起票) と requested (承認待ち) を追加
    for _ in range(15):
        part = random.choice(PARTS)
        plant_id = plant_for_part(part[0])
        requested_at = START + timedelta(days=rng.randint(0, DAYS - 1), hours=rng.randint(9, 17))
        requisitions.append({
            "id": req_id,
            "no": f"PR-2026-{req_id:06d}",
            "plant_id": plant_id,
            "part_id": part[0],
            "qty": rng.choice([20, 30, 50, 100]),
            "requested_by": rng.choice(requesters[plant_id]),
            "requested_at": fmt_dt(requested_at),
            "needed_by": (requested_at + timedelta(days=rng.randint(7, 21))).strftime("%Y-%m-%d"),
            "status": "approved",
        })
        req_id += 1
    for _ in range(10):
        part = random.choice(PARTS)
        plant_id = plant_for_part(part[0])
        requested_at = START + timedelta(days=rng.randint(DAYS - 7, DAYS - 1), hours=rng.randint(9, 17))
        requisitions.append({
            "id": req_id,
            "no": f"PR-2026-{req_id:06d}",
            "plant_id": plant_id,
            "part_id": part[0],
            "qty": rng.choice([20, 30, 50]),
            "requested_by": rng.choice(requesters[plant_id]),
            "requested_at": fmt_dt(requested_at),
            "needed_by": (requested_at + timedelta(days=rng.randint(7, 21))).strftime("%Y-%m-%d"),
            "status": "requested",
        })
        req_id += 1

    stmts.append("-- purchase_requisitions")
    req_vals = ",\n  ".join(
        f"({r['id']},'{r['no']}',{r['plant_id']},{r['part_id']},{r['qty']},"
        f"'{r['requested_by']}','{r['requested_at']}','{r['needed_by']}','{r['status']}')"
        for r in requisitions
    )
    stmts.append(
        "INSERT INTO purchase_requisitions (id, requisition_no, plant_id, part_id, qty, "
        "requested_by, requested_at, needed_by, status) VALUES\n  "
        + req_vals + ";"
    )

    # ---- purchase_orders (列追加版) ----
    stmts.append("-- purchase_orders")
    po_vals = []
    for (i, s, p, o, q, up, st) in po_rows:
        plant_id = plant_for_part(p)
        lead = SUPPLIERS[s - 1][3]
        expected = (o + timedelta(days=lead)).date().strftime("%Y-%m-%d")
        total = round(q * up, 2)
        req_ref = po_id_to_req_id.get(i)
        req_str = "NULL" if req_ref is None else str(req_ref)
        po_vals.append(
            f"({i},{s},{p},'{fmt_dt(o)}',{q},{up},'{st}',"
            f"{plant_id},{req_str},'{expected}',{total})"
        )
    stmts.append(
        "INSERT INTO purchase_orders (id, supplier_id, part_id, ordered_at, qty, unit_price, status, "
        "plant_id, requisition_id, expected_delivery_date, total_amount) VALUES\n  "
        + ",\n  ".join(po_vals) + ";"
    )

    # ---- deliveries (列追加版) ----
    delivery_rows: list[tuple[int, int, datetime, int, int]] = []
    did = 1
    receivers = ["受入A", "受入B", "受入C"]
    delivery_records: list[dict] = []
    for po in po_rows:
        po_id, supplier_id, _, ordered, qty, _, status = po
        if status in ("delivered", "partial"):
            lead = SUPPLIERS[supplier_id - 1][3]
            delivered_at = ordered + timedelta(days=lead + random.randint(-2, 3))
            if status == "delivered":
                received = qty
            else:
                received = max(1, int(qty * random.uniform(0.4, 0.85)))
            rejected = int(received * random.uniform(0, 0.05))
            delivery_rows.append((did, po_id, delivered_at, received, rejected))
            delivery_records.append({
                "id": did,
                "po_id": po_id,
                "delivered_at": fmt_dt(delivered_at),
                "qty_received": received,
                "qty_rejected": rejected,
                "receipt_no": f"GR-2026-{did:06d}",
                "received_by": rng.choice(receivers),
            })
            did += 1

    stmts.append("-- deliveries")
    del_vals = ",\n  ".join(
        f"({r['id']},{r['po_id']},'{r['delivered_at']}',{r['qty_received']},{r['qty_rejected']},"
        f"'{r['receipt_no']}','{r['received_by']}')"
        for r in delivery_records
    )
    stmts.append(
        "INSERT INTO deliveries (id, po_id, delivered_at, qty_received, qty_rejected, receipt_no, received_by) VALUES\n  "
        + del_vals + ";"
    )

    # ---- supplier_part_catalog ----
    # 各 part につき primary を 1 件、50% でセカンダリを 1 件追加
    catalog: list[dict] = []
    cat_id = 1
    for part in PARTS:
        # primary
        catalog.append({
            "id": cat_id,
            "supplier_id": part[3],
            "part_id": part[0],
            "supplier_part_no": f"{SUPPLIERS[part[3] - 1][1][:3].upper()}-{part[1]}",
            "lead_time_days": SUPPLIERS[part[3] - 1][3],
            "unit_price": part[4],
            "moq": rng.choice([1, 10, 20, 50]),
            "is_primary": 1,
            "valid_from": "2026-01-01",
            "valid_to": None,
        })
        cat_id += 1
        if rng.random() < 0.50:
            # secondary: 別のサプライヤー(同 kind の他部品が紐付くサプライヤーから選ぶ)
            alt_sup_pool = [s for s in range(1, 11) if s != part[3]]
            alt_sup = rng.choice(alt_sup_pool)
            alt_lead = max(2, SUPPLIERS[alt_sup - 1][3] + rng.randint(-3, 5))
            alt_price = round(part[4] * rng.uniform(0.92, 1.12), 2)
            catalog.append({
                "id": cat_id,
                "supplier_id": alt_sup,
                "part_id": part[0],
                "supplier_part_no": f"{SUPPLIERS[alt_sup - 1][1][:3].upper()}-{part[1]}-ALT",
                "lead_time_days": alt_lead,
                "unit_price": alt_price,
                "moq": rng.choice([10, 20, 50, 100]),
                "is_primary": 0,
                "valid_from": "2026-01-01",
                "valid_to": None,
            })
            cat_id += 1

    stmts.append("-- supplier_part_catalog")
    cat_vals = ",\n  ".join(
        f"({c['id']},{c['supplier_id']},{c['part_id']},'{c['supplier_part_no']}',"
        f"{c['lead_time_days']},{c['unit_price']},{c['moq']},{c['is_primary']},"
        f"'{c['valid_from']}',"
        + ("NULL" if c["valid_to"] is None else f"'{c['valid_to']}'")
        + ")"
        for c in catalog
    )
    stmts.append(
        "INSERT INTO supplier_part_catalog (id, supplier_id, part_id, supplier_part_no, "
        "lead_time_days, unit_price, moq, is_primary, valid_from, valid_to) VALUES\n  "
        + cat_vals + ";"
    )

    # ---- invoices (3-Way Match) ----
    # delivered/partial の 90% に対し請求書を発行。
    # 92% matched / 5% qty_mismatch / 3% price_mismatch
    invoices: list[dict] = []
    inv_id = 1
    # po_id -> supplier_id, unit_price のルックアップ
    po_lookup = {p[0]: (p[1], p[5]) for p in po_rows}
    for d in delivery_records:
        if rng.random() >= 0.90:
            continue
        supplier_id, po_unit_price = po_lookup[d["po_id"]]
        sup = SUPPLIERS[supplier_id - 1]
        terms = PAYMENT_TERMS_BY_COUNTRY.get(sup[2], "NET30")
        terms_days = int(terms.replace("NET", ""))
        invoice_date = datetime.strptime(d["delivered_at"][:10], "%Y-%m-%d") + timedelta(days=rng.randint(3, 10))
        due_date = invoice_date + timedelta(days=terms_days)
        # Match status の判定
        roll = rng.random()
        if roll < 0.92:
            match_status = "matched"
            qty_billed = d["qty_received"]
            unit_price_inv = po_unit_price
        elif roll < 0.97:
            match_status = "qty_mismatch"
            qty_billed = d["qty_received"] + rng.choice([-5, -3, 3, 5])
            qty_billed = max(1, qty_billed)
            unit_price_inv = po_unit_price
        else:
            match_status = "price_mismatch"
            qty_billed = d["qty_received"]
            unit_price_inv = round(po_unit_price * 1.10, 2)
        amount = round(qty_billed * unit_price_inv, 2)
        paid_at = None
        if rng.random() < 0.70 and match_status == "matched":
            paid_at = (due_date + timedelta(days=rng.randint(-3, 5))).strftime("%Y-%m-%d")
        invoices.append({
            "id": inv_id,
            "no": f"INV-2026-{inv_id:06d}",
            "supplier_id": supplier_id,
            "po_id": d["po_id"],
            "delivery_id": d["id"],
            "invoice_date": invoice_date.strftime("%Y-%m-%d"),
            "due_date": due_date.strftime("%Y-%m-%d"),
            "qty_billed": qty_billed,
            "unit_price": unit_price_inv,
            "amount": amount,
            "currency": CURRENCY_BY_COUNTRY.get(sup[2], "JPY"),
            "match_status": match_status,
            "paid_at": paid_at,
        })
        inv_id += 1

    stmts.append("-- invoices")
    inv_vals = ",\n  ".join(
        f"({i['id']},'{i['no']}',{i['supplier_id']},{i['po_id']},"
        + (f"{i['delivery_id']}" if i['delivery_id'] is not None else "NULL")
        + f",'{i['invoice_date']}','{i['due_date']}',{i['qty_billed']},{i['unit_price']},"
        f"{i['amount']},'{i['currency']}','{i['match_status']}',"
        + ("NULL" if i["paid_at"] is None else f"'{i['paid_at']}'")
        + ")"
        for i in invoices
    )
    stmts.append(
        "INSERT INTO invoices (id, invoice_no, supplier_id, po_id, delivery_id, "
        "invoice_date, due_date, qty_billed, unit_price, amount, currency, match_status, paid_at) VALUES\n  "
        + inv_vals + ";"
    )

    write_sql(DB_INIT / "procurement" / "02-seed.sql", stmts)
    return {"po_rows": po_rows, "delivery_rows": delivery_rows}


# ---------- 3. SCADA (Postgres 16) ----------

def gen_scada() -> list[tuple[int, int, int, datetime, str, int, int]]:
    stmts: list[str] = []

    stmts.append("-- factories")
    vals = ",\n  ".join(f"({i},'{n}','{r}')" for (i, n, r) in FACTORIES)
    stmts.append(f"INSERT INTO factories (id, name, region) VALUES\n  {vals};")

    stmts.append("-- lines")
    vals = ",\n  ".join(f"({i},{f},'{n}')" for (i, f, n) in LINES)
    stmts.append(f"INSERT INTO lines (id, factory_id, name) VALUES\n  {vals};")

    # equipment: installed_at / maker を埋める
    stmts.append("-- equipment")
    eq_makers = ["FANUC", "Yaskawa", "Mitsubishi", "Omron", "Keyence", "Siemens"]
    eq_rng = random.Random(301)
    eq_vals = []
    for (i, lid, n, t) in EQUIPMENT:
        # 設備 id を決定論的に installed_at と maker にマップ
        installed = (datetime(2023, 4, 1) + timedelta(days=(i - 1) * 30)).date().strftime("%Y-%m-%d")
        maker = eq_makers[(i - 1) % len(eq_makers)]
        eq_vals.append(f"({i},{lid},'{n}','{t}','{installed}','{maker}')")
    stmts.append(
        "INSERT INTO equipment (id, line_id, name, type, installed_at, maker) VALUES\n  "
        + ",\n  ".join(eq_vals) + ";"
    )

    # sensor_readings: 24 設備 × 24h × 30日 = 17,280 行。バッチに分けて INSERT
    # 同時にしきい値超過を検出して alarms に積む。
    sensor_rows: list[str] = []
    alarm_records: list[dict] = []
    alarm_rng = random.Random(302)
    active_alarm_until: dict[int, datetime] = {}  # equipment_id -> 復帰予定時刻
    for eq_id, line_id, _, _ in EQUIPMENT:
        for d in range(DAYS):
            for h in range(24):
                ts = START + timedelta(days=d, hours=h)
                base_temp = 35 + (eq_id % 5) * 2
                temp = round(base_temp + random.uniform(-3, 5), 2)
                pressure = round(0.4 + random.uniform(-0.05, 0.05), 2)
                vibration = round(0.15 + random.uniform(-0.05, 0.08), 3)
                # 深夜/早朝は稼働低下
                if 0 <= h < 6:
                    runtime = round(random.uniform(0, 20), 2)
                elif 6 <= h < 22:
                    runtime = round(random.uniform(45, 60), 2)
                else:
                    runtime = round(random.uniform(20, 50), 2)
                # 品質: 極端なしきい値超過は uncertain
                quality = 192
                triggered_alarm = None
                # アラーム閾値は厳しめに(1時間粒度データなので過剰発生を抑える)
                if temp >= 44.0:
                    quality = 64
                    triggered_alarm = ("HIGH_TEMP", "warn" if temp < 45.0 else "crit",
                                       f"温度高({temp}℃)")
                elif vibration >= 0.228:
                    quality = 64
                    triggered_alarm = ("OVER_VIB", "warn",
                                       f"振動異常({vibration}mm/s)")
                sensor_rows.append(
                    f"({eq_id},'{fmt_dt(ts)}+00',{temp},{pressure},{vibration},{runtime},{quality})"
                )
                # alarm 状態管理: 同一設備で active なアラームがあれば新規発生させない
                # クールダウンを長め(平均 4 時間)に取ることで実際的な件数(設備あたり数件)に抑える
                if triggered_alarm and active_alarm_until.get(eq_id, datetime.min.replace(tzinfo=timezone.utc)) < ts:
                    code, sev, desc = triggered_alarm
                    duration_min = alarm_rng.randint(30, 180)
                    time_off = ts + timedelta(minutes=duration_min)
                    # クールダウン(再発防止)期間。同一設備で連続発生しないように長めに取る
                    cooldown_until = time_off + timedelta(hours=alarm_rng.randint(24, 72))
                    time_ack = ts + timedelta(minutes=alarm_rng.randint(1, max(1, duration_min // 2)))
                    alarm_records.append({
                        "equipment_id": eq_id,
                        "alarm_code": code,
                        "severity": sev,
                        "time_on": fmt_dt(ts),
                        "time_ack": fmt_dt(time_ack),
                        "time_off": fmt_dt(time_off),
                        "description": desc,
                    })
                    active_alarm_until[eq_id] = cooldown_until

    stmts.append("-- sensor_readings")
    batch = 500
    for i in range(0, len(sensor_rows), batch):
        chunk = ",\n  ".join(sensor_rows[i:i + batch])
        stmts.append(
            "INSERT INTO sensor_readings (equipment_id, recorded_at, temperature, pressure, vibration, runtime_minutes, quality) VALUES\n  "
            + chunk + ";"
        )

    # production_events: ライン × 24h × 30日。1日に1ラインあたり、稼働3〜4 / 停止1 / メンテ稀
    prod_rows: list[tuple[int, int, datetime, str, int, int]] = []
    eid = 1
    for line_id_, _, _ in [(li[0], li[1], li[2]) for li in LINES]:
        for d in range(DAYS):
            for h in range(24):
                ts = START + timedelta(days=d, hours=h)
                if 0 <= h < 6:
                    event = random.choices(["stopped", "running"], weights=[80, 20])[0]
                elif 6 <= h < 22:
                    event = random.choices(["running", "stopped", "maintenance"], weights=[88, 8, 4])[0]
                else:
                    event = random.choices(["running", "stopped"], weights=[60, 40])[0]
                if event == "running":
                    produced = random.randint(80, 130)
                    defect = max(0, int(produced * random.uniform(0.005, 0.04)))
                else:
                    produced = 0
                    defect = 0
                prod_rows.append((eid, line_id_, ts, event, produced, defect))
                eid += 1

    stmts.append("-- production_events")
    vals_list = [
        f"({lid},'{fmt_dt(ts)}+00','{ev}',{pq},{dq})"
        for (_, lid, ts, ev, pq, dq) in prod_rows
    ]
    for i in range(0, len(vals_list), batch):
        chunk = ",\n  ".join(vals_list[i:i + batch])
        stmts.append(
            "INSERT INTO production_events (line_id, occurred_at, event_type, produced_qty, defect_qty) VALUES\n  "
            + chunk + ";"
        )

    # ---- tags (24 equipment × 4 tag = 96 行) ----
    tag_defs = [
        ("TEMP", "℃"),
        ("PRES", "MPa"),
        ("VIB", "mm/s"),
        ("RUNTIME", "min"),
    ]
    tag_rows: list[str] = []
    tid = 1
    for (eq_id, _line_id, _name, _typ) in EQUIPMENT:
        for tag_name, unit in tag_defs:
            tag_rows.append(f"({tid},{eq_id},'{tag_name}','{unit}','float')")
            tid += 1
    stmts.append("-- tags")
    stmts.append(
        "INSERT INTO tags (id, equipment_id, tag_name, unit, data_type) VALUES\n  "
        + ",\n  ".join(tag_rows) + ";"
    )

    # ---- alarms (しきい値超過から集めたイベント) ----
    if alarm_records:
        stmts.append("-- alarms")
        alarm_vals = ",\n  ".join(
            f"({i + 1},{a['equipment_id']},'{a['alarm_code']}','{a['severity']}',"
            f"'{a['time_on']}+00','{a['time_ack']}+00','{a['time_off']}+00','{a['description']}')"
            for i, a in enumerate(alarm_records)
        )
        stmts.append(
            "INSERT INTO alarms (id, equipment_id, alarm_code, severity, time_on, time_ack, time_off, description) VALUES\n  "
            + alarm_vals + ";"
        )

    # ---- production_records (6 lines × 30 days × 2 shifts = 360 行) ----
    # 同期間の production_events を集計して good/defect を導出することで、
    # 旧 production_events と新 production_records の数値が整合する。
    # まず line × day × shift で集計値を作る
    shift_buckets: dict[tuple[int, int, str], dict] = {}  # (line_id, day, shift) -> {produced, defect}
    for (_, lid, ts, ev, pq, dq) in prod_rows:
        d = (ts - START).days
        h = ts.hour
        shift = "day" if 6 <= h < 22 else "night"
        key = (lid, d, shift)
        b = shift_buckets.setdefault(key, {"produced": 0, "defect": 0})
        b["produced"] += pq
        b["defect"] += dq

    pr_rows: list[str] = []
    pr_id = 1
    for (lid, d, shift), agg in sorted(shift_buckets.items()):
        # line_id 1-3 = product_id 1-2, line_id 4-6 = product_id 2-3 のようにマップ
        product_id = ((lid - 1) % 3) + 1
        if shift == "day":
            started = START + timedelta(days=d, hours=6)
            ended = START + timedelta(days=d, hours=22)
        else:
            started = START + timedelta(days=d, hours=22)
            ended = START + timedelta(days=d + 1, hours=6)
        good = agg["produced"] - agg["defect"]
        pr_rows.append(
            f"({pr_id},{lid},{product_id},'{fmt_dt(started)}+00','{fmt_dt(ended)}+00',{good},{agg['defect']},'{shift}')"
        )
        pr_id += 1
    stmts.append("-- production_records")
    for i in range(0, len(pr_rows), batch):
        chunk = ",\n  ".join(pr_rows[i:i + batch])
        stmts.append(
            "INSERT INTO production_records (id, line_id, product_id, started_at, ended_at, good_count, defect_count, shift) VALUES\n  "
            + chunk + ";"
        )

    write_sql(DB_INIT / "scada" / "02-seed.sql", stmts)
    return prod_rows


# ---------- 4. WMS (Postgres 13) ----------

def gen_wms(po_rows: list | None = None, delivery_rows: list | None = None) -> None:
    stmts: list[str] = []
    po_rows = po_rows or []
    delivery_rows = delivery_rows or []
    rng = random.Random(401)  # WMS 拡張用

    warehouses = [(1, 1, "東京倉庫"), (2, 2, "大阪倉庫")]
    stmts.append("-- warehouses")
    vals = ",\n  ".join(f"({i},{f},'{n}')" for (i, f, n) in warehouses)
    stmts.append(f"INSERT INTO warehouses (id, factory_id, name) VALUES\n  {vals};")

    # locations: 既存 zone/shelf を維持しつつ aisle/rack/bin/capacity を埋める
    locations: list[tuple[int, int, str, str]] = []
    lid = 1
    for w in warehouses:
        for zone in ("A", "B", "C"):
            for shelf_n in range(1, 4):
                locations.append((lid, w[0], zone, f"S{shelf_n:02d}"))
                lid += 1

    stmts.append("-- locations")
    loc_vals = []
    capacity_by_zone = {"A": 30.00, "B": 50.00, "C": 80.00}
    for (i, w, z, s) in locations:
        aisle = f"{((i - 1) % 3) + 1:02d}"
        rack = f"R{z}"
        bin_ = f"B{s[-1]}"
        cap = capacity_by_zone[z]
        loc_vals.append(f"({i},{w},'{z}','{s}','{aisle}','{rack}','{bin_}',{cap})")
    stmts.append(
        "INSERT INTO locations (id, warehouse_id, zone, shelf, aisle, rack, bin, capacity_cubic_feet) VALUES\n  "
        + ",\n  ".join(loc_vals) + ";"
    )

    # inventory: 既存ロジック + lot_no / expiry_date / status を追加
    inventory_records: list[dict] = []
    inv_id = 1
    inv_keys: set[tuple[int, int]] = set()
    for part in PARTS:
        n_locs = random.randint(1, 2)
        chosen_locs = random.sample(locations, n_locs)
        for loc in chosen_locs:
            key = (part[0], loc[0])
            if key in inv_keys:
                continue
            inv_keys.add(key)
            qty = random.randint(10, 500)
            ts = START + timedelta(days=random.randint(0, DAYS - 1), hours=random.randint(0, 23))
            kind = part_kind(part[1])
            # lot 管理は 30% 程度の在庫にだけ付与
            lot_no = None
            expiry = None
            if rng.random() < 0.30:
                lot_no = f"L-202605-{inv_id:03d}"
                if kind in ("magnet", "coil"):
                    expiry = (ts + timedelta(days=365)).date().strftime("%Y-%m-%d")
            # status: 90% available / 8% allocated / 2% quarantined
            r_status = rng.random()
            if r_status < 0.90:
                status = "available"
            elif r_status < 0.98:
                status = "allocated"
            else:
                status = "quarantined"
            inventory_records.append({
                "id": inv_id,
                "part_id": part[0],
                "location_id": loc[0],
                "qty": qty,
                "updated_at": fmt_dt(ts),
                "lot_no": lot_no,
                "expiry_date": expiry,
                "status": status,
            })
            inv_id += 1

    stmts.append("-- inventory")
    inv_vals = ",\n  ".join(
        f"({r['id']},{r['part_id']},{r['location_id']},{r['qty']},'{r['updated_at']}+00',"
        + ("NULL" if r["lot_no"] is None else f"'{r['lot_no']}'") + ","
        + ("NULL" if r["expiry_date"] is None else f"'{r['expiry_date']}'") + ","
        + f"'{r['status']}')"
        for r in inventory_records
    )
    stmts.append(
        "INSERT INTO inventory (id, part_id, location_id, qty, updated_at, lot_no, expiry_date, status) VALUES\n  "
        + inv_vals + ";"
    )

    # stock_movements: 既存ロジックに「引当」「引当キャンセル」「出荷確定」reason を追加
    move_rows: list[tuple[int, int, str, str, int, str]] = []
    mid = 1
    reasons_in = ["納品", "返品", "他拠点入庫", "引当キャンセル"]
    reasons_out = ["生産投入", "廃棄", "他拠点出庫", "引当", "出荷確定"]
    for d in range(DAYS):
        n_moves = random.randint(15, 25)
        for _ in range(n_moves):
            part = random.choice(PARTS)
            loc = random.choice(locations)
            ts = START + timedelta(days=d, hours=random.randint(6, 22))
            direction = random.choice(["in", "out"])
            qty = random.randint(5, 80)
            reason = random.choice(reasons_in if direction == "in" else reasons_out)
            move_rows.append((mid, part[0], fmt_dt(ts), direction, qty, reason))
            mid += 1

    stmts.append("-- stock_movements")
    move_full: list[str] = []
    for idx, (_, part_id, ts, direction, qty, reason) in enumerate(move_rows):
        loc = locations[idx % len(locations)]
        move_full.append(f"({part_id},{loc[0]},'{ts}+00','{direction}',{qty},'{reason}')")
    batch = 200
    for i in range(0, len(move_full), batch):
        chunk = ",\n  ".join(move_full[i:i + batch])
        stmts.append(
            "INSERT INTO stock_movements (part_id, location_id, moved_at, direction, qty, reason) VALUES\n  "
            + chunk + ";"
        )

    # ---- receipts (procurement の po_rows / delivery_rows を活用) ----
    # delivered/partial の PO 30 件 + pending 15 件 + cancelled 5 件 = 約 50 行
    receipt_rows: list[dict] = []
    rcv_id = 1
    # delivered/partial を 30 件サンプリング
    delivered_pos = [d for d in delivery_rows]
    sampled_delivered = rng.sample(delivered_pos, min(30, len(delivered_pos)))
    for (did, po_id, delivered_at, qty_received, _) in sampled_delivered:
        # po_id から part_id / supplier を取得
        po = next((p for p in po_rows if p[0] == po_id), None)
        if po is None:
            continue
        _, _, part_id_, ordered, qty, _, status = po
        warehouse_id = plant_for_part(part_id_)  # 1=東京/2=大阪 と warehouse_id 1/2 は一致
        expected_at = ordered + timedelta(days=SUPPLIERS[po[1] - 1][3])
        actual_status = "received" if status == "delivered" else "partial"
        receipt_rows.append({
            "id": rcv_id,
            "po_id": po_id,
            "warehouse_id": warehouse_id,
            "part_id": part_id_,
            "expected_at": fmt_dt(expected_at),
            "received_at": fmt_dt(delivered_at),
            "qty_expected": qty,
            "qty_received": qty_received,
            "status": actual_status,
        })
        rcv_id += 1

    # pending: ordered のまま未入荷 → 期日が近い PO から 15 件
    ordered_pos = [p for p in po_rows if p[6] == "ordered"]
    sampled_ordered = rng.sample(ordered_pos, min(15, len(ordered_pos)))
    for po in sampled_ordered:
        po_id, supplier_id, part_id_, ordered, qty, _, _ = po
        warehouse_id = plant_for_part(part_id_)
        expected_at = ordered + timedelta(days=SUPPLIERS[supplier_id - 1][3])
        receipt_rows.append({
            "id": rcv_id,
            "po_id": po_id,
            "warehouse_id": warehouse_id,
            "part_id": part_id_,
            "expected_at": fmt_dt(expected_at),
            "received_at": None,
            "qty_expected": qty,
            "qty_received": 0,
            "status": "pending",
        })
        rcv_id += 1

    # cancelled
    cancelled_pos = [p for p in po_rows if p[6] == "cancelled"]
    sampled_cancelled = rng.sample(cancelled_pos, min(5, len(cancelled_pos)))
    for po in sampled_cancelled:
        po_id, supplier_id, part_id_, ordered, qty, _, _ = po
        warehouse_id = plant_for_part(part_id_)
        expected_at = ordered + timedelta(days=SUPPLIERS[supplier_id - 1][3])
        receipt_rows.append({
            "id": rcv_id,
            "po_id": po_id,
            "warehouse_id": warehouse_id,
            "part_id": part_id_,
            "expected_at": fmt_dt(expected_at),
            "received_at": None,
            "qty_expected": qty,
            "qty_received": 0,
            "status": "cancelled",
        })
        rcv_id += 1

    if receipt_rows:
        stmts.append("-- receipts")
        rec_vals = ",\n  ".join(
            f"({r['id']},{r['po_id']},{r['warehouse_id']},{r['part_id']},"
            f"'{r['expected_at']}+00',"
            + ("NULL" if r["received_at"] is None else f"'{r['received_at']}+00'")
            + f",{r['qty_expected']},{r['qty_received']},'{r['status']}')"
            for r in receipt_rows
        )
        stmts.append(
            "INSERT INTO receipts (id, po_id, warehouse_id, part_id, expected_at, received_at, qty_expected, qty_received, status) VALUES\n  "
            + rec_vals + ";"
        )

    # ---- shipments + shipment_lines ----
    # 30 days × 2 shipments = 60 件、各 shipment は 1-4 行の明細
    carriers = ["ヤマト運輸", "佐川急便", "西濃運輸", "自社便"]
    statuses = ["planned", "picking", "shipped", "shipped", "shipped", "delivered"]
    shipment_records: list[dict] = []
    shipment_line_records: list[dict] = []
    ship_id = 1
    line_id_seq = 1
    for d in range(DAYS):
        for _ in range(2):
            wid = rng.choice([1, 2])
            ship_no = f"SH-202605{d + 1:02d}-{rng.randint(1, 99):03d}"
            carrier = rng.choice(carriers)
            shipped_at = START + timedelta(days=d, hours=rng.randint(9, 18))
            status = rng.choice(statuses)
            tracking = f"TRK{rng.randint(100000, 999999)}" if status in ("shipped", "delivered") else None
            shipment_records.append({
                "id": ship_id,
                "ship_no": ship_no,
                "warehouse_id": wid,
                "carrier": carrier,
                "tracking_no": tracking,
                "shipped_at": fmt_dt(shipped_at) if status in ("shipped", "delivered") else None,
                "status": status,
            })
            # 明細
            n_lines = rng.randint(1, 4)
            for _ in range(n_lines):
                part = rng.choice(PARTS)
                shipment_line_records.append({
                    "id": line_id_seq,
                    "shipment_id": ship_id,
                    "part_id": part[0],
                    "lot_no": f"L-202605-{rng.randint(1, 999):03d}" if rng.random() < 0.4 else None,
                    "qty": rng.randint(5, 50),
                })
                line_id_seq += 1
            ship_id += 1

    stmts.append("-- shipments")
    ship_vals_fixed = []
    for s in shipment_records:
        tracking = "NULL" if s["tracking_no"] is None else f"'{s['tracking_no']}'"
        shipped = "NULL" if s["shipped_at"] is None else f"'{s['shipped_at']}+00'"
        ship_vals_fixed.append(
            f"({s['id']},'{s['ship_no']}',{s['warehouse_id']},'{s['carrier']}',{tracking},{shipped},'{s['status']}')"
        )
    stmts.append(
        "INSERT INTO shipments (id, ship_no, warehouse_id, carrier, tracking_no, shipped_at, status) VALUES\n  "
        + ",\n  ".join(ship_vals_fixed) + ";"
    )

    stmts.append("-- shipment_lines")
    line_vals = []
    for l in shipment_line_records:
        lot = "NULL" if l["lot_no"] is None else f"'{l['lot_no']}'"
        line_vals.append(f"({l['id']},{l['shipment_id']},{l['part_id']},{lot},{l['qty']})")
    stmts.append(
        "INSERT INTO shipment_lines (id, shipment_id, part_id, lot_no, qty) VALUES\n  "
        + ",\n  ".join(line_vals) + ";"
    )

    write_sql(DB_INIT / "wms" / "02-seed.sql", stmts)


# ---------- 5. QMS (Postgres 14) ----------

def gen_qms() -> None:
    stmts: list[str] = []
    rng = random.Random(501)

    # ---- inspection_items (固定 5 種) ----
    inspection_items = [
        (1, "外観", "attribute", None),
        (2, "寸法-外径", "variable", "mm"),
        (3, "寸法-内径", "variable", "mm"),
        (4, "重量", "variable", "g"),
        (5, "電気特性", "variable", "V"),
    ]
    stmts.append("-- inspection_items")
    item_vals = ",\n  ".join(
        f"({i},'{n}','{dt}'," + ("NULL" if uom is None else f"'{uom}'") + ")"
        for (i, n, dt, uom) in inspection_items
    )
    stmts.append(
        "INSERT INTO inspection_items (id, name, data_type, uom) VALUES\n  "
        + item_vals + ";"
    )

    # ---- quality_specs ----
    # 50 部品 × 平均 2 規格、半数は社内規格(customer_code=NULL)、半数は顧客 CUST-A/B 向け
    spec_records: list[dict] = []
    sid = 1
    spec_templates = {
        # spec_name: (lower, target, upper, uom)
        "外径": (9.95, 10.00, 10.05, "mm"),
        "重量": (95.0, 100.0, 105.0, "g"),
        "耐電圧": (10.0, 12.0, 14.0, "V"),
    }
    customer_codes = [None, "CUST-A", "CUST-B"]
    for part in PARTS:
        # 各部品に 2 つの規格(社内+顧客別)を割り当て
        chosen_specs = rng.sample(list(spec_templates.keys()), 2)
        for spec_name in chosen_specs:
            cust = rng.choice(customer_codes)
            lower, target, upper = spec_templates[spec_name][:3]
            uom = spec_templates[spec_name][3]
            # 顧客別はやや厳しく
            if cust is not None:
                lower += (target - lower) * 0.2
                upper -= (upper - target) * 0.2
            spec_records.append({
                "id": sid,
                "part_id": part[0],
                "spec_name": spec_name,
                "customer_code": cust,
                "lower_limit": round(lower, 3),
                "target_value": round(target, 3),
                "upper_limit": round(upper, 3),
                "uom": uom,
                "revision": 1,
                "effective_from": "2026-01-01",
                "effective_to": None,
            })
            sid += 1
    # 20 件に revision=2 の世代変更を追加(古い rev1 の effective_to を埋める)
    rev2_targets = rng.sample(range(1, sid), 20)
    for orig_id in rev2_targets:
        # 元の spec を revision=2 として複製
        orig = spec_records[orig_id - 1]
        orig["effective_to"] = "2026-04-30"
        new_spec = dict(orig)
        new_spec["id"] = sid
        new_spec["revision"] = 2
        new_spec["effective_from"] = "2026-05-01"
        new_spec["effective_to"] = None
        # 規格を 5% タイトに
        new_spec["lower_limit"] = round(orig["lower_limit"] * 1.02, 3)
        new_spec["upper_limit"] = round(orig["upper_limit"] * 0.98, 3)
        spec_records.append(new_spec)
        sid += 1

    stmts.append("-- quality_specs")
    spec_vals = ",\n  ".join(
        f"({s['id']},{s['part_id']},'{s['spec_name']}',"
        + ("NULL" if s["customer_code"] is None else f"'{s['customer_code']}'") + ","
        + f"{s['lower_limit']},{s['target_value']},{s['upper_limit']},'{s['uom']}',"
        + f"{s['revision']},'{s['effective_from']}',"
        + ("NULL" if s["effective_to"] is None else f"'{s['effective_to']}'") + ")"
        for s in spec_records
    )
    stmts.append(
        "INSERT INTO quality_specs (id, part_id, spec_name, customer_code, "
        "lower_limit, target_value, upper_limit, uom, revision, effective_from, effective_to) VALUES\n  "
        + spec_vals + ";"
    )

    # ---- inspections (列追加版で id 明示) ----
    # 各 line の代表部品 = (line_id - 1) % 50 + 1。その部品の有効な spec から spec_id を選ぶ
    specs_by_part: dict[int, list[int]] = {}
    for s in spec_records:
        if s["effective_to"] is None:
            specs_by_part.setdefault(s["part_id"], []).append(s["id"])

    inspections: list[tuple[int, int, datetime, str, int, int, int, str, str, int | None]] = []
    insp_id = 1
    inspectors = ["検査員A", "検査員B", "検査員C", "検査員D"]
    for d in range(DAYS):
        for line_id, _, _ in [(li[0], li[1], li[2]) for li in LINES]:
            ts = START + timedelta(days=d, hours=random.randint(14, 18))
            sample_qty = random.choice([20, 30, 50])
            ng = max(0, int(sample_qty * random.uniform(0, 0.08)))
            ok = sample_qty - ng - random.randint(0, 2)
            ok = max(0, ok)
            lot = f"LOT-{ts.strftime('%Y%m%d')}-L{line_id}"
            # inspection_type: 10% receiving / 70% in_process / 20% final
            r_type = rng.random()
            if r_type < 0.10:
                itype = "receiving"
            elif r_type < 0.80:
                itype = "in_process"
            else:
                itype = "final"
            # spec_id: ライン代表部品の有効 spec から
            rep_part_id = ((line_id - 1) * 8) % 50 + 1
            spec_pool = specs_by_part.get(rep_part_id, [])
            spec_id = rng.choice(spec_pool) if spec_pool else None
            inspections.append((insp_id, line_id, ts, lot, sample_qty, ok, ng,
                                random.choice(inspectors), itype, spec_id))
            insp_id += 1

    stmts.append("-- inspections")
    insp_vals = ",\n  ".join(
        f"({i},{lid},'{fmt_dt(ts)}+00','{lot}',{s},{ok},{ng},'{insp}','{itype}',"
        + ("NULL" if spec_id is None else str(spec_id)) + ")"
        for (i, lid, ts, lot, s, ok, ng, insp, itype, spec_id) in inspections
    )
    stmts.append(
        "INSERT INTO inspections (id, line_id, inspected_at, lot_no, sample_qty, ok_qty, ng_qty, inspector, inspection_type, spec_id) VALUES\n  "
        + insp_vals + ";"
    )
    # SERIAL シーケンスを最大 id 以降に進める
    stmts.append(f"SELECT setval('inspections_id_seq', {insp_id - 1}, true);")

    defects: list[tuple[int, int, int, str, str]] = []
    def_id = 1
    defect_types = ["寸法不良", "表面キズ", "溶接割れ", "色相違", "組立不良"]
    severities = ["low", "medium", "high"]
    for insp in inspections:
        ng_qty = insp[6]
        for _ in range(ng_qty):
            part = random.choice(PARTS)
            defects.append((def_id, insp[0], part[0], random.choice(defect_types), random.choices(severities, weights=[60, 30, 10])[0]))
            def_id += 1

    stmts.append("-- defect_records")
    if defects:
        vals = ",\n  ".join(
            f"({insp_id_},{pid_},'{dt_}','{sev_}')"
            for (_, insp_id_, pid_, dt_, sev_) in defects
        )
        stmts.append(f"INSERT INTO defect_records (inspection_id, part_id, defect_type, severity) VALUES\n  {vals};")

    # corrective_actions: action_type / effectiveness を埋める
    actions: list[dict] = []
    act_id = 1
    action_texts = [
        "治具を交換しロットを再検査",
        "設計部門へECRを発行",
        "溶接機のパラメータを調整",
        "オペレーターを再教育",
        "不良品をサプライヤーへ返却",
    ]
    statuses = ["open", "in_progress", "closed"]
    action_types = ["containment", "corrective", "corrective", "corrective", "preventive"]
    for d in defects:
        if d[4] in ("medium", "high") or random.random() < 0.3:
            ts = START + timedelta(days=random.randint(0, DAYS - 1), hours=random.randint(9, 17))
            status = random.choices(statuses, weights=[30, 30, 40])[0]
            atype = random.choice(action_types)
            if status == "closed":
                # 70% effective / 20% ineffective / 10% not_evaluated
                er = random.random()
                if er < 0.70:
                    effectiveness = "effective"
                elif er < 0.90:
                    effectiveness = "ineffective"
                else:
                    effectiveness = "not_evaluated"
            else:
                effectiveness = "not_evaluated"
            actions.append({
                "id": act_id,
                "defect_id": d[0],
                "action": random.choice(action_texts),
                "taken_at": fmt_dt(ts),
                "status": status,
                "action_type": atype,
                "effectiveness": effectiveness,
            })
            act_id += 1

    stmts.append("-- corrective_actions")
    if actions:
        ca_vals = ",\n  ".join(
            f"({a['defect_id']},'{a['action']}','{a['taken_at']}+00','{a['status']}',"
            f"'{a['action_type']}','{a['effectiveness']}')"
            for a in actions
        )
        stmts.append(
            "INSERT INTO corrective_actions (defect_id, action, taken_at, status, action_type, effectiveness) VALUES\n  "
            + ca_vals + ";"
        )

    # ---- inspection_results ----
    # 各 inspection について平均 3 項目を判定。measured_value は spec から導出
    results: list[dict] = []
    res_id = 1
    spec_by_id = {s["id"]: s for s in spec_records}
    for insp in inspections:
        insp_id_, line_id, ts, lot, sample_qty, ok, ng, _, _, spec_id = insp
        # 検査する項目は 2-4 ランダム
        n_items = rng.randint(2, 4)
        chosen_items = rng.sample(range(1, 6), n_items)
        # ng が出ているなら 1 項目は ng 判定にする
        ng_assigned = (ng == 0)
        for item_id in chosen_items:
            # measured_value: spec が紐付いていれば lower/upper の間で、なければ NULL
            measured = None
            judgement = "ok"
            if spec_id is not None and item_id in (2, 3, 4):
                spec = spec_by_id[spec_id]
                lower, upper = spec["lower_limit"], spec["upper_limit"]
                target = spec["target_value"]
                if not ng_assigned and rng.random() < 0.5:
                    # 範囲外の値で ng
                    if rng.random() < 0.5:
                        measured = round(lower - rng.uniform(0.001, 0.05), 3)
                    else:
                        measured = round(upper + rng.uniform(0.001, 0.05), 3)
                    judgement = "ng"
                    ng_assigned = True
                else:
                    measured = round(target + rng.uniform(-0.5, 0.5) * (upper - lower) / 4, 3)
            else:
                # attribute(外観/電気特性): NG が残っていれば1件 ng
                if not ng_assigned and rng.random() < 0.3:
                    judgement = "ng"
                    ng_assigned = True
            results.append({
                "id": res_id,
                "inspection_id": insp_id_,
                "item_id": item_id,
                "measured_value": measured,
                "judgement": judgement,
            })
            res_id += 1

    stmts.append("-- inspection_results")
    res_vals = ",\n  ".join(
        f"({r['id']},{r['inspection_id']},{r['item_id']},"
        + ("NULL" if r["measured_value"] is None else str(r["measured_value"])) + ","
        + f"'{r['judgement']}')"
        for r in results
    )
    batch_q = 500
    for i in range(0, len(results), batch_q):
        chunk_rs = results[i:i + batch_q]
        chunk_vals = ",\n  ".join(
            f"({r['id']},{r['inspection_id']},{r['item_id']},"
            + ("NULL" if r["measured_value"] is None else str(r["measured_value"])) + ","
            + f"'{r['judgement']}')"
            for r in chunk_rs
        )
        stmts.append(
            "INSERT INTO inspection_results (id, inspection_id, item_id, measured_value, judgement) VALUES\n  "
            + chunk_vals + ";"
        )

    # ---- four_m_changes (2 factory × 30 day × 0.5 件 ≒ 30 件) ----
    four_m_records: list[dict] = []
    fm_id = 1
    fm_descs = {
        "man": ["シフト交代", "新人オペレーター投入", "年休による応援人員投入"],
        "machine": ["金型交換", "定期点検実施", "突発故障による予備機切替"],
        "material": ["材料ロット切替", "サプライヤー変更", "代替材適用"],
        "method": ["作業手順書 v2 適用", "サイクルタイム短縮", "検査頻度変更"],
    }
    fm_authors = ["東京設計者", "大阪設計者", "管理者", "東京購買A", "大阪購買A"]
    for d in range(DAYS):
        for factory_id in (1, 2):
            if rng.random() < 0.50:
                continue
            occurred = START + timedelta(days=d, hours=rng.randint(6, 18))
            ctype = rng.choice(list(fm_descs.keys()))
            desc = rng.choice(fm_descs[ctype])
            line_id = rng.choice([li[0] for li in LINES if li[1] == factory_id])
            four_m_records.append({
                "id": fm_id,
                "factory_id": factory_id,
                "line_id": line_id,
                "occurred_at": fmt_dt(occurred),
                "change_type": ctype,
                "description": desc,
                "is_planned": "TRUE" if rng.random() < 0.75 else "FALSE",
                "changed_by": rng.choice(fm_authors),
            })
            fm_id += 1
    if four_m_records:
        stmts.append("-- four_m_changes")
        fm_vals = ",\n  ".join(
            f"({f['id']},{f['factory_id']},{f['line_id']},'{f['occurred_at']}+00',"
            f"'{f['change_type']}','{f['description']}',{f['is_planned']},'{f['changed_by']}')"
            for f in four_m_records
        )
        stmts.append(
            "INSERT INTO four_m_changes (id, factory_id, line_id, occurred_at, change_type, description, is_planned, changed_by) VALUES\n  "
            + fm_vals + ";"
        )

    write_sql(DB_INIT / "qms" / "02-seed.sql", stmts)


def main() -> None:
    gen_ebom()
    procurement_data = gen_procurement()
    gen_scada()
    gen_wms(po_rows=procurement_data["po_rows"], delivery_rows=procurement_data["delivery_rows"])
    gen_qms()
    print("done")


if __name__ == "__main__":
    main()
