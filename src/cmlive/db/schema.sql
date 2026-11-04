-- Esquema principal. Idempotente: pode ser aplicado em cada arranque.
-- Vários serviços arrancam ao mesmo tempo: apply_schema() serializa com um advisory lock.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ------------------------------------------------------------------ posições
CREATE TABLE IF NOT EXISTS vehicle_positions (
    ts             timestamptz      NOT NULL,  -- instante reportado pelo veículo
    vehicle_id     text             NOT NULL,
    lat            double precision NOT NULL,
    lon            double precision NOT NULL,
    bearing        real,
    speed          real,
    trip_id        text,
    line_id        text,
    route_id       text,
    stop_id        text,
    current_status text,
    agency_id      text,
    collected_at   timestamptz      NOT NULL,  -- coletor recebeu a resposta
    ingested_at    timestamptz      NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (vehicle_id, ts)               -- idempotência: duplicados são ignorados
);
SELECT create_hypertable('vehicle_positions', by_range('ts', INTERVAL '1 day'),
                         if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS vehicle_positions_trip_idx ON vehicle_positions (trip_id, ts);

DO $$
BEGIN
    IF NOT (SELECT compression_enabled FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'vehicle_positions') THEN
        ALTER TABLE vehicle_positions SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'vehicle_id',
            timescaledb.compress_orderby = 'ts'
        );
    END IF;
END $$;
SELECT add_compression_policy('vehicle_positions', INTERVAL '2 days', if_not_exists => TRUE);

-- ------------------------------------------------------------------ chegadas
-- Particionada pela hora PLANEADA: é determinística (vem do GTFS), por isso o mesmo
-- evento reprocessado cai sempre na mesma linha da chave primária.
CREATE TABLE IF NOT EXISTS stop_arrivals (
    scheduled_at   timestamptz NOT NULL,
    trip_id        text        NOT NULL,
    stop_sequence  integer     NOT NULL,
    service_date   date        NOT NULL,
    stop_id        text        NOT NULL,
    vehicle_id     text        NOT NULL,
    line_id        text,
    route_id       text,
    observed_at    timestamptz NOT NULL,
    delay_s        integer     NOT NULL,
    method         text        NOT NULL,
    uncertainty_s  real        NOT NULL,
    detected_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (trip_id, stop_sequence, scheduled_at)
);
SELECT create_hypertable('stop_arrivals', by_range('scheduled_at', INTERVAL '7 days'),
                         if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS stop_arrivals_line_idx ON stop_arrivals (line_id, scheduled_at DESC);
CREATE INDEX IF NOT EXISTS stop_arrivals_stop_idx ON stop_arrivals (stop_id, scheduled_at DESC);

-- ------------------------------------------------------------------ agregações incrementais
-- Continuous aggregate: o TimescaleDB só recalcula os buckets onde entraram dados novos.
-- "Pontual" = entre 1 min adiantado e 5 min atrasado (ver README).
CREATE MATERIALIZED VIEW IF NOT EXISTS delay_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
    time_bucket(INTERVAL '1 hour', scheduled_at)        AS bucket,
    line_id,
    count(*)                                            AS n,
    avg(delay_s)::real                                  AS avg_delay_s,
    sum(delay_s::double precision * delay_s)            AS sum_sq_delay,
    min(delay_s)                                        AS min_delay_s,
    max(delay_s)                                        AS max_delay_s,
    count(*) FILTER (WHERE delay_s < -60)               AS n_early,
    count(*) FILTER (WHERE delay_s BETWEEN -60 AND 300) AS n_on_time,
    count(*) FILTER (WHERE delay_s > 300)               AS n_late
FROM stop_arrivals
WHERE uncertainty_s <= 60
GROUP BY bucket, line_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('delay_hourly',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists     => TRUE);

-- ------------------------------------------------------------------ GTFS ativo
CREATE SCHEMA IF NOT EXISTS gtfs;
CREATE TABLE IF NOT EXISTS gtfs.feed_info (
    feed_version text, loaded_at timestamptz, source_url text, sha256 text,
    n_trips integer, n_stop_times integer
);
