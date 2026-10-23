"""Build a small fictional warehouse: seven ISOs, their hourly demand and their interconnection queues.

    uv run python -m gridrag.warehouse.build
"""

from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gridrag.config import DB

SCHEMA = Path(__file__).with_name("schema.sql")
SEED = 20261023
START, END = pd.Timestamp("2025-01-01"), pd.Timestamp("2026-10-21")  

ISOS = {
    "CAISO": {"tz": "America/Los_Angeles", "demand_base_mw": 33500, "queue_projects": 168},
    "ERCOT": {"tz": "America/Chicago", "demand_base_mw": 61500, "queue_projects": 194},
    "ISONE": {"tz": "America/New_York", "demand_base_mw": 14700, "queue_projects": 106},
    "MISO": {"tz": "EST", "demand_base_mw": 64800, "queue_projects": 178},
    "NYISO": {"tz": "America/New_York", "demand_base_mw": 18300, "queue_projects": 120},
    "PJM": {"tz": "America/New_York", "demand_base_mw": 81000, "queue_projects": 220},
    "SPP": {"tz": "America/Chicago", "demand_base_mw": 39400, "queue_projects": 148},
}

# Order sets fuel_id. code -> (name, category).
FUELS = {
    "natural_gas": ("Natural gas", "fossil"),
    "coal": ("Coal", "fossil"),
    "oil": ("Oil", "fossil"),
    "nuclear": ("Nuclear", "nuclear"),
    "hydro": ("Hydro", "renewable"),
    "wind": ("Wind", "renewable"),
    "solar": ("Solar", "renewable"),
    "geothermal": ("Geothermal", "renewable"),
    "biomass": ("Biomass", "renewable"),
    "battery": ("Battery storage", "storage"),
    "hydrogen": ("Hydrogen", "other"),
    "transmission": ("Transmission", "other"),
    "other": ("Other or unknown", "other"),
}
QUEUE_STATUSES = {
    "active": "Active: in study, agreement or construction",
    "withdrawn": "Withdrawn, cancelled, terminated or retracted",
    "completed": "Completed / in service",
    "suspended": "Suspended",
    "unknown": "Status not reported",
}

def hourly(iso: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """One row per UTC hour covering local dates start..end on the ISO's clock."""
    zone = ISOS[iso]["tz"]
    first = start.tz_localize(zone).tz_convert("UTC")
    stop = (end + pd.DateOffset(days=1)).tz_localize(zone).tz_convert("UTC")
    utc = pd.date_range(first, stop, freq="h", inclusive="left")
    local = utc.tz_convert(zone).tz_localize(None)
    hour, day = local.hour.to_numpy(), local.dayofyear.to_numpy()
   
    # growth per year, weekend dip, late-July seasonal peak, afternoon daily peak, day-to-day wobble
    demand = ISOS[iso]["demand_base_mw"] * (1 + 0.02 * (local.year.to_numpy() - 2025)) * (
        1 - 0.045 * (local.dayofweek.to_numpy() >= 5)) * (
        1 + 0.08 * np.cos(2 * np.pi * (day - 205) / 365)) * (
        1 + 0.11 * np.sin(2 * np.pi * (hour - 8) / 24) + 0.025 * np.sin(day * 0.41 + (SEED % 1009) / 1009)
    )
    return pd.DataFrame({
        "iso_id": list(ISOS).index(iso) + 1,
        "interval_start_utc": utc.tz_localize(None),
        "interval_start_local": local,
        "demand_mw": np.round(demand, 2),
    })


def queue(as_of: pd.Timestamp) -> pd.DataFrame:
    """Current projects per ISO. Fuel, status and dates cycle on the project index, so every rebuild matches."""
    fuels = ["solar", "battery", "wind", "natural_gas", "hydro", "nuclear", "other"]
    statuses = ["active", "active", "active", "withdrawn", "completed", "suspended"]
    counties = {"CAISO": ["Riverside", "Kern", "San Bernardino", "Imperial"],
                "ERCOT": ["Travis", "Lubbock", "Harris", "Nueces"],
                "ISONE": ["Suffolk", "Worcester", "Essex", "Bristol"],
                "MISO": ["Cook", "Will", "Lake", "DuPage"],
                "NYISO": ["Kings", "Queens", "Erie", "Monroe"],
                "PJM": ["Allegheny", "Bucks", "Berks", "York"],
                "SPP": ["Oklahoma", "Tulsa", "Cleveland", "Canadian"]}
    states = {"CAISO": "CA", "ERCOT": "TX", "ISONE": "MA", "MISO": "IL", "NYISO": "NY", "PJM": "PA", "SPP": "OK"}
    raw_statuses = {
        "active": ("Active", "FIS In Progress", "IA Executed", "Under Construction", "Facility Study Stage"),
        "withdrawn": ("Withdrawn", "Canceled", "Terminated", "Deactivated"),
        "completed": ("In Service", "Completed", "Done"),
        "suspended": ("Suspended", "Pending Revision Approval"),
    }
    rows = []
    for iso_id, (code, info) in enumerate(ISOS.items(), 1):
        for i in range(info["queue_projects"]):
            fuel = fuels[(i * 3 + iso_id) % len(fuels)]
            status = statuses[(i * 5 + iso_id) % len(statuses)]
            entered = as_of.date() - timedelta(days=80 + (i * 31) % 1300)
            rows.append({
                "project_id": len(rows) + 1, "iso_id": iso_id, "queue_id": f"{code}-{i + 1:04d}",
                "project_name": f"{code} {fuel.replace('_', ' ').title()} {i + 1}",
                "developer": f"Example Energy {i % 17 + 1}", "county": counties[code][(i + iso_id) % 4],
                "state": states[code], "fuel_id": list(FUELS).index(fuel) + 1,
                "technology": {"solar": "Photovoltaic", "battery": "Battery Storage", "wind": "Wind",
                               "natural_gas": "Combined Cycle"}.get(fuel, fuel.title()),
                "status_code": status, "status_raw": raw_statuses[status][i % len(raw_statuses[status])],
                "capacity_mw": float(25 + (i * 37 + iso_id * 13) % 780),
                "is_hybrid": fuel in {"solar", "wind"} and i % 4 == 0,
                "queue_date": entered, "proposed_cod": entered + timedelta(days=730 + i % 400),
                "withdrawn_date": entered + timedelta(days=300) if status == "withdrawn" else None,
                "completed_date": entered + timedelta(days=600) if status == "completed" else None,
            })
    return pd.DataFrame(rows)


def _insert(con, table, frame):
    con.register("incoming", frame)
    con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM incoming")
    con.unregister("incoming")


def build() -> dict[str, int]:
    """Rebuild the warehouse from scratch; returns rows per table."""
    frames = {
        "core.dim_iso": pd.DataFrame([
            {"iso_id": i, "iso_code": code, "timezone": info["tz"]} for i, (code, info) in enumerate(ISOS.items(), 1)
        ]),
        "core.dim_fuel": pd.DataFrame([
            {"fuel_id": i, "fuel_code": code, "name": name, "category": category,
             "is_renewable": category == "renewable", "is_carbon_free": category in {"renewable", "nuclear"}}
            for i, (code, (name, category)) in enumerate(FUELS.items(), 1)
        ]),
        "core.dim_queue_status": pd.DataFrame([
            {"status_code": code, "description": description} for code, description in QUEUE_STATUSES.items()
        ]),
        "core.fact_balance_hourly": pd.concat([hourly(iso, START, END) for iso in ISOS], ignore_index=True),
        "core.queue_project": queue(END),
    }
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    with duckdb.connect(str(DB)) as con:
        con.execute(SCHEMA.read_text())
        for table, frame in frames.items():  # dimensions first, so foreign keys resolve
            _insert(con, table, frame)
    return {table: len(frame) for table, frame in frames.items()}


if __name__ == "__main__":
    for table, rows in build().items():
        print(f"{table}: {rows:,} rows")
