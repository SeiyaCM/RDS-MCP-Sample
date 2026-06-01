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
  uom VARCHAR(8) NOT NULL DEFAULT 'pcs',
  material VARCHAR(64) NULL,
  current_revision CHAR(1) NOT NULL DEFAULT 'A',
  lifecycle_status VARCHAR(16) NOT NULL DEFAULT 'active',
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
  eco_no VARCHAR(16) NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL DEFAULT 'applied',
  effective_date DATE NULL,
  new_revision CHAR(1) NULL,
  PRIMARY KEY (id),
  KEY ix_ec_part (part_id),
  KEY ix_ec_status_eff (status, effective_date),
  CONSTRAINT fk_ec_part FOREIGN KEY (part_id) REFERENCES parts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 部品のリビジョン履歴。常に最新版が parts.current_revision と一致し、
-- 過去 Rev は effective_to で期間管理する。
CREATE TABLE part_revisions (
  id INT NOT NULL AUTO_INCREMENT,
  part_id INT NOT NULL,
  revision CHAR(1) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  change_reason VARCHAR(255) NULL,
  released_by VARCHAR(64) NOT NULL,
  released_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_part_rev (part_id, revision),
  KEY ix_part_rev_current (part_id, effective_to),
  CONSTRAINT fk_part_rev_part FOREIGN KEY (part_id) REFERENCES parts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 代替品(セカンダリソース)。設計上の互換性を表現する。
-- 購買条件は procurement.supplier_part_catalog 側で管理する(責任分界)。
CREATE TABLE alternate_parts (
  id INT NOT NULL AUTO_INCREMENT,
  primary_part_id INT NOT NULL,
  alternate_part_id INT NOT NULL,
  compatibility VARCHAR(16) NOT NULL DEFAULT 'full',
  note VARCHAR(255) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_alt (primary_part_id, alternate_part_id),
  CONSTRAINT chk_alt_diff CHECK (primary_part_id <> alternate_part_id),
  CONSTRAINT fk_alt_primary FOREIGN KEY (primary_part_id) REFERENCES parts(id),
  CONSTRAINT fk_alt_alt FOREIGN KEY (alternate_part_id) REFERENCES parts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ECO と影響部品の多対多。engineering_changes.part_id が主たる対象、
-- 同時に変更される他部品はここで展開する。
CREATE TABLE eco_part_links (
  eco_id INT NOT NULL,
  part_id INT NOT NULL,
  impact VARCHAR(16) NOT NULL DEFAULT 'changed',
  PRIMARY KEY (eco_id, part_id),
  CONSTRAINT fk_ecopl_eco FOREIGN KEY (eco_id) REFERENCES engineering_changes(id),
  CONSTRAINT fk_ecopl_part FOREIGN KEY (part_id) REFERENCES parts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
