"""Generate fictional dimensions, demand, generation, and queue projects.

frames() assembles the complete warehouse as in-memory tables. Interval formulas
are shared with the per-ISO product generators to keep their inputs aligned.
Coverage and ISO profiles are defined in fixtures.py.
"""

from collections.abc import Mapping
from datetime import timedelta

import numpy as np
import pandas as pd

from gridrag.warehouse import fixtures, product_data, products


def interval_series(
    iso: fixtures.Iso, start: pd.Timestamp, end: pd.Timestamp, freq: str
) -> product_data.IntervalSeries:
    """Interval keys at freq ("h" or "5min") covering local dates start..end on the ISO's clock, with the
    demand and per-fuel MW shapes over them. Both cadences evaluate the same formulas on local time."""
    first = start.tz_localize(iso.tz).tz_convert("UTC")
    stop = (end + pd.DateOffset(days=1)).tz_localize(iso.tz).tz_convert("UTC")
    utc = pd.date_range(first, stop, freq=freq, inclusive="left")
    local = utc.tz_convert(iso.tz).tz_localize(None)
    hour = local.hour.to_numpy() + local.minute.to_numpy() / 60  # fractional within the hour at 5-minute cadence
    day, phase = local.dayofyear.to_numpy(), (fixtures.SEED % 1009) / 1009
    keys = pd.DataFrame(
        {
            "iso_id": iso.id,
            "interval_start_utc": utc.tz_localize(None),
            "interval_start_local": local,
        }
    )

    # growth per year, weekend dip, late-July seasonal peak, afternoon daily peak, day-to-day wobble
    demand = (
        iso.demand_base_mw
        * (1 + 0.02 * (local.year.to_numpy() - 2025))
        * (1 - 0.045 * (local.dayofweek.to_numpy() >= 5))
        * (1 + 0.08 * np.cos(2 * np.pi * (day - 205) / 365))
        * (1 + 0.11 * np.sin(2 * np.pi * (hour - 8) / 24) + 0.025 * np.sin(day * 0.41 + phase))
    )
    # daylight-only arc peaking at noon, growing yearly, strongest near the June solstice
    solar = (
        iso.solar_peak_mw
        * (1 + 0.07 * (local.year.to_numpy() - 2025))
        * (np.maximum(0, np.sin(np.pi * (hour - 6) / 12)))
        * (1 + 0.12 * np.cos(2 * np.pi * (day - 172) / 365))
    )
    wind = iso.wind_base_mw * (0.85 + 0.28 * np.sin(day * 0.19 + hour * 0.17 + phase))
    fuels = {
        "natural_gas": demand * 0.32,
        "coal": demand * 0.08,
        "nuclear": demand * 0.13,
        "hydro": demand * 0.09,
        "wind": wind,
        "solar": solar,
        # oscillates on the row position, so values depend on where the window starts (kept to match the submission)
        "battery": 0.018 * demand * np.sin(np.arange(len(keys)) * 0.24 + phase),
    }
    return product_data.IntervalSeries(keys=keys, demand_mw=demand, generation_mw=fuels)


def _generation(keys: pd.DataFrame, fuels: Mapping[str, np.ndarray]) -> pd.DataFrame:
    """One row per interval and fuel."""
    return pd.concat(
        [keys.assign(fuel_id=fixtures.FUEL_IDS[fuel], generation_mw=np.round(mw, 2)) for fuel, mw in fuels.items()],
        ignore_index=True,
    )


def hourly_facts(iso: fixtures.Iso, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Balance and generation-by-fuel rows for every UTC hour covering local dates start..end."""
    series = interval_series(iso, start, end, "h")
    total = sum(np.round(mw, 2) for mw in series.generation_mw.values())
    balance = series.keys.assign(
        demand_mw=np.round(series.demand_mw, 2),
        demand_forecast_mw=np.round(series.demand_mw * 1.015, 2),
        net_generation_mw=np.round(total, 2),
    )
    return {
        "core.fact_balance_hourly": balance,
        "core.fact_generation_hourly": _generation(series.keys, series.generation_mw),
    }


def five_minute_facts(iso: fixtures.Iso, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Load and generation-by-fuel rows for every five-minute interval covering local dates start..end.
    Load wobbles slightly around the demand shape, so it can differ a little from hourly demand."""
    series = interval_series(iso, start, end, "5min")
    keys = series.keys
    load = keys.assign(load_mw=np.round(series.demand_mw * (1 + 0.006 * np.sin(np.arange(len(keys)) * 0.7)), 2))
    return {"core.fact_load_5min": load, "core.fact_generation_5min": _generation(keys, series.generation_mw)}


def queue_projects(as_of: pd.Timestamp) -> pd.DataFrame:
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
    for iso in fixtures.ISOS:
        for index in range(iso.queue_projects):
            fuel = fuels[(index * 3 + iso.id) % len(fuels)]
            status = statuses[(index * 5 + iso.id) % len(statuses)]
            entered = as_of.date() - timedelta(days=80 + (index * 31) % 1300)
            rows.append(
                {
                    "project_id": len(rows) + 1,
                    "iso_id": iso.id,
                    "queue_id": f"{iso.code}-{index + 1:04d}",
                    "project_name": f"{iso.code} {fuel.replace('_', ' ').title()} {index + 1}",
                    "developer": f"Example Energy {index % 17 + 1}",
                    "county": iso.counties[(index + iso.id) % len(iso.counties)],
                    "state": iso.state,
                    "fuel_id": fixtures.FUEL_IDS[fuel],
                    "technology": {
                        "solar": "Photovoltaic",
                        "battery": "Battery Storage",
                        "wind": "Wind",
                        "natural_gas": "Combined Cycle",
                    }.get(fuel, fuel.title()),
                    "status_code": status,
                    "status_raw": raw_statuses[status][index % len(raw_statuses[status])],
                    "capacity_mw": float(25 + (index * 37 + iso.id * 13) % 780),
                    "is_hybrid": fuel in {"solar", "wind"} and index % 4 == 0,
                    "queue_date": entered,
                    "proposed_cod": entered + timedelta(days=730 + index % 400),
                    "withdrawn_date": entered + timedelta(days=300) if status == "withdrawn" else None,
                    "completed_date": entered + timedelta(days=600) if status == "completed" else None,
                }
            )
    return pd.DataFrame(rows)


def dimensions() -> dict[str, pd.DataFrame]:
    """Build the lookup tables referenced by the generated facts."""
    return {
        "core.dim_iso": pd.DataFrame(
            [{"iso_id": iso.id, "iso_code": iso.code, "timezone": iso.tz} for iso in fixtures.ISOS]
        ),
        "core.dim_fuel": pd.DataFrame(
            [
                {
                    "fuel_id": fixtures.FUEL_IDS[code],
                    "fuel_code": code,
                    "name": name,
                    "category": category,
                    "is_renewable": category == "renewable",
                    "is_carbon_free": category in {"renewable", "nuclear"},
                }
                for code, (name, category) in fixtures.FUELS.items()
            ]
        ),
        "core.dim_queue_status": pd.DataFrame(
            [{"status_code": code, "description": description} for code, description in fixtures.QUEUE_STATUSES.items()]
        ),
        "core.dim_location": product_data.locations(fixtures.ISO_IDS),
    }


def frames() -> dict[str, pd.DataFrame]:
    """Assemble every table's rows in load order: dimensions, facts, then queue.

    Hourly facts cover the full history. Five-minute facts cover the recent week
    for CAISO and ERCOT. Per-ISO products cover the recent week for every ISO.
    Generation is deterministic and does not open or write a database.
    """
    fact_parts: dict[str, list[pd.DataFrame]] = {}
    for iso in fixtures.ISOS:
        iso_frames = hourly_facts(iso, fixtures.HOURLY_START, fixtures.END_DATE)
        if iso.code in fixtures.FIVE_MINUTE_FACT_ISOS:
            iso_frames.update(five_minute_facts(iso, fixtures.RECENT_START, fixtures.END_DATE))

        product_inputs = product_data.ProductInputs(
            iso_id=iso.id,
            solar_peak_mw=iso.solar_peak_mw,
            fuel_ids=fixtures.FUEL_IDS,
            start=fixtures.RECENT_START,
            end=fixtures.END_DATE,
            hourly=interval_series(iso, fixtures.RECENT_START, fixtures.END_DATE, "h"),
            five_minute=interval_series(iso, fixtures.RECENT_START, fixtures.END_DATE, "5min"),
        )
        iso_frames.update(products.frames(iso.code, product_inputs))
        for table, frame in iso_frames.items():
            fact_parts.setdefault(table, []).append(frame)

    tables = dimensions()
    for table, parts in fact_parts.items():
        tables[table] = pd.concat(parts, ignore_index=True)
    tables["core.queue_project"] = queue_projects(fixtures.END_DATE)
    return tables
