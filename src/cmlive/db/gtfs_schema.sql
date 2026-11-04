-- Tabelas do GTFS, criadas num esquema temporário ({schema}) e trocadas atomicamente.
CREATE SCHEMA {schema};

CREATE TABLE {schema}.feed_info (
    feed_version text, loaded_at timestamptz, source_url text, sha256 text,
    n_trips integer, n_stop_times integer
);

CREATE TABLE {schema}.routes (
    route_id text PRIMARY KEY, line_id text, short_name text, long_name text,
    color text, text_color text
);

CREATE TABLE {schema}.stops (
    stop_id text PRIMARY KEY, name text, lat double precision, lon double precision,
    municipality text
);

CREATE TABLE {schema}.trips (
    trip_id text PRIMARY KEY, route_id text, service_id text, direction_id smallint,
    pattern_id text, headsign text
);

CREATE TABLE {schema}.calendar_dates (
    service_id text, date date, exception_type smallint
);

CREATE TABLE {schema}.stop_times (
    trip_id text, stop_sequence integer, stop_id text, arrival_s integer
);
