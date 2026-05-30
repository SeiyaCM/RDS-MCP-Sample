SET NAMES utf8mb4;

CREATE TABLE products (
  id INT NOT NULL AUTO_INCREMENT,
  code VARCHAR(32) NOT NULL,
  name VARCHAR(128) NOT NULL,
  category VARCHAR(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_products_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE parts (
  id INT NOT NULL AUTO_INCREMENT,
  code VARCHAR(32) NOT NULL,
  name VARCHAR(128) NOT NULL,
  supplier_id INT NOT NULL,
  unit_cost DECIMAL(10,2) NOT NULL,
  product_id INT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_parts_code (code),
  KEY ix_parts_supplier (supplier_id),
  CONSTRAINT fk_parts_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE bom (
  id INT NOT NULL AUTO_INCREMENT,
  parent_part_id INT NOT NULL,
  child_part_id INT NOT NULL,
  qty INT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_bom_parent_child (parent_part_id, child_part_id),
  CONSTRAINT fk_bom_parent FOREIGN KEY (parent_part_id) REFERENCES parts(id),
  CONSTRAINT fk_bom_child FOREIGN KEY (child_part_id) REFERENCES parts(id),
  CONSTRAINT chk_bom_diff CHECK (parent_part_id <> child_part_id),
  CONSTRAINT chk_bom_qty CHECK (qty >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE engineering_changes (
  id INT NOT NULL AUTO_INCREMENT,
  part_id INT NOT NULL,
  changed_at DATETIME NOT NULL,
  reason VARCHAR(255) NOT NULL,
  changed_by VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_ec_part (part_id),
  CONSTRAINT fk_ec_part FOREIGN KEY (part_id) REFERENCES parts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
