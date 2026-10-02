-- One observation row per site per instant.
--
-- `weather_daily` sums `precip_mm` without `source` in its grouping. Two rows
-- for the same hour therefore double that day's rain, which clears a soil-water
-- deficit nothing actually cleared and leaves an outdoor plant unwatered. Under
-- the design nothing measures the soil, so there is no second opinion to catch it.
--
-- Unique on (site_id, time) rather than (site_id, time, source): this table is
-- the site's observed weather, not every source's opinion of it, and `source`
-- records which one the row came from. Storing disagreeing sources for one hour
-- is a real feature but not a v1 need, and it would make the aggregate pick a
-- winner per row rather than trust its own grouping.
--
-- The ingest already replaces whole windows to avoid duplicates; this lets the
-- database enforce what one module could only promise. Timescale requires the
-- partitioning column in a unique index, and `time` is it.

CREATE UNIQUE INDEX weather_obs_site_time_key ON weather_obs (site_id, time);

-- The non-unique index this supersedes: (site_id, time DESC) was there to serve
-- the Almanac's "most recent first" reads, which the unique index above cannot
-- satisfy as cheaply in that direction. Kept deliberately.
