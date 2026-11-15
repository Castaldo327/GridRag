"""Fixed settings for the fictional warehouse.

Edit coverage dates, ISO profiles, fuel definitions, and queue statuses here.
Data formulas live in synthetic.py and product_data.py; database writes live in
build.py. ISO IDs are explicit to keep existing rows and locations stable.
"""

from dataclasses import dataclass

import pandas as pd

SEED = 20261023
HOURLY_START = pd.Timestamp("2025-01-01")
RECENT_START = pd.Timestamp("2026-10-15")
END_DATE = pd.Timestamp("2026-10-21")

# Shared five-minute facts cover two ISOs; per-ISO products cover all seven.
FIVE_MINUTE_FACT_ISOS = ("CAISO", "ERCOT")


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
    Iso(
        id=1,
        code="CAISO",
        tz="America/Los_Angeles",
        demand_base_mw=33500,
        solar_peak_mw=14500,
        wind_base_mw=4100,
        queue_projects=168,
        state="CA",
        counties=("Riverside", "Kern", "San Bernardino", "Imperial"),
    ),
    Iso(
        id=2,
        code="ERCOT",
        tz="America/Chicago",
        demand_base_mw=61500,
        solar_peak_mw=12500,
        wind_base_mw=10500,
        queue_projects=194,
        state="TX",
        counties=("Travis", "Lubbock", "Harris", "Nueces"),
    ),
    Iso(
        id=3,
        code="ISONE",
        tz="America/New_York",
        demand_base_mw=14700,
        solar_peak_mw=2300,
        wind_base_mw=2700,
        queue_projects=106,
        state="MA",
        counties=("Suffolk", "Worcester", "Essex", "Bristol"),
    ),
    Iso(
        id=4,
        code="MISO",
        tz="EST",
        demand_base_mw=64800,
        solar_peak_mw=8700,
        wind_base_mw=15600,
        queue_projects=178,
        state="IL",
        counties=("Cook", "Will", "Lake", "DuPage"),
    ),
    Iso(
        id=5,
        code="NYISO",
        tz="America/New_York",
        demand_base_mw=18300,
        solar_peak_mw=3200,
        wind_base_mw=2900,
        queue_projects=120,
        state="NY",
        counties=("Kings", "Queens", "Erie", "Monroe"),
    ),
    Iso(
        id=6,
        code="PJM",
        tz="America/New_York",
        demand_base_mw=81000,
        solar_peak_mw=9800,
        wind_base_mw=10100,
        queue_projects=220,
        state="PA",
        counties=("Allegheny", "Bucks", "Berks", "York"),
    ),
    Iso(
        id=7,
        code="SPP",
        tz="America/Chicago",
        demand_base_mw=39400,
        solar_peak_mw=5400,
        wind_base_mw=13800,
        queue_projects=148,
        state="OK",
        counties=("Oklahoma", "Tulsa", "Cleveland", "Canadian"),
    ),
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
