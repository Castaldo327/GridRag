"""Build a small fictional warehouse: seven ISOs, their hourly demand and generation by fuel, five-minute
load and generation for CAISO and ERCOT, and the interconnection queues.

    uv run python -m gridrag.warehouse.build
"""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gridrag import config
from gridrag.warehouse import products

SCHEMA = Path(__file__).with_name("schema.sql")
SEED = 20261023
START, END = pd.Timestamp("2025-01-01"), pd.Timestamp("2026-10-21")
FIVE_START, FIVE_MINUTE_ISOS = pd.Timestamp("2026-10-15"), ("CAISO", "ERCOT")  # last week only, two ISOs
# per-ISO products (prices) cover the same last week, for all seven ISOs


@dataclass(frozen=True)
class Iso:
    """One fictional ISO. id is explicit, so adding an ISO never renumbers another's rows, locations or checks."""

    id: int
    code: str
    tz: str
    demand_base_mw: int
    solar_peak_mw: int
    wind_base_mw: int
    queue_projects: int
    state: str  # where its fictional queue projects are sited
    counties: tuple[str, ...]


ISOS = (
    Iso(id=1, code="CAISO", tz="America/Los_Angeles", demand_base_mw=33500, solar_peak_mw=14500, wind_base_mw=4100,
        queue_projects=168, state="CA", counties=("Riverside", "Kern", "San Bernardino", "Imperial")),
    Iso(id=2, code="ERCOT", tz="America/Chicago", demand_base_mw=61500, solar_peak_mw=12500, wind_base_mw=10500,
        queue_projects=194, state="TX", counties=("Travis", "Lubbock", "Harris", "Nueces")),
    Iso(id=3, code="ISONE", tz="America/New_York", demand_base_mw=14700, solar_peak_mw=2300, wind_base_mw=2700,
        queue_projects=106, state="MA", counties=("Suffolk", "Worcester", "Essex", "Bristol")),
    Iso(id=4, code="MISO", tz="EST", demand_base_mw=64800, solar_peak_mw=8700, wind_base_mw=15600,
        queue_projects=178, state="IL", counties=("Cook", "Will", "Lake", "DuPage")),
    Iso(id=5, code="NYISO", tz="America/New_York", demand_base_mw=18300, solar_peak_mw=3200, wind_base_mw=2900,
        queue_projects=120, state="NY", counties=("Kings", "Queens", "Erie", "Monroe")),
    Iso(id=6, code="PJM", tz="America/New_York", demand_base_mw=81000, solar_peak_mw=9800, wind_base_mw=10100,
        queue_projects=220, state="PA", counties=("Allegheny", "Bucks", "Berks", "York")),
    Iso(id=7, code="SPP", tz="America/Chicago", demand_base_mw=39400, solar_peak_mw=5400, wind_base_mw=13800,
        queue_projects=148, state="OK", counties=("Oklahoma", "Tulsa", "Cleveland", "Canadian")),
)
ISO_IDS = {iso.code: iso.id for iso in ISOS}

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
FUEL_IDS = {code: i for i, code in enumerate(FUELS, 1)}
QUEUE_STATUSES = {
    "active": "Active: in study, agreement or construction",
    "withdrawn": "Withdrawn, cancelled, terminated or retracted",
    "completed": "Completed / in service",
    "suspended": "Suspended",
    "unknown": "Status not reported",
}

def _series(iso: Iso, start: pd.Timestamp, end: pd.Timestamp, freq: str) -> products.Series:
    """Interval keys at freq ("h" or "5min") covering local dates start..end on the ISO's clock, with the
    demand and per-fuel MW shapes over them. Both cadences evaluate the same formulas on local time."""
    first = start.tz_localize(iso.tz).tz_convert("UTC")
    stop = (end + pd.DateOffset(days=1)).tz_localize(iso.tz).tz_convert("UTC")
    utc = pd.date_range(first, stop, freq=freq, inclusive="left")
    local = utc.tz_convert(iso.tz).tz_localize(None)
    hour = local.hour.to_numpy() + local.minute.to_numpy() / 60  # fractional within the hour at 5-minute cadence
    day, phase = local.dayofyear.to_numpy(), (SEED % 1009) / 1009
    keys = pd.DataFrame({
        "iso_id": iso.id, "interval_start_utc": utc.tz_localize(None), "interval_start_local": local,
    })

    # growth per year, weekend dip, late-July seasonal peak, afternoon daily peak, day-to-day wobble
    demand = iso.demand_base_mw * (1 + 0.02 * (local.year.to_numpy() - 2025)) * (
        1 - 0.045 * (local.dayofweek.to_numpy() >= 5)) * (
        1 + 0.08 * np.cos(2 * np.pi * (day - 205) / 365)) * (
        1 + 0.11 * np.sin(2 * np.pi * (hour - 8) / 24) + 0.025 * np.sin(day * 0.41 + phase)
    )
    # daylight-only arc peaking at noon, growing yearly, strongest near the June solstice
    solar = iso.solar_peak_mw * (1 + 0.07 * (local.year.to_numpy() - 2025)) * (
        np.maximum(0, np.sin(np.pi * (hour - 6) / 12))) * (1 + 0.12 * np.cos(2 * np.pi * (day - 172) / 365))
    wind = iso.wind_base_mw * (0.85 + 0.28 * np.sin(day * 0.19 + hour * 0.17 + phase))
    fuels = {
        "natural_gas": demand * 0.32, "coal": demand * 0.08, "nuclear": demand * 0.13, "hydro": demand * 0.09,
        "wind": wind, "solar": solar,
        # oscillates on the row position, so values depend on where the window starts (kept to match the submission)
        "battery": 0.018 * demand * np.sin(np.arange(len(keys)) * 0.24 + phase),
    }
    return products.Series(keys, demand, fuels)


def _generation(keys: pd.DataFrame, fuels: dict) -> pd.DataFrame:
    """One row per interval and fuel."""
    return pd.concat(
        [keys.assign(fuel_id=FUEL_IDS[fuel], generation_mw=np.round(mw, 2)) for fuel, mw in fuels.items()],
        ignore_index=True,
    )


def hourly(iso: Iso, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Balance and generation-by-fuel rows for every UTC hour covering local dates start..end."""
    series = _series(iso, start, end, "h")
    total = sum(np.round(mw, 2) for mw in series.fuels.values())
    balance = series.keys.assign(demand_mw=np.round(series.demand, 2),
                                 demand_forecast_mw=np.round(series.demand * 1.015, 2),
                                 net_generation_mw=np.round(total, 2))
    return {"core.fact_balance_hourly": balance, "core.fact_generation_hourly": _generation(series.keys, series.fuels)}


def five_minute(iso: Iso, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Load and generation-by-fuel rows for every five-minute interval covering local dates start..end.
    Load wobbles slightly around the demand shape, so it can differ a little from hourly demand."""
    series = _series(iso, start, end, "5min")
    keys = series.keys
    load = keys.assign(load_mw=np.round(series.demand * (1 + 0.006 * np.sin(np.arange(len(keys)) * 0.7)), 2))
    return {"core.fact_load_5min": load, "core.fact_generation_5min": _generation(keys, series.fuels)}


def queue(as_of: pd.Timestamp) -> pd.DataFrame:
    """Current projects per ISO. Fuel, status and dates cycle on the project index, so every rebuild matches."""
    fuels = ["solar", "battery", "wind", "natural_gas", "hydro", "nuclear", "other"]
    statuses = ["active", "active", "active", "withdrawn", "completed", "suspended"]
    raw_statuses = {
        "active": ("Active", "FIS In Progress", "IA Executed", "Under Construction", "Facility Study Stage"),
        "withdrawn": ("Withdrawn", "Canceled", "Terminated", "Deactivated"),
        "completed": ("In Service", "Completed", "Done"),
        "suspended": ("Suspended", "Pending Revision Approval"),
    }
    rows = []
    for iso in ISOS:
        for i in range(iso.queue_projects):
            fuel = fuels[(i * 3 + iso.id) % len(fuels)]
            status = statuses[(i * 5 + iso.id) % len(statuses)]
            entered = as_of.date() - timedelta(days=80 + (i * 31) % 1300)
            rows.append({
                "project_id": len(rows) + 1, "iso_id": iso.id, "queue_id": f"{iso.code}-{i + 1:04d}",
                "project_name": f"{iso.code} {fuel.replace('_', ' ').title()} {i + 1}",
                "developer": f"Example Energy {i % 17 + 1}", "county": iso.counties[(i + iso.id) % len(iso.counties)],
                "state": iso.state, "fuel_id": FUEL_IDS[fuel],
                "technology": {"solar": "Photovoltaic", "battery": "Battery Storage", "wind": "Wind",
                               "natural_gas": "Combined Cycle"}.get(fuel, fuel.title()),
                "status_code": status, "status_raw": raw_statuses[status][i % len(raw_statuses[status])],
                "capacity_mw": float(25 + (i * 37 + iso.id * 13) % 780),
                "is_hybrid": fuel in {"solar", "wind"} and i % 4 == 0,
                "queue_date": entered, "proposed_cod": entered + timedelta(days=730 + i % 400),
                "withdrawn_date": entered + timedelta(days=300) if status == "withdrawn" else None,
                "completed_date": entered + timedelta(days=600) if status == "completed" else None,
            })
    return pd.DataFrame(rows)


def schema_text() -> str:
    """Every CREATE TABLE: the hand-written schema.sql, then the generated per-ISO products."""
    return SCHEMA.read_text().rstrip() + "\n\n" + products.schema(ISO_IDS, FIVE_START, END) + "\n"


def _insert(con, table, frame):
    con.register("incoming", frame)
    con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM incoming")
    con.unregister("incoming")


def build() -> dict[str, int]:
    """Rebuild the warehouse from scratch; returns rows per table."""
    facts: dict[str, list[pd.DataFrame]] = {}
    for iso in ISOS:
        parts = {**hourly(iso, START, END),
                 **(five_minute(iso, FIVE_START, END) if iso.code in FIVE_MINUTE_ISOS else {})}
        parts |= products.frames(iso.code, products.Inputs(
            iso.id, iso.solar_peak_mw, FUEL_IDS, FIVE_START, END,
            _series(iso, FIVE_START, END, "h"), _series(iso, FIVE_START, END, "5min"),
        ))
        for table, frame in parts.items():
            facts.setdefault(table, []).append(frame)
    frames = {
        "core.dim_iso": pd.DataFrame([{"iso_id": iso.id, "iso_code": iso.code, "timezone": iso.tz} for iso in ISOS]),
        "core.dim_fuel": pd.DataFrame([
            {"fuel_id": FUEL_IDS[code], "fuel_code": code, "name": name, "category": category,
             "is_renewable": category == "renewable", "is_carbon_free": category in {"renewable", "nuclear"}}
            for code, (name, category) in FUELS.items()
        ]),
        "core.dim_queue_status": pd.DataFrame([
            {"status_code": code, "description": description} for code, description in QUEUE_STATUSES.items()
        ]),
        "core.dim_location": products.locations(ISO_IDS),
        **{table: pd.concat(parts, ignore_index=True) for table, parts in facts.items()},
        "core.queue_project": queue(END),
    }
    db_path = config.settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute(schema_text())
        for table, frame in frames.items():  # dimensions first, so foreign keys resolve
            _insert(con, table, frame)
    return {table: len(frame) for table, frame in frames.items()}


if __name__ == "__main__":
    for table, rows in build().items():
        print(f"{table}: {rows:,} rows")
