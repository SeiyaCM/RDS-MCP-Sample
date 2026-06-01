CREATE TABLE inspections (
  id SERIAL PRIMARY KEY,
  line_id INT NOT NULL,
  inspected_at TIMESTAMPTZ NOT NULL,
  lot_no VARCHAR(32) NOT NULL,
  sample_qty INT NOT NULL,
  ok_qty INT NOT NULL,
  ng_qty INT NOT NULL,
  inspector VARCHAR(64) NOT NULL,
  inspection_type VARCHAR(16) NOT NULL DEFAULT 'in_process'
                  CHECK (inspection_type IN ('receiving','in_process','final')),
  spec_id INT,
  CHECK (ok_qty + ng_qty <= sample_qty)
);
CREATE INDEX ix_inspections_line_time ON inspections (line_id, inspected_at);

CREATE TABLE defect_records (
  id SERIAL PRIMARY KEY,
  inspection_id INT NOT NULL REFERENCES inspections(id),
  part_id INT NOT NULL,
  defect_type VARCHAR(64) NOT NULL,
  severity VARCHAR(8) NOT NULL CHECK (severity IN ('low','medium','high'))
);

CREATE TABLE corrective_actions (
  id SERIAL PRIMARY KEY,
  defect_id INT NOT NULL REFERENCES defect_records(id),
  action TEXT NOT NULL,
  taken_at TIMESTAMPTZ NOT NULL,
  status VARCHAR(16) NOT NULL CHECK (status IN ('open','in_progress','closed')),
  action_type VARCHAR(16) NOT NULL DEFAULT 'corrective'
              CHECK (action_type IN ('containment','corrective','preventive')),
  effectiveness VARCHAR(16) DEFAULT 'not_evaluated'
                CHECK (effectiveness IN ('not_evaluated','effective','ineffective'))
);

-- 品質規格マスタ。世代管理(revision)と顧客別納入規格(customer_code IS NOT NULL)に対応。
CREATE TABLE quality_specs (
  id SERIAL PRIMARY KEY,
  part_id INT NOT NULL,
  spec_name VARCHAR(64) NOT NULL,
  customer_code VARCHAR(32),
  lower_limit NUMERIC(10,3),
  target_value NUMERIC(10,3),
  upper_limit NUMERIC(10,3),
  uom VARCHAR(16) NOT NULL,
  revision INT NOT NULL DEFAULT 1,
  effective_from DATE NOT NULL,
  effective_to DATE,
  UNIQUE (part_id, spec_name, customer_code, revision)
);

-- 検査項目マスタ
CREATE TABLE inspection_items (
  id SERIAL PRIMARY KEY,
  name VARCHAR(64) NOT NULL UNIQUE,
  data_type VARCHAR(16) NOT NULL CHECK (data_type IN ('variable','attribute')),
  uom VARCHAR(16)
);

-- 検査結果(inspection × item の多対多)。判定値を保持して SPC 分析に使う。
CREATE TABLE inspection_results (
  id BIGSERIAL PRIMARY KEY,
  inspection_id INT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
  item_id INT NOT NULL REFERENCES inspection_items(id),
  measured_value NUMERIC(10,3),
  judgement VARCHAR(8) NOT NULL CHECK (judgement IN ('ok','ng')),
  UNIQUE (inspection_id, item_id)
);

-- 4M 変更履歴(Man / Machine / Material / Method)
CREATE TABLE four_m_changes (
  id SERIAL PRIMARY KEY,
  factory_id INT NOT NULL,
  line_id INT,
  occurred_at TIMESTAMPTZ NOT NULL,
  change_type VARCHAR(8) NOT NULL CHECK (change_type IN ('man','machine','material','method')),
  description TEXT NOT NULL,
  is_planned BOOLEAN NOT NULL DEFAULT TRUE,
  changed_by VARCHAR(64) NOT NULL
);
CREATE INDEX ix_4m_factory_time ON four_m_changes (factory_id, occurred_at);

-- inspections.spec_id への FK(後付け、quality_specs 作成後)
ALTER TABLE inspections
  ADD CONSTRAINT fk_inspections_spec FOREIGN KEY (spec_id) REFERENCES quality_specs(id);
