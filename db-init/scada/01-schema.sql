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
  type VARCHAR(32) NOT NULL CHECK (type IN ('press','weld','assembly','inspect')),
  installed_at DATE NOT NULL DEFAULT '2024-04-01',
  maker VARCHAR(64) NOT NULL DEFAULT 'Unknown'
);

CREATE TABLE sensor_readings (
  id BIGSERIAL PRIMARY KEY,
  equipment_id INT NOT NULL REFERENCES equipment(id),
  recorded_at TIMESTAMPTZ NOT NULL,
  temperature NUMERIC(6,2) NOT NULL,
  pressure NUMERIC(6,2) NOT NULL,
  vibration NUMERIC(6,3) NOT NULL,
  runtime_minutes NUMERIC(5,2) NOT NULL,
  quality SMALLINT NOT NULL DEFAULT 192
);
CREATE INDEX ix_sensor_eq_time ON sensor_readings (equipment_id, recorded_at);
COMMENT ON COLUMN sensor_readings.quality IS 'OPC UA QualityCode 0-255 (192+ = good, 64-191 = uncertain, 0-63 = bad)';

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
COMMENT ON TABLE production_events IS 'ラインの 1 時間ステータス(running/stopped/maintenance)。生産実績の集計は production_records も参照。';

-- タグマスタ。equipment × 物理量(温度/圧力/振動/稼働分)を定義し、
-- v_sensor_readings_long view 経由でナロー(縦持ち)アクセスを可能にする。
CREATE TABLE tags (
  id SERIAL PRIMARY KEY,
  equipment_id INT NOT NULL REFERENCES equipment(id),
  tag_name VARCHAR(32) NOT NULL,
  unit VARCHAR(16) NOT NULL,
  data_type VARCHAR(16) NOT NULL DEFAULT 'float',
  UNIQUE (equipment_id, tag_name)
);

-- アラーム履歴。OPC UA 風のしきい値超過イベントを発生→確認→復帰の状態遷移で管理。
CREATE TABLE alarms (
  id BIGSERIAL PRIMARY KEY,
  equipment_id INT NOT NULL REFERENCES equipment(id),
  alarm_code VARCHAR(32) NOT NULL,
  severity VARCHAR(8) NOT NULL CHECK (severity IN ('info','warn','crit')),
  time_on TIMESTAMPTZ NOT NULL,
  time_ack TIMESTAMPTZ,
  time_off TIMESTAMPTZ,
  duration_s INT GENERATED ALWAYS AS
              (EXTRACT(EPOCH FROM (time_off - time_on))::INT) STORED,
  description VARCHAR(256) NOT NULL
);
CREATE INDEX ix_alarms_eq_time ON alarms (equipment_id, time_on);

-- 生産実績。ライン × シフトごとに完成数/不良数を記録。
-- 旧 production_events からの集計と整合(同じ line・期間で defect_count が一致)。
CREATE TABLE production_records (
  id BIGSERIAL PRIMARY KEY,
  line_id INT NOT NULL REFERENCES lines(id),
  product_id INT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ NOT NULL,
  good_count INT NOT NULL CHECK (good_count >= 0),
  defect_count INT NOT NULL CHECK (defect_count >= 0),
  shift VARCHAR(8) NOT NULL CHECK (shift IN ('day','night')),
  CHECK (ended_at > started_at)
);
CREATE INDEX ix_prodrec_line_time ON production_records (line_id, started_at);

-- ナロー(縦持ち)ビュー。物理は sensor_readings のワイド形のまま、
-- LLM からは「タグごとの時系列」として参照できる。
CREATE OR REPLACE VIEW v_sensor_readings_long AS
SELECT sr.recorded_at, t.id AS tag_id, t.tag_name, t.unit,
       CASE t.tag_name
         WHEN 'TEMP'    THEN sr.temperature
         WHEN 'PRES'    THEN sr.pressure
         WHEN 'VIB'     THEN sr.vibration
         WHEN 'RUNTIME' THEN sr.runtime_minutes
       END::NUMERIC AS float_value,
       sr.quality
FROM sensor_readings sr
JOIN tags t ON t.equipment_id = sr.equipment_id;
