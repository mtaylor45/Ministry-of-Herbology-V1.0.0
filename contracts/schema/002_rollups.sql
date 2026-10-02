-- Continuous aggregates for the Almanac's 1 / 7 / 30-day history views.

CREATE MATERIALIZED VIEW reading_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', time) AS bucket,
    source_id,
    location_id,
    specimen_id,
    metric,
    avg(value)  AS avg_value,
    min(value)  AS min_value,
    max(value)  AS max_value,
    count(*)    AS samples
FROM reading
GROUP BY bucket, source_id, location_id, specimen_id, metric
WITH NO DATA;

SELECT add_continuous_aggregate_policy('reading_hourly',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

CREATE MATERIALIZED VIEW reading_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 day', time) AS bucket,
    location_id,
    specimen_id,
    metric,
    avg(value)  AS avg_value,
    min(value)  AS min_value,
    max(value)  AS max_value,
    count(*)    AS samples
FROM reading
GROUP BY bucket, location_id, specimen_id, metric
WITH NO DATA;

SELECT add_continuous_aggregate_policy('reading_daily',
    start_offset => INTERVAL '90 days',
    end_offset   => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour');

CREATE MATERIALIZED VIEW weather_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 day', time) AS bucket,
    site_id,
    avg(temperature_c) AS avg_temp_c,
    min(temperature_c) AS min_temp_c,
    max(temperature_c) AS max_temp_c,
    avg(humidity_pct)  AS avg_humidity_pct,
    sum(precip_mm)     AS precip_mm,
    sum(et0_mm)        AS et0_mm
FROM weather_obs
GROUP BY bucket, site_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('weather_daily',
    start_offset => INTERVAL '90 days',
    end_offset   => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour');

-- Keep raw readings for a year; the rollups carry the long history.
SELECT add_retention_policy('reading', INTERVAL '400 days');
