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

FACTORIES = [(1, "Tokyo", "east"), (2, "Osaka", "west")]
LINES = [
    (1, 1, "Line-1"), (2, 1, "Line-2"), (3, 1, "Line-3"),
    (4, 2, "Line-1"), (5, 2, "Line-2"), (6, 2, "Line-3"),
]
EQUIPMENT_TYPES = ["press", "weld", "assembly", "inspect"]
EQUIPMENT: list[tuple[int, int, str, str]] = []
for li in LINES:
    line_id = li[0]
    for i, t in enumerate(EQUIPMENT_TYPES):
        eq_id = (line_id - 1) * 4 + i + 1
        EQUIPMENT.append((eq_id, line_id, f"EQ-{line_id:02d}-{t[:3].upper()}", t))

SUPPLIERS = [
    (1, "Tokyo Steel Co.", "Japan", 3, "sales@tokyosteel.example.jp"),
    (2, "Osaka Bearings", "Japan", 5, "info@osakabearings.example.jp"),
    (3, "Shenzhen Electronics", "China", 14, "trade@sze.example.cn"),
    (4, "Bavaria Precision", "Germany", 21, "hello@bavpre.example.de"),
    (5, "Detroit Castings", "USA", 28, "sales@detcast.example.com"),
    (6, "Hanoi Plastics", "Vietnam", 18, "ops@hanoiplast.example.vn"),
    (7, "Pune Components", "India", 25, "biz@punecomp.example.in"),
    (8, "Seoul Sensors", "Korea", 10, "global@seoulsensors.example.kr"),
    (9, "Taipei Wire", "Taiwan", 12, "info@taipeiwire.example.tw"),
    (10, "Mexico Tooling", "Mexico", 20, "ventas@mxtool.example.mx"),
]

PRODUCTS = [
    (1, "PROD-A", "Compact EV Motor", "assembly"),
    (2, "PROD-B", "Industrial Robot Arm", "assembly"),
    (3, "PROD-C", "Smart Inverter Unit", "module"),
]

# 部品 50 個
PART_KINDS = [
    ("bolt", "Bolt"), ("nut", "Nut"), ("shaft", "Shaft"), ("bearing", "Bearing"),
    ("plate", "Plate"), ("frame", "Frame"), ("cover", "Cover"), ("gear", "Gear"),
    ("coil", "Coil"), ("magnet", "Magnet"),
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


# ---------- 1. E-BOM (MySQL 8.0) ----------

def gen_ebom() -> None:
    stmts: list[str] = []

    stmts.append("-- products")
    vals = ",\n  ".join(f"({i},'{c}','{n}','{cat}')" for (i, c, n, cat) in PRODUCTS)
    stmts.append(f"INSERT INTO products (id, code, name, category) VALUES\n  {vals};")

    stmts.append("-- parts")
    vals = ",\n  ".join(
        f"({i},'{c}','{n}',{sup},{cost},{prod})"
        for (i, c, n, sup, cost, prod) in PARTS
    )
    stmts.append(f"INSERT INTO parts (id, code, name, supplier_id, unit_cost, product_id) VALUES\n  {vals};")

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

    ec_rows: list[tuple[int, int, str, str, str]] = []
    reasons = ["Material change", "Tolerance adjustment", "Cost reduction", "Supplier switch", "Quality improvement"]
    authors = ["tokyo_designer", "osaka_designer", "admin"]
    for i in range(1, 31):
        part = random.choice(PARTS)
        offset_days = random.randint(0, DAYS - 1)
        when = START + timedelta(days=offset_days, hours=random.randint(8, 17))
        ec_rows.append((i, part[0], fmt_dt(when), random.choice(reasons), random.choice(authors)))
    stmts.append("-- engineering_changes")
    vals = ",\n  ".join(f"({i},{p},'{t}','{r}','{a}')" for (i, p, t, r, a) in ec_rows)
    stmts.append(f"INSERT INTO engineering_changes (id, part_id, changed_at, reason, changed_by) VALUES\n  {vals};")

    write_sql(DB_INIT / "ebom" / "02-seed.sql", stmts)


# ---------- 2. 購買・調達 (MySQL 5.7) ----------

def gen_procurement() -> list[tuple[int, int, int, datetime, int, float, str]]:
    stmts: list[str] = []
    stmts.append("-- suppliers")
    vals = ",\n  ".join(f"({i},'{n}','{c}',{lt},'{e}')" for (i, n, c, lt, e) in SUPPLIERS)
    stmts.append(f"INSERT INTO suppliers (id, name, country, lead_time_days, contact_email) VALUES\n  {vals};")

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

    stmts.append("-- purchase_orders")
    vals = ",\n  ".join(
        f"({i},{s},{p},'{fmt_dt(o)}',{q},{up},'{st}')"
        for (i, s, p, o, q, up, st) in po_rows
    )
    stmts.append(f"INSERT INTO purchase_orders (id, supplier_id, part_id, ordered_at, qty, unit_price, status) VALUES\n  {vals};")

    delivery_rows: list[tuple[int, int, str, int, int]] = []
    did = 1
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
            delivery_rows.append((did, po_id, fmt_dt(delivered_at), received, rejected))
            did += 1

    stmts.append("-- deliveries")
    vals = ",\n  ".join(
        f"({i},{p},'{d}',{r},{rej})"
        for (i, p, d, r, rej) in delivery_rows
    )
    stmts.append(f"INSERT INTO deliveries (id, po_id, delivered_at, qty_received, qty_rejected) VALUES\n  {vals};")

    write_sql(DB_INIT / "procurement" / "02-seed.sql", stmts)
    return po_rows


# ---------- 3. SCADA (Postgres 16) ----------

def gen_scada() -> list[tuple[int, int, int, datetime, str, int, int]]:
    stmts: list[str] = []

    stmts.append("-- factories")
    vals = ",\n  ".join(f"({i},'{n}','{r}')" for (i, n, r) in FACTORIES)
    stmts.append(f"INSERT INTO factories (id, name, region) VALUES\n  {vals};")

    stmts.append("-- lines")
    vals = ",\n  ".join(f"({i},{f},'{n}')" for (i, f, n) in LINES)
    stmts.append(f"INSERT INTO lines (id, factory_id, name) VALUES\n  {vals};")

    stmts.append("-- equipment")
    vals = ",\n  ".join(f"({i},{lid},'{n}','{t}')" for (i, lid, n, t) in EQUIPMENT)
    stmts.append(f"INSERT INTO equipment (id, line_id, name, type) VALUES\n  {vals};")

    # sensor_readings: 24 設備 × 24h × 30日 = 17,280 行。バッチに分けて INSERT
    sensor_rows: list[str] = []
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
                sensor_rows.append(
                    f"({eq_id},'{fmt_dt(ts)}+00',{temp},{pressure},{vibration},{runtime})"
                )

    stmts.append("-- sensor_readings")
    batch = 500
    for i in range(0, len(sensor_rows), batch):
        chunk = ",\n  ".join(sensor_rows[i:i + batch])
        stmts.append(
            "INSERT INTO sensor_readings (equipment_id, recorded_at, temperature, pressure, vibration, runtime_minutes) VALUES\n  "
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

    write_sql(DB_INIT / "scada" / "02-seed.sql", stmts)
    return prod_rows


# ---------- 4. WMS (Postgres 13) ----------

def gen_wms() -> None:
    stmts: list[str] = []

    warehouses = [(1, 1, "Tokyo-WH"), (2, 2, "Osaka-WH")]
    stmts.append("-- warehouses")
    vals = ",\n  ".join(f"({i},{f},'{n}')" for (i, f, n) in warehouses)
    stmts.append(f"INSERT INTO warehouses (id, factory_id, name) VALUES\n  {vals};")

    locations: list[tuple[int, int, str, str]] = []
    lid = 1
    for w in warehouses:
        for zone in ("A", "B", "C"):
            for shelf_n in range(1, 4):
                locations.append((lid, w[0], zone, f"S{shelf_n:02d}"))
                lid += 1

    stmts.append("-- locations")
    vals = ",\n  ".join(f"({i},{w},'{z}','{s}')" for (i, w, z, s) in locations)
    stmts.append(f"INSERT INTO locations (id, warehouse_id, zone, shelf) VALUES\n  {vals};")

    inventory_rows: list[tuple[int, int, int, str]] = []
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
            inventory_rows.append((inv_id, part[0], loc[0], qty, fmt_dt(ts)))
            inv_id += 1

    stmts.append("-- inventory")
    vals = ",\n  ".join(
        f"({i},{p},{l},{q},'{u}+00')"
        for (i, p, l, q, u) in [(r[0], r[1], r[2], r[3], r[4]) for r in inventory_rows]
    )
    stmts.append(f"INSERT INTO inventory (id, part_id, location_id, qty, updated_at) VALUES\n  {vals};")

    move_rows: list[tuple[int, int, str, str, int, str]] = []
    mid = 1
    reasons_in = ["delivery", "return", "transfer_in"]
    reasons_out = ["production", "scrap", "transfer_out"]
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
    vals_list = [
        f"({p},'{ts}+00','{d}',{q},'{r}')"
        for (_, p, ts, d, q, r) in move_rows
    ]
    # location_id を別途差し込む
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

    write_sql(DB_INIT / "wms" / "02-seed.sql", stmts)


# ---------- 5. QMS (Postgres 14) ----------

def gen_qms() -> None:
    stmts: list[str] = []

    inspections: list[tuple[int, int, datetime, str, int, int, int, str]] = []
    insp_id = 1
    inspectors = ["inspector_a", "inspector_b", "inspector_c", "inspector_d"]
    for d in range(DAYS):
        for line_id, _, _ in [(li[0], li[1], li[2]) for li in LINES]:
            ts = START + timedelta(days=d, hours=random.randint(14, 18))
            sample_qty = random.choice([20, 30, 50])
            ng = max(0, int(sample_qty * random.uniform(0, 0.08)))
            ok = sample_qty - ng - random.randint(0, 2)
            ok = max(0, ok)
            lot = f"LOT-{ts.strftime('%Y%m%d')}-L{line_id}"
            inspections.append((insp_id, line_id, ts, lot, sample_qty, ok, ng, random.choice(inspectors)))
            insp_id += 1

    stmts.append("-- inspections")
    vals = ",\n  ".join(
        f"({lid},'{fmt_dt(ts)}+00','{lot}',{s},{ok},{ng},'{insp}')"
        for (_, lid, ts, lot, s, ok, ng, insp) in inspections
    )
    stmts.append(f"INSERT INTO inspections (line_id, inspected_at, lot_no, sample_qty, ok_qty, ng_qty, inspector) VALUES\n  {vals};")

    defects: list[tuple[int, int, int, str, str]] = []
    def_id = 1
    defect_types = ["dimension", "surface_scratch", "weld_crack", "color_mismatch", "assembly_error"]
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

    actions: list[tuple[int, int, str, str, str]] = []
    act_id = 1
    action_texts = [
        "Replaced jig and re-inspected the lot",
        "Issued ECR to design team",
        "Adjusted welder parameters",
        "Re-trained operator",
        "Returned defective parts to supplier",
    ]
    statuses = ["open", "in_progress", "closed"]
    for d in defects:
        if d[4] in ("medium", "high") or random.random() < 0.3:
            ts = START + timedelta(days=random.randint(0, DAYS - 1), hours=random.randint(9, 17))
            actions.append((act_id, d[0], random.choice(action_texts), fmt_dt(ts), random.choices(statuses, weights=[30, 30, 40])[0]))
            act_id += 1

    stmts.append("-- corrective_actions")
    if actions:
        vals = ",\n  ".join(
            f"({did_},'{act_}','{ts_}+00','{st_}')"
            for (_, did_, act_, ts_, st_) in actions
        )
        stmts.append(f"INSERT INTO corrective_actions (defect_id, action, taken_at, status) VALUES\n  {vals};")

    write_sql(DB_INIT / "qms" / "02-seed.sql", stmts)


def main() -> None:
    gen_ebom()
    gen_procurement()
    gen_scada()
    gen_wms()
    gen_qms()
    print("done")


if __name__ == "__main__":
    main()
