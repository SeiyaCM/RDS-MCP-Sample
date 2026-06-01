SET NAMES utf8mb4;

CREATE TABLE suppliers (
  id INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL,
  country VARCHAR(64) NOT NULL,
  lead_time_days INT NOT NULL,
  contact_email VARCHAR(128) NOT NULL,
  payment_terms VARCHAR(16) NOT NULL DEFAULT 'NET30',
  otd_target_pct DECIMAL(5,2) NOT NULL DEFAULT 95.00,
  currency CHAR(3) NOT NULL DEFAULT 'JPY',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_suppliers_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 購買依頼。現場部門からの調達要求。承認後に purchase_orders へ converted される。
CREATE TABLE purchase_requisitions (
  id INT NOT NULL AUTO_INCREMENT,
  requisition_no VARCHAR(16) NOT NULL,
  plant_id INT NOT NULL,
  part_id INT NOT NULL,
  qty INT NOT NULL,
  requested_by VARCHAR(64) NOT NULL,
  requested_at DATETIME NOT NULL,
  needed_by DATE NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'approved',
  PRIMARY KEY (id),
  UNIQUE KEY uq_req_no (requisition_no),
  KEY ix_req_plant_status (plant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE purchase_orders (
  id INT NOT NULL AUTO_INCREMENT,
  supplier_id INT NOT NULL,
  part_id INT NOT NULL,
  ordered_at DATETIME NOT NULL,
  qty INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  status VARCHAR(16) NOT NULL,
  plant_id INT NOT NULL DEFAULT 1,
  requisition_id INT NULL,
  expected_delivery_date DATE NULL,
  total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY ix_po_supplier (supplier_id),
  KEY ix_po_ordered (ordered_at),
  KEY ix_po_plant_status (plant_id, status),
  CONSTRAINT fk_po_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
  CONSTRAINT fk_po_req FOREIGN KEY (requisition_id) REFERENCES purchase_requisitions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE deliveries (
  id INT NOT NULL AUTO_INCREMENT,
  po_id INT NOT NULL,
  delivered_at DATETIME NOT NULL,
  qty_received INT NOT NULL,
  qty_rejected INT NOT NULL,
  receipt_no VARCHAR(16) NOT NULL DEFAULT '',
  received_by VARCHAR(64) NOT NULL DEFAULT '',
  PRIMARY KEY (id),
  KEY ix_deliveries_po (po_id),
  CONSTRAINT fk_deliveries_po FOREIGN KEY (po_id) REFERENCES purchase_orders(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- サプライヤー別の購入条件(セカンダリソース対応)。
-- 設計上の互換は ebom.alternate_parts、ここは「どのサプライヤーから幾らで何日で買えるか」。
-- part_id は ebom_db.parts.id への論理参照(物理 FK は不可)。
CREATE TABLE supplier_part_catalog (
  id INT NOT NULL AUTO_INCREMENT,
  supplier_id INT NOT NULL,
  part_id INT NOT NULL,
  supplier_part_no VARCHAR(64) NOT NULL,
  lead_time_days INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  moq INT NOT NULL DEFAULT 1,
  is_primary TINYINT(1) NOT NULL DEFAULT 0,
  valid_from DATE NOT NULL,
  valid_to DATE NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_spc (supplier_id, part_id, valid_from),
  KEY ix_spc_part_primary (part_id, is_primary),
  CONSTRAINT fk_spc_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 請求書(3-Way Match の 3 点目)。 PO・Delivery と突合し、不一致を match_status で表現。
CREATE TABLE invoices (
  id INT NOT NULL AUTO_INCREMENT,
  invoice_no VARCHAR(32) NOT NULL,
  supplier_id INT NOT NULL,
  po_id INT NOT NULL,
  delivery_id INT NULL,
  invoice_date DATE NOT NULL,
  due_date DATE NOT NULL,
  qty_billed INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'JPY',
  match_status VARCHAR(16) NOT NULL DEFAULT 'matched',
  paid_at DATE NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_inv_no (invoice_no),
  KEY ix_inv_po (po_id),
  KEY ix_inv_status (match_status),
  CONSTRAINT fk_inv_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
  CONSTRAINT fk_inv_po FOREIGN KEY (po_id) REFERENCES purchase_orders(id),
  CONSTRAINT fk_inv_delivery FOREIGN KEY (delivery_id) REFERENCES deliveries(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
