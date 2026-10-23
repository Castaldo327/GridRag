"""Per-ISO source products: one table per ISO and product, with distinct markets and location grains.

Similar products are intentional analytical alternatives (bus vs hub, real-time vs day-ahead), not copies.
Their DDL, with the comments routing reads, is generated here from the same definitions that fill them.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Product:
    suffix: str  # table name after the ISO prefix
    family: str  # routing family
    description: str
    columns: tuple[tuple[str, str, str], ...]  # (name, type, comment) after iso_id
    keys: tuple[str, ...]


UTC = ("interval_start_utc", "TIMESTAMP", "delivery interval start, UTC; join time series on this and iso_id")
LOCAL = ("interval_start_local", "TIMESTAMP", "delivery interval start on the ISO clock; calendar filters use this")
LOCATION = ("location_id", "INTEGER", "price location in core.dim_location; bus and hub grains differ")
PRICE = (
    ("lmp", "DOUBLE", "total locational marginal price, USD/MWh; equals energy + congestion + loss"),
    ("energy", "DOUBLE", "energy price component, USD/MWh"),
    ("congestion", "DOUBLE", "congestion price component, USD/MWh"),
    ("loss", "DOUBLE", "marginal-loss price component, USD/MWh"),
)
PRODUCTS = (
    Product("lmp_rt_bus_5min", "prices",
            "Real-time five-minute LMPs at individual electrical buses; NOT hub prices or day-ahead prices.",
            (UTC, LOCAL, LOCATION, *PRICE), ("iso_id", "interval_start_utc", "location_id")),
    Product("lmp_rt_hub_5min", "prices",
            "Real-time five-minute trading-HUB LMPs; NOT bus prices or day-ahead prices.",
            (UTC, LOCAL, LOCATION, *PRICE), ("iso_id", "interval_start_utc", "location_id")),
    Product("lmp_da_hub_hourly", "prices",
            "Day-ahead hourly trading-HUB LMPs; compare against hourly averages of real-time hub prices.",
            (UTC, LOCAL, LOCATION, *PRICE), ("iso_id", "interval_start_utc", "location_id")),
)
LOCATIONS = ("BUS_A", "BUS_B", "BUS_C", "HUB")  # location_id = iso_id * 10 + position (1-based)


def table_name(iso: str, product: Product) -> str:
    return f"core.{iso.lower()}_{product.suffix}"


def schema(isos: list[str], start: pd.Timestamp, end: pd.Timestamp) -> str:
    """CREATE TABLE blocks in schema.sql's style: table comment above, column comments inline."""
    blocks = []
    for iso_id, iso in enumerate(isos, 1):
        for product in PRODUCTS:
            lines = [
                f"-- {iso} only, local dates {start:%Y-%m-%d} through {end:%Y-%m-%d}. {product.description}",
                f"CREATE TABLE {table_name(iso, product)} (",
                f"    iso_id SMALLINT NOT NULL REFERENCES core.dim_iso (iso_id) CHECK (iso_id = {iso_id}),",
            ]
            for name, dtype, comment in product.columns:
                reference = " REFERENCES core.dim_location (location_id)" if name == "location_id" else ""
                lines.append(f"    {name} {dtype} NOT NULL{reference},  -- {comment}")
            lines += [f"    PRIMARY KEY ({', '.join(product.keys)})", ");"]
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def locations(isos: list[str]) -> pd.DataFrame:
    return pd.DataFrame([
        {"location_id": iso_id * 10 + index, "iso_id": iso_id, "location_code": f"{iso}_{label}",
         "location_type": "hub" if label == "HUB" else "bus"}
        for iso_id, iso in enumerate(isos, 1)
        for index, label in enumerate(LOCATIONS, 1)
    ])


def frames(iso: str, iso_id: int, hourly: pd.DataFrame, five: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Rows for every product of one ISO, from its hourly and five-minute interval keys."""
    out = {}
    for product in PRODUCTS:
        day_ahead = "da_" in product.suffix
        base = hourly if day_ahead else five
        parts = []
        for location in (4,) if "hub" in product.suffix else (1, 2, 3):
            frame = base.copy()
            hour = frame.interval_start_local.dt.hour.to_numpy()
            day = frame.interval_start_local.dt.day.to_numpy()
            frame["location_id"] = iso_id * 10 + location
            # daily price arc plus a slow drift; evening congestion; real-time congestion wobbles per interval
            frame["energy"] = np.round(24 + iso_id * 1.3 + 8 * np.sin((hour - 9) * np.pi / 12) + day * 0.15, 2)
            frame["congestion"] = np.round(
                location * 1.7 + (hour >= 17) * (4 + iso_id)
                + (0.8 if day_ahead else np.sin(np.arange(len(base)) * 0.31)), 2,
            )
            frame["loss"] = np.round(0.2 * location + iso_id * 0.03, 2)
            frame["lmp"] = np.round(frame.energy + frame.congestion + frame.loss, 2)
            parts.append(frame)
        out[table_name(iso, product)] = pd.concat(parts, ignore_index=True)
    return out
