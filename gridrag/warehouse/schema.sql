-- Core warehouse: dimensions (dim_*) and grid facts (fact_*). Every row is fictional.

CREATE SCHEMA core;

CREATE TABLE core.dim_iso (
    iso_id   SMALLINT PRIMARY KEY,
    iso_code VARCHAR NOT NULL UNIQUE,
    timezone VARCHAR NOT NULL  -- clock of interval_start_local
);

-- Fuels and technologies; queue projects reference these.
CREATE TABLE core.dim_fuel (
    fuel_id        SMALLINT PRIMARY KEY,
    fuel_code      VARCHAR NOT NULL UNIQUE,  -- natural_gas, coal, oil, nuclear, hydro, wind, solar, geothermal, biomass, battery, hydrogen, transmission, other
    name           VARCHAR NOT NULL,
    category       VARCHAR NOT NULL CHECK (category IN ('fossil', 'nuclear', 'renewable', 'storage', 'other')),
    is_renewable   BOOLEAN NOT NULL,         -- hydro, wind, solar, geothermal, biomass
    is_carbon_free BOOLEAN NOT NULL          -- renewable or nuclear
);

-- Common status classes of interconnection-queue projects.
CREATE TABLE core.dim_queue_status (
    status_code VARCHAR PRIMARY KEY,  -- active, withdrawn, completed, suspended or unknown
    description VARCHAR NOT NULL
);

-- One row per ISO and hour. Local timestamps repeat in the fall-back hour, so the key is UTC.
CREATE TABLE core.fact_balance_hourly (
    iso_id               SMALLINT  NOT NULL REFERENCES core.dim_iso (iso_id),
    interval_start_utc   TIMESTAMP NOT NULL,
    interval_start_local TIMESTAMP NOT NULL,
    demand_mw            DOUBLE,
    PRIMARY KEY (iso_id, interval_start_utc)
);

-- Interconnection queue: one fictional current project per row, as of 2026-10-21.
-- No historical status snapshots: entry dates cannot reconstruct what the queue looked like earlier.
CREATE TABLE core.queue_project (
    project_id     INTEGER  PRIMARY KEY,
    iso_id         SMALLINT NOT NULL REFERENCES core.dim_iso (iso_id),
    queue_id       VARCHAR,                -- fictional ISO-prefixed queue identifier
    project_name   VARCHAR,
    developer      VARCHAR,                -- interconnecting entity
    county         VARCHAR,
    state          VARCHAR,                -- two-letter US state
    fuel_id        SMALLINT NOT NULL REFERENCES core.dim_fuel (fuel_id),
    technology     VARCHAR,                -- fictional technology label
    status_code    VARCHAR  NOT NULL REFERENCES core.dim_queue_status (status_code),
    status_raw     VARCHAR,                -- fictional raw status label behind status_code
    capacity_mw    DOUBLE,                 -- proposed capacity, MW (not built capacity or output)
    is_hybrid      BOOLEAN  NOT NULL,      -- a non-storage project paired with storage
    queue_date     DATE,                   -- date the project entered the queue
    proposed_cod   DATE,                   -- proposed commercial operation date
    withdrawn_date DATE,
    completed_date DATE
);
