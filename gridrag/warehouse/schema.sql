-- Core warehouse: dimensions (dim_*) and grid facts (fact_*). Every row is fictional.

CREATE SCHEMA core;

CREATE TABLE core.dim_iso (
    iso_id   SMALLINT PRIMARY KEY,
    iso_code VARCHAR NOT NULL UNIQUE,
    timezone VARCHAR NOT NULL  -- clock of interval_start_local
);

-- One row per ISO and hour. Local timestamps repeat in the fall-back hour, so the key is UTC.
CREATE TABLE core.fact_balance_hourly (
    iso_id               SMALLINT  NOT NULL REFERENCES core.dim_iso (iso_id),
    interval_start_utc   TIMESTAMP NOT NULL,
    interval_start_local TIMESTAMP NOT NULL,
    demand_mw            DOUBLE,
    PRIMARY KEY (iso_id, interval_start_utc)
);
