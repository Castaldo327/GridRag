-- Core warehouse: dimensions (dim_*) and grid facts (fact_*). Every row is fictional.

CREATE SCHEMA core;

CREATE TABLE core.dim_iso (
    iso_id   SMALLINT PRIMARY KEY,
    iso_code VARCHAR NOT NULL UNIQUE,
    timezone VARCHAR NOT NULL
);
COMMENT ON COLUMN core.dim_iso.timezone IS 'clock of interval_start_local';

CREATE TABLE core.dim_fuel (
    fuel_id        SMALLINT PRIMARY KEY,
    fuel_code      VARCHAR NOT NULL UNIQUE,
    name           VARCHAR NOT NULL,
    category       VARCHAR NOT NULL CHECK (category IN ('fossil', 'nuclear', 'renewable', 'storage', 'other')),
    is_renewable   BOOLEAN NOT NULL,
    is_carbon_free BOOLEAN NOT NULL
);
COMMENT ON TABLE core.dim_fuel IS 'Fuels and technologies shared by generation facts and queue projects.';
COMMENT ON COLUMN core.dim_fuel.fuel_code IS 'natural_gas, coal, oil, nuclear, hydro, wind, solar, geothermal, biomass, battery, hydrogen, transmission, other';
COMMENT ON COLUMN core.dim_fuel.is_renewable IS 'hydro, wind, solar, geothermal, biomass';
COMMENT ON COLUMN core.dim_fuel.is_carbon_free IS 'renewable or nuclear';

CREATE TABLE core.dim_location (
    location_id   INTEGER  PRIMARY KEY,
    iso_id        SMALLINT NOT NULL REFERENCES core.dim_iso (iso_id),
    location_code VARCHAR  NOT NULL UNIQUE,
    location_type VARCHAR  NOT NULL CHECK (location_type IN ('bus', 'hub'))
);
COMMENT ON TABLE core.dim_location IS 'Fictional price locations: three electrical buses and one trading hub per ISO.
Bus and hub IDs are not interchangeable.';
COMMENT ON COLUMN core.dim_location.location_code IS 'ISO_BUS_A, ISO_BUS_B, ISO_BUS_C or ISO_HUB, with ISO replaced by the ISO code';
COMMENT ON COLUMN core.dim_location.location_type IS 'no implied bus-to-hub averaging weights';

CREATE TABLE core.dim_queue_status (
    status_code VARCHAR PRIMARY KEY,
    description VARCHAR NOT NULL
);
COMMENT ON TABLE core.dim_queue_status IS 'Common status classes of interconnection-queue projects.';
COMMENT ON COLUMN core.dim_queue_status.status_code IS 'active, withdrawn, completed, suspended or unknown';

CREATE TABLE core.fact_balance_hourly (
    iso_id               SMALLINT  NOT NULL REFERENCES core.dim_iso (iso_id),
    interval_start_utc   TIMESTAMP NOT NULL,
    interval_start_local TIMESTAMP NOT NULL,
    demand_mw            DOUBLE,
    demand_forecast_mw   DOUBLE,
    net_generation_mw    DOUBLE,
    PRIMARY KEY (iso_id, interval_start_utc)
);
COMMENT ON TABLE core.fact_balance_hourly IS 'Hourly balance: total demand (load) and net generation across all fuels, the denominator of fuel shares.
One row per ISO and hour. Local timestamps repeat in the fall-back hour, so the key is UTC.
Joining to generation by ISO/hour is one-to-many: each balance measure repeats for every fuel.
Aggregate balance and fuel generation separately before combining totals, or make the join one-to-one.';
COMMENT ON COLUMN core.fact_balance_hourly.demand_mw IS 'demand (load), MW';
COMMENT ON COLUMN core.fact_balance_hourly.demand_forecast_mw IS 'one simple day-ahead demand estimate per hour, MW; no publication time, so not usable for a forecast known at a cutoff';
COMMENT ON COLUMN core.fact_balance_hourly.net_generation_mw IS 'net generation from all fuels, MW (the denominator of fuel shares)';

CREATE TABLE core.fact_generation_hourly (
    iso_id               SMALLINT  NOT NULL REFERENCES core.dim_iso (iso_id),
    interval_start_utc   TIMESTAMP NOT NULL,
    interval_start_local TIMESTAMP NOT NULL,
    fuel_id              SMALLINT  NOT NULL REFERENCES core.dim_fuel (fuel_id),
    generation_mw        DOUBLE    NOT NULL,
    PRIMARY KEY (iso_id, interval_start_utc, fuel_id)
);
COMMENT ON TABLE core.fact_generation_hourly IS 'Hourly generation by fuel: one row per ISO, hour and fuel; MW averaged over the hour.
Battery is net output: negative while charging.';
COMMENT ON COLUMN core.fact_generation_hourly.generation_mw IS 'generation (output) from this fuel, MW averaged over the hour';

CREATE TABLE core.fact_load_5min (
    iso_id               SMALLINT  NOT NULL REFERENCES core.dim_iso (iso_id),
    interval_start_utc   TIMESTAMP NOT NULL,
    interval_start_local TIMESTAMP NOT NULL,
    load_mw              DOUBLE,
    PRIMARY KEY (iso_id, interval_start_utc)
);
COMMENT ON TABLE core.fact_load_5min IS 'Five-minute load: one row per CAISO or ERCOT interval, local dates 2026-10-15 through 2026-10-21.
Can differ slightly from hourly demand.';
COMMENT ON COLUMN core.fact_load_5min.load_mw IS 'load (demand), MW';

CREATE TABLE core.fact_generation_5min (
    iso_id               SMALLINT  NOT NULL REFERENCES core.dim_iso (iso_id),
    interval_start_utc   TIMESTAMP NOT NULL,
    interval_start_local TIMESTAMP NOT NULL,
    fuel_id              SMALLINT  NOT NULL REFERENCES core.dim_fuel (fuel_id),
    generation_mw        DOUBLE    NOT NULL,
    PRIMARY KEY (iso_id, interval_start_utc, fuel_id)
);
COMMENT ON TABLE core.fact_generation_5min IS 'Five-minute generation by fuel for CAISO and ERCOT, local dates 2026-10-15 through 2026-10-21.
Battery is net output: negative while charging.';
COMMENT ON COLUMN core.fact_generation_5min.generation_mw IS 'generation (output) from this fuel, MW over the five minutes';

CREATE TABLE core.queue_project (
    project_id     INTEGER  PRIMARY KEY,
    iso_id         SMALLINT NOT NULL REFERENCES core.dim_iso (iso_id),
    queue_id       VARCHAR,
    project_name   VARCHAR,
    developer      VARCHAR,
    county         VARCHAR,
    state          VARCHAR,
    fuel_id        SMALLINT NOT NULL REFERENCES core.dim_fuel (fuel_id),
    technology     VARCHAR,
    status_code    VARCHAR  NOT NULL REFERENCES core.dim_queue_status (status_code),
    status_raw     VARCHAR,
    capacity_mw    DOUBLE,
    is_hybrid      BOOLEAN  NOT NULL,
    queue_date     DATE,
    proposed_cod   DATE,
    withdrawn_date DATE,
    completed_date DATE
);
COMMENT ON TABLE core.queue_project IS 'Interconnection queue: one fictional current project per row, as of 2026-10-21.
No historical status snapshots: entry dates cannot reconstruct what the queue looked like earlier.';
COMMENT ON COLUMN core.queue_project.queue_id IS 'fictional ISO-prefixed queue identifier';
COMMENT ON COLUMN core.queue_project.project_name IS 'fictional project name';
COMMENT ON COLUMN core.queue_project.developer IS 'interconnecting entity';
COMMENT ON COLUMN core.queue_project.county IS 'project county';
COMMENT ON COLUMN core.queue_project.state IS 'two-letter US state';
COMMENT ON COLUMN core.queue_project.technology IS 'fictional technology label';
COMMENT ON COLUMN core.queue_project.status_raw IS 'fictional raw status label behind status_code';
COMMENT ON COLUMN core.queue_project.capacity_mw IS 'proposed capacity, MW (not built capacity or output)';
COMMENT ON COLUMN core.queue_project.is_hybrid IS 'a non-storage project paired with storage';
COMMENT ON COLUMN core.queue_project.queue_date IS 'date the project entered the queue';
COMMENT ON COLUMN core.queue_project.proposed_cod IS 'proposed commercial operation date';
COMMENT ON COLUMN core.queue_project.withdrawn_date IS 'date a withdrawn project left the queue';
COMMENT ON COLUMN core.queue_project.completed_date IS 'date a completed project entered service';
