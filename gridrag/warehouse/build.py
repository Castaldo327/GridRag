"""Build a small fictional warehouse: seven ISOs and their hourly demand.

    uv run python -m gridrag.warehouse.build
"""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gridrag.config import DB

SCHEMA = Path(__file__).with_name("schema.sql")
SEED = 20261023
START, END = pd.Timestamp("2025-01-01"), pd.Timestamp("2026-10-21")  

ISOS = {
    "CAISO": {"tz": "America/Los_Angeles", "demand_base_mw": 33500},
    "ERCOT": {"tz": "America/Chicago", "demand_base_mw": 61500},
    "ISONE": {"tz": "America/New_York", "demand_base_mw": 14700},
    "MISO": {"tz": "EST", "demand_base_mw": 64800},
    "NYISO": {"tz": "America/New_York", "demand_base_mw": 18300},
    "PJM": {"tz": "America/New_York", "demand_base_mw": 81000},
    "SPP": {"tz": "America/Chicago", "demand_base_mw": 39400},
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


def _insert(con, table, frame):
    con.register("incoming", frame)
    con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM incoming")
    con.unregister("incoming")


def build() -> dict[str, int]:
    """Rebuild the warehouse from scratch; returns rows per table."""
    isos = pd.DataFrame(
        [{"iso_id": i, "iso_code": code, "timezone": info["tz"]} for i, (code, info) in enumerate(ISOS.items(), 1)]
    )
    balance = pd.concat([hourly(iso, START, END) for iso in ISOS], ignore_index=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    with duckdb.connect(str(DB)) as con:
        con.execute(SCHEMA.read_text())
        _insert(con, "core.dim_iso", isos)
        _insert(con, "core.fact_balance_hourly", balance)
    return {"core.dim_iso": len(isos), "core.fact_balance_hourly": len(balance)}


if __name__ == "__main__":
    for table, rows in build().items():
        print(f"{table}: {rows:,} rows")
