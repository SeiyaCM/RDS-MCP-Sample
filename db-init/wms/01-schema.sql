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
  UNIQUE (warehouse_id, zone, shelf)
);

CREATE TABLE inventory (
  id SERIAL PRIMARY KEY,
  part_id INT NOT NULL,
  location_id INT NOT NULL REFERENCES locations(id),
  qty INT NOT NULL CHECK (qty >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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
