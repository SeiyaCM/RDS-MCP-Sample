CREATE TABLE inspections (
  id SERIAL PRIMARY KEY,
  line_id INT NOT NULL,
  inspected_at TIMESTAMPTZ NOT NULL,
  lot_no VARCHAR(32) NOT NULL,
  sample_qty INT NOT NULL,
  ok_qty INT NOT NULL,
  ng_qty INT NOT NULL,
  inspector VARCHAR(64) NOT NULL,
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
  status VARCHAR(16) NOT NULL CHECK (status IN ('open','in_progress','closed'))
);
