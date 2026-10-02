-- The Ministry of Herbology — schema v1
-- Forward-only. Do not edit; add a new numbered migration instead.

CREATE EXTENSION IF NOT EXISTS "timescaledb";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "citext";

-- ---------------------------------------------------------------------------
-- Household and members
-- ---------------------------------------------------------------------------

CREATE TABLE member (
    id              uuid PRIMARY KEY,
    name            text NOT NULL,
    role            text NOT NULL DEFAULT 'tender'
                        CHECK (role IN ('keeper', 'tender', 'observer')),
    email           citext,
    notify_prefs    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    archived_at     timestamptz
);

-- ---------------------------------------------------------------------------
-- Places: site -> area -> zone, plus map layers
-- ---------------------------------------------------------------------------

CREATE TABLE site (
    id              uuid PRIMARY KEY,
    name            text NOT NULL,
    latitude        double precision NOT NULL,
    longitude       double precision NOT NULL,
    elevation_m     double precision,
    timezone        text NOT NULL,
    nws_zone        text,             -- e.g. 'INZ050', for frost/freeze advisories
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE map_layer (
    id              uuid PRIMARY KEY,
    site_id         uuid NOT NULL REFERENCES site(id) ON DELETE CASCADE,
    name            text NOT NULL,
    kind            text NOT NULL CHECK (kind IN ('floor_plan', 'survey')),
    image_key       text NOT NULL,    -- object-store key for the plan or survey image
    image_width_px  integer NOT NULL,
    image_height_px integer NOT NULL,
    -- floor plans use CRS.Simple with a px->mm scale; surveys are georeferenced
    scale_mm_per_px double precision,
    calibration     jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{px:[x,y], world:[lat,lon]}...]
    ordinal         integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE location (
    id              uuid PRIMARY KEY,
    site_id         uuid NOT NULL REFERENCES site(id) ON DELETE CASCADE,
    parent_id       uuid REFERENCES location(id) ON DELETE CASCADE,
    name            text NOT NULL,
    kind            text NOT NULL CHECK (kind IN ('area', 'zone', 'bed', 'room', 'shelf')),
    is_outdoor      boolean NOT NULL,
    is_covered      boolean NOT NULL DEFAULT false,   -- porch, eave: rain does not reach
    sun_exposure    text CHECK (sun_exposure IN
                        ('full_sun', 'part_sun', 'part_shade', 'full_shade', 'unknown')),
    map_layer_id    uuid REFERENCES map_layer(id) ON DELETE SET NULL,
    -- polygon in layer pixel coordinates for zones drawn on a plan or survey
    boundary_px     jsonb,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    archived_at     timestamptz
);

CREATE INDEX location_site_idx   ON location(site_id);
CREATE INDEX location_parent_idx ON location(parent_id);

-- ---------------------------------------------------------------------------
-- Botanical knowledge: sources, species, cited care values
-- ---------------------------------------------------------------------------

CREATE TABLE source (
    id              uuid PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN
                        ('powo', 'gbif', 'wikipedia', 'wikidata', 'usda', 'perenual',
                         'plantnet', 'nws', 'open_meteo', 'user', 'other')),
    title           text NOT NULL,
    url             text,
    license         text,
    retrieved_at    timestamptz NOT NULL DEFAULT now(),
    payload         jsonb        -- raw response, cached for re-synthesis
);

CREATE TABLE species (
    id                  uuid PRIMARY KEY,
    accepted_name       text NOT NULL,              -- 'Monstera deliciosa'
    rank                text NOT NULL DEFAULT 'species'
                            CHECK (rank IN ('species', 'subspecies', 'variety', 'hybrid', 'genus')),
    family              text,
    genus               text,
    common_names        text[] NOT NULL DEFAULT '{}',
    gbif_key            text,
    powo_id             text,
    native_range        text[],
    summary             text,                        -- Compendium prose
    -- care profile: canonical, machine-readable; every value cited in care_value
    light_min_lux       integer,
    light_max_lux       integer,
    light_label         text CHECK (light_label IN
                            ('full_sun', 'bright_indirect', 'part_shade', 'low_light', 'unknown')),
    water_k_c           double precision,            -- crop coefficient for the water balance
    water_interval_days integer,                     -- indoor fallback interval
    soil_ph_min         double precision,
    soil_ph_max         double precision,
    soil_type           text,
    fertilizer_note     text,
    humidity_min_pct    integer,
    min_temp_c          double precision,            -- frost threshold
    max_temp_c          double precision,
    usda_zone_min       text,
    usda_zone_max       text,
    dormancy_months     integer[],                   -- 1-12; care is dialled back
    toxic_to_pets       boolean,
    toxic_to_children   boolean,
    toxicity_note       text,
    enrichment_state    text NOT NULL DEFAULT 'pending'
                            CHECK (enrichment_state IN ('pending', 'running', 'complete', 'failed')),
    enriched_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX species_accepted_name_key ON species(lower(accepted_name));
CREATE INDEX species_name_trgm ON species USING gin (accepted_name gin_trgm_ops);

-- The no-invented-plant-facts rule: no invented plant facts. Every care field above has a row here saying
-- where it came from and how much to trust it.
CREATE TABLE care_value (
    id              uuid PRIMARY KEY,
    species_id      uuid NOT NULL REFERENCES species(id) ON DELETE CASCADE,
    field           text NOT NULL,           -- column name in species, e.g. 'water_k_c'
    value           jsonb NOT NULL,
    unit            text,
    source_id       uuid REFERENCES source(id) ON DELETE SET NULL,
    confidence      text NOT NULL CHECK (confidence IN ('high', 'medium', 'low', 'unknown')),
    is_user_override boolean NOT NULL DEFAULT false,
    edited_by       uuid REFERENCES member(id) ON DELETE SET NULL,
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX care_value_species_field_idx ON care_value(species_id, field);
-- A cited value is one with a source; an uncited one must be 'unknown' confidence.
ALTER TABLE care_value ADD CONSTRAINT care_value_uncited_is_unknown
    CHECK (source_id IS NOT NULL OR is_user_override OR confidence = 'unknown');

-- ---------------------------------------------------------------------------
-- Specimens: the actual plants
-- ---------------------------------------------------------------------------

CREATE TABLE specimen (
    id              uuid PRIMARY KEY,
    species_id      uuid REFERENCES species(id) ON DELETE SET NULL,
    nickname        text,
    cultivar        text,
    is_group        boolean NOT NULL DEFAULT false,   -- a bed or clump counted as one
    count           integer NOT NULL DEFAULT 1 CHECK (count > 0),
    location_id     uuid REFERENCES location(id) ON DELETE SET NULL,
    map_layer_id    uuid REFERENCES map_layer(id) ON DELETE SET NULL,
    pin_px          jsonb,                            -- {x, y} in layer pixels
    is_outdoor      boolean NOT NULL DEFAULT false,   -- denormalised from location for fast filters
    in_container    boolean NOT NULL DEFAULT true,
    container_litres double precision,
    container_note  text,
    soil_note       text,
    acquired_on     date,
    provenance      text,
    status          text NOT NULL DEFAULT 'thriving'
                        CHECK (status IN ('thriving', 'struggling', 'dormant', 'overwintering',
                                          'lost', 'given_away', 'archived')),
    -- care overrides: NULL means "use the species value"
    water_k_c_override           double precision,
    water_interval_days_override integer,
    min_temp_c_override          double precision,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    archived_at     timestamptz
);

CREATE INDEX specimen_location_idx ON specimen(location_id);
CREATE INDEX specimen_species_idx  ON specimen(species_id);
CREATE INDEX specimen_outdoor_idx  ON specimen(is_outdoor) WHERE archived_at IS NULL;

CREATE TABLE photo (
    id              uuid PRIMARY KEY,
    specimen_id     uuid NOT NULL REFERENCES specimen(id) ON DELETE CASCADE,
    image_key       text NOT NULL,
    taken_at        timestamptz NOT NULL DEFAULT now(),
    caption         text,
    is_primary      boolean NOT NULL DEFAULT false,
    taken_by        uuid REFERENCES member(id) ON DELETE SET NULL
);

CREATE INDEX photo_specimen_idx ON photo(specimen_id, taken_at DESC);

CREATE TABLE log_entry (
    id              uuid PRIMARY KEY,
    specimen_id     uuid NOT NULL REFERENCES specimen(id) ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN
                        ('growth', 'pest', 'disease', 'repot', 'prune', 'relocate', 'note')),
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    body            text,
    photo_id        uuid REFERENCES photo(id) ON DELETE SET NULL,
    data            jsonb NOT NULL DEFAULT '{}'::jsonb,   -- e.g. {from_location, to_location}
    logged_by       uuid REFERENCES member(id) ON DELETE SET NULL
);

CREATE INDEX log_entry_specimen_idx ON log_entry(specimen_id, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- Sensors, readings, weather (Timescale hypertables)
-- ---------------------------------------------------------------------------

CREATE TABLE sensor_source (
    id              uuid PRIMARY KEY,
    name            text NOT NULL,
    adapter         text NOT NULL CHECK (adapter IN
                        ('home_assistant', 'ecowitt', 'miflora', 'homekit', 'nest', 'manual')),
    external_ids    jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {temperature: 'sensor.x', ...}
    location_id     uuid REFERENCES location(id) ON DELETE SET NULL,
    specimen_id     uuid REFERENCES specimen(id) ON DELETE SET NULL,  -- soil probes
    poll_seconds    integer NOT NULL DEFAULT 300,
    enabled         boolean NOT NULL DEFAULT true,
    last_seen_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reading (
    time            timestamptz NOT NULL,
    source_id       uuid NOT NULL REFERENCES sensor_source(id) ON DELETE CASCADE,
    metric          text NOT NULL CHECK (metric IN
                        ('temperature_c', 'humidity_pct', 'soil_moisture_pct',
                         'soil_temperature_c', 'illuminance_lux', 'soil_ec')),
    value           double precision NOT NULL,
    location_id     uuid REFERENCES location(id) ON DELETE SET NULL,
    specimen_id     uuid REFERENCES specimen(id) ON DELETE SET NULL
);

SELECT create_hypertable('reading', 'time', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX reading_source_metric_idx   ON reading(source_id, metric, time DESC);
CREATE INDEX reading_specimen_metric_idx ON reading(specimen_id, metric, time DESC);

CREATE TABLE weather_obs (
    time            timestamptz NOT NULL,
    site_id         uuid NOT NULL REFERENCES site(id) ON DELETE CASCADE,
    temperature_c   double precision,
    humidity_pct    double precision,
    precip_mm       double precision,
    et0_mm          double precision,
    wind_kph        double precision,
    solar_wm2       double precision,
    cloud_pct       double precision,
    condition       text,
    source          text NOT NULL DEFAULT 'open_meteo'
);

SELECT create_hypertable('weather_obs', 'time', chunk_time_interval => INTERVAL '30 days');
CREATE INDEX weather_obs_site_idx ON weather_obs(site_id, time DESC);

CREATE TABLE weather_forecast (
    time            timestamptz NOT NULL,       -- the hour or day being forecast
    site_id         uuid NOT NULL REFERENCES site(id) ON DELETE CASCADE,
    issued_at       timestamptz NOT NULL,
    horizon         text NOT NULL CHECK (horizon IN ('hourly', 'daily')),
    temperature_c   double precision,
    temp_min_c      double precision,
    temp_max_c      double precision,
    precip_mm       double precision,
    precip_prob_pct double precision,
    et0_mm          double precision,
    wind_kph        double precision,
    condition       text,
    sunrise         timestamptz,
    sunset          timestamptz,
    source          text NOT NULL DEFAULT 'open_meteo'
);

SELECT create_hypertable('weather_forecast', 'time', chunk_time_interval => INTERVAL '30 days');
CREATE UNIQUE INDEX weather_forecast_key
    ON weather_forecast(site_id, horizon, time, issued_at);

CREATE TABLE weather_alert (
    id              uuid PRIMARY KEY,
    site_id         uuid NOT NULL REFERENCES site(id) ON DELETE CASCADE,
    external_id     text NOT NULL,              -- NWS alert id
    event           text NOT NULL,              -- 'Frost Advisory', 'Freeze Warning'
    severity        text,
    onset           timestamptz,
    expires         timestamptz,
    headline        text,
    description     text,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (site_id, external_id)
);

-- ---------------------------------------------------------------------------
-- Water balance (E) — one row per specimen per day
-- ---------------------------------------------------------------------------

CREATE TABLE water_balance (
    day             date NOT NULL,
    specimen_id     uuid NOT NULL REFERENCES specimen(id) ON DELETE CASCADE,
    deficit_mm      double precision NOT NULL,
    capacity_mm     double precision NOT NULL,      -- D_max
    threshold_mm    double precision NOT NULL,      -- water when deficit crosses this
    et0_mm          double precision NOT NULL DEFAULT 0,
    k_c             double precision NOT NULL,
    precip_mm       double precision NOT NULL DEFAULT 0,
    irrigation_mm   double precision NOT NULL DEFAULT 0,
    cover_factor    double precision NOT NULL DEFAULT 1,
    sensor_override_pct double precision,           -- soil probe wins when present
    computed_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (specimen_id, day)
);

CREATE INDEX water_balance_day_idx ON water_balance(day DESC);

-- ---------------------------------------------------------------------------
-- Care rules and tasks (G)
-- ---------------------------------------------------------------------------

CREATE TABLE care_rule (
    id              uuid PRIMARY KEY,
    species_id      uuid REFERENCES species(id) ON DELETE CASCADE,
    specimen_id     uuid REFERENCES specimen(id) ON DELETE CASCADE,
    task_type       text NOT NULL CHECK (task_type IN
                        ('water', 'fertilize', 'mist', 'prune', 'repot', 'inspect',
                         'bring_indoors', 'return_outdoors', 'cover', 'rotate')),
    strategy        text NOT NULL DEFAULT 'interval'
                        CHECK (strategy IN ('interval', 'water_balance', 'frost_guard', 'seasonal')),
    base_interval_days integer,
    amount_ml       integer,
    modifiers       jsonb NOT NULL DEFAULT '{}'::jsonb,
                    -- {season: {winter: 1.6}, humidity_low: 0.8, dormancy: 'suspend'}
    months          integer[],                      -- restrict to these months
    enabled         boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (species_id IS NOT NULL OR specimen_id IS NOT NULL)
);

CREATE INDEX care_rule_specimen_idx ON care_rule(specimen_id) WHERE enabled;
CREATE INDEX care_rule_species_idx  ON care_rule(species_id)  WHERE enabled;

CREATE TABLE task (
    id              uuid PRIMARY KEY,
    specimen_id     uuid NOT NULL REFERENCES specimen(id) ON DELETE CASCADE,
    care_rule_id    uuid REFERENCES care_rule(id) ON DELETE SET NULL,
    task_type       text NOT NULL,
    due_at          timestamptz NOT NULL,
    all_day         boolean NOT NULL DEFAULT true,
    status          text NOT NULL DEFAULT 'due'
                        CHECK (status IN ('due', 'done', 'satisfied', 'skipped', 'cancelled')),
    satisfied_by    text CHECK (satisfied_by IN ('rain', 'sensor', 'forecast_change', 'manual')),
    amount_ml       integer,
    priority        text NOT NULL DEFAULT 'normal'
                        CHECK (priority IN ('low', 'normal', 'urgent')),
    title           text NOT NULL,               -- themed
    plain_title     text NOT NULL,               -- the original-theme rule: always a plain equivalent
    detail          text,
    completed_at    timestamptz,
    completed_by    uuid REFERENCES member(id) ON DELETE SET NULL,
    notes           text,
    -- stable ICS identity, so reschedules update in place instead of duplicating
    ics_uid         text NOT NULL,
    ics_sequence    integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX task_ics_uid_key   ON task(ics_uid);
CREATE INDEX task_due_idx              ON task(due_at) WHERE status = 'due';
CREATE INDEX task_specimen_idx         ON task(specimen_id, due_at DESC);

CREATE TABLE task_event (
    id              uuid PRIMARY KEY,
    task_id         uuid NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    at              timestamptz NOT NULL DEFAULT now(),
    kind            text NOT NULL CHECK (kind IN
                        ('created', 'rescheduled', 'completed', 'satisfied',
                         'skipped', 'cancelled', 'reopened', 'noted')),
    by_member       uuid REFERENCES member(id) ON DELETE SET NULL,
    data            jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX task_event_task_idx ON task_event(task_id, at DESC);

CREATE TABLE frost_alert (
    id              uuid PRIMARY KEY,
    specimen_id     uuid NOT NULL REFERENCES specimen(id) ON DELETE CASCADE,
    night_of        date NOT NULL,
    forecast_low_c  double precision NOT NULL,
    threshold_c     double precision NOT NULL,
    advisory_id     uuid REFERENCES weather_alert(id) ON DELETE SET NULL,
    action          text NOT NULL CHECK (action IN ('bring_indoors', 'cover', 'monitor')),
    task_id         uuid REFERENCES task(id) ON DELETE SET NULL,
    state           text NOT NULL DEFAULT 'open'
                        CHECK (state IN ('open', 'resolved', 'expired')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (specimen_id, night_of)
);

-- ---------------------------------------------------------------------------
-- Calendar feeds (G)
-- ---------------------------------------------------------------------------

CREATE TABLE calendar_feed (
    id              uuid PRIMARY KEY,
    member_id       uuid NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    name            text NOT NULL,
    token           text NOT NULL,                  -- URL secret; revoke by rotating
    filters         jsonb NOT NULL DEFAULT '{}'::jsonb,
                    -- {outdoor: true, task_types: ['water'], location_ids: [...]}
    push_target     text CHECK (push_target IN ('none', 'google', 'caldav')),
    push_config     jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_rendered_at timestamptz,
    revoked_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX calendar_feed_token_key ON calendar_feed(token);

-- ---------------------------------------------------------------------------
-- Naturalist's Journal (K)
-- ---------------------------------------------------------------------------

CREATE TABLE plate (
    id              uuid PRIMARY KEY,
    species_id      uuid REFERENCES species(id) ON DELETE CASCADE,
    specimen_id     uuid REFERENCES specimen(id) ON DELETE CASCADE,
    image_key       text NOT NULL,
    thumb_key       text,
    origin          text NOT NULL CHECK (origin IN ('public_domain', 'generated', 'user_upload')),
    source_id       uuid REFERENCES source(id) ON DELETE SET NULL,
    license         text,
    attribution     text,
    style           text,                            -- the one house style for generated plates
    approved        boolean NOT NULL DEFAULT false,
    approved_by     uuid REFERENCES member(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (species_id IS NOT NULL OR specimen_id IS NOT NULL),
    CHECK (origin <> 'public_domain' OR license IS NOT NULL)
);

CREATE TABLE field_note (
    id              uuid PRIMARY KEY,
    specimen_id     uuid NOT NULL REFERENCES specimen(id) ON DELETE CASCADE,
    body            text NOT NULL,
    written_at      timestamptz NOT NULL DEFAULT now(),
    written_by      uuid REFERENCES member(id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------------------
-- Integration bookkeeping (F)
-- ---------------------------------------------------------------------------

CREATE TABLE integration (
    id              uuid PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN
                        ('home_assistant', 'mqtt', 'google_calendar', 'caldav',
                         'lunette', 'plantnet', 'perenual')),
    name            text NOT NULL,
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- secrets live in the secret store
    enabled         boolean NOT NULL DEFAULT true,
    last_ok_at      timestamptz,
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job_run (
    id              uuid PRIMARY KEY,
    job             text NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    ok              boolean,
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX job_run_job_idx ON job_run(job, started_at DESC);
