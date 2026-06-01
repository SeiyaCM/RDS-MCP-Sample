CREATE TABLE warehouses (
  id INT PRIMARY KEY,
  factory_id INT NOT NULL,
  name VARCHAR(64) NOT NULL,
  UNIQUE (factory_id, name)
);

CREATE TABLE locations (
  id INT PRIMARY KEY,
  warehouse_id INT NOT NULL REFERENCES warehouses(id),
  zone VARCHAR(8) NOT NULL CHECK (zone IN ('A','B','C')),
  shelf VARCHAR(8) NOT NULL,
  aisle VARCHAR(8) NOT NULL DEFAULT '01',
  rack VARCHAR(8) NOT NULL DEFAULT 'R1',
  bin VARCHAR(8) NOT NULL DEFAULT 'B1',
  capacity_cubic_feet NUMERIC(8,2) NOT NULL DEFAULT 50.00,
  UNIQUE (warehouse_id, zone, shelf)
);

CREATE TABLE inventory (
  id SERIAL PRIMARY KEY,
  part_id INT NOT NULL,
  location_id INT NOT NULL REFERENCES locations(id),
  qty INT NOT NULL CHECK (qty >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  lot_no VARCHAR(32),
  expiry_date DATE,
  status VARCHAR(16) NOT NULL DEFAULT 'available'
          CHECK (status IN ('available','allocated','shipped','quarantined')),
  UNIQUE (part_id, location_id)
);

CREATE TABLE stock_movements (
  id BIGSERIAL PRIMARY KEY,
  part_id INT NOT NULL,
  location_id INT NOT NULL REFERENCES locations(id),
  moved_at TIMESTAMPTZ NOT NULL,
  direction VARCHAR(8) NOT NULL CHECK (direction IN ('in','out')),
  qty INT NOT NULL CHECK (qty > 0),
  reason VARCHAR(64) NOT NULL
);
CREATE INDEX ix_moves_part_time ON stock_movements (part_id, moved_at);
COMMENT ON COLUMN stock_movements.reason IS '納品/返品/他拠点入庫/生産投入/廃棄/他拠点出庫/引当/引当キャンセル/出荷確定 など';

-- 入荷予定(ASN)。procurement.purchase_orders.id への論理参照を po_id で保持。
CREATE TABLE receipts (
  id SERIAL PRIMARY KEY,
  po_id INT NOT NULL,
  warehouse_id INT NOT NULL REFERENCES warehouses(id),
  part_id INT NOT NULL,
  expected_at TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ,
  qty_expected INT NOT NULL CHECK (qty_expected > 0),
  qty_received INT NOT NULL DEFAULT 0,
  status VARCHAR(16) NOT NULL DEFAULT 'pending'
          CHECK (status IN ('pending','partial','received','cancelled'))
);
CREATE INDEX ix_receipts_po ON receipts (po_id);

-- 出荷ヘッダ
CREATE TABLE shipments (
  id SERIAL PRIMARY KEY,
  ship_no VARCHAR(32) NOT NULL UNIQUE,
  warehouse_id INT NOT NULL REFERENCES warehouses(id),
  carrier VARCHAR(32) NOT NULL,
  tracking_no VARCHAR(64),
  shipped_at TIMESTAMPTZ,
  status VARCHAR(16) NOT NULL DEFAULT 'planned'
          CHECK (status IN ('planned','picking','shipped','delivered','cancelled'))
);

-- 出荷明細
CREATE TABLE shipment_lines (
  id BIGSERIAL PRIMARY KEY,
  shipment_id INT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  part_id INT NOT NULL,
  lot_no VARCHAR(32),
  qty INT NOT NULL CHECK (qty > 0)
);
CREATE INDEX ix_shiplines_sh ON shipment_lines (shipment_id);
