SET NAMES utf8mb4;

CREATE TABLE suppliers (
  id INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL,
  country VARCHAR(64) NOT NULL,
  lead_time_days INT NOT NULL,
  contact_email VARCHAR(128) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_suppliers_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE purchase_orders (
  id INT NOT NULL AUTO_INCREMENT,
  supplier_id INT NOT NULL,
  part_id INT NOT NULL,
  ordered_at DATETIME NOT NULL,
  qty INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  status VARCHAR(16) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_po_supplier (supplier_id),
  KEY ix_po_ordered (ordered_at),
  CONSTRAINT fk_po_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE deliveries (
  id INT NOT NULL AUTO_INCREMENT,
  po_id INT NOT NULL,
  delivered_at DATETIME NOT NULL,
  qty_received INT NOT NULL,
  qty_rejected INT NOT NULL,
  PRIMARY KEY (id),
  KEY ix_deliveries_po (po_id),
  CONSTRAINT fk_deliveries_po FOREIGN KEY (po_id) REFERENCES purchase_orders(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
