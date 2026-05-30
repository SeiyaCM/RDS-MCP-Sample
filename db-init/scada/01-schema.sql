CREATE TABLE factories (
  id INT PRIMARY KEY,
  name VARCHAR(64) NOT NULL UNIQUE,
  region VARCHAR(32) NOT NULL
);

CREATE TABLE lines (
  id INT PRIMARY KEY,
  factory_id INT NOT NULL REFERENCES factories(id),
  name VARCHAR(64) NOT NULL,
  UNIQUE (factory_id, name)
);

CREATE TABLE equipment (
  id INT PRIMARY KEY,
  line_id INT NOT NULL REFERENCES lines(id),
  name VARCHAR(64) NOT NULL,
  type VARCHAR(32) NOT NULL CHECK (type IN ('press','weld','assembly','inspect'))
);

CREATE TABLE sensor_readings (
  id BIGSERIAL PRIMARY KEY,
  equipment_id INT NOT NULL REFERENCES equipment(id),
  recorded_at TIMESTAMPTZ NOT NULL,
  temperature NUMERIC(6,2) NOT NULL,
  pressure NUMERIC(6,2) NOT NULL,
  vibration NUMERIC(6,3) NOT NULL,
  runtime_minutes NUMERIC(5,2) NOT NULL
);
CREATE INDEX ix_sensor_eq_time ON sensor_readings (equipment_id, recorded_at);

CREATE TABLE production_events (
  id BIGSERIAL PRIMARY KEY,
  line_id INT NOT NULL REFERENCES lines(id),
  occurred_at TIMESTAMPTZ NOT NULL,
  event_type VARCHAR(16) NOT NULL CHECK (event_type IN ('running','stopped','maintenance')),
  produced_qty INT NOT NULL DEFAULT 0,
  defect_qty INT NOT NULL DEFAULT 0,
  CHECK (defect_qty <= produced_qty)
);
CREATE INDEX ix_prodev_line_time ON production_events (line_id, occurred_at);
