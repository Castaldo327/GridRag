"""Per-ISO source products: one table per ISO and product (prices, load-forecast vintages, ancillary prices,
storage dispatch, outages, curtailment), with distinct markets, grains and time semantics.

Similar products are intentional analytical alternatives (bus vs hub, real-time vs day-ahead, forecast vs
actual, reserve vs energy price, observed storage vs proposed queue capacity), not copies.
Each product defines its columns, the comments routing reads and the generator that fills its tables, so a
table's DDL and rows come from one definition. Routing scores each product once, as a family of per-ISO tables.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Series:
    """Interval keys for one ISO at one cadence, with the builder's demand and per-fuel MW shapes over them."""

    keys: pd.DataFrame
    demand: np.ndarray
    fuels: dict[str, np.ndarray]


@dataclass(frozen=True)
class Inputs:
    """What a product's generator draws on for one ISO. Both series cover local dates start..end, so products
    line up with the observed facts for the same intervals."""

    iso_id: int
    solar_peak_mw: float
    fuel_ids: Mapping[str, int]
    start: pd.Timestamp
    end: pd.Timestamp
    hourly: Series
    five: Series


@dataclass(frozen=True)
class Product:
    suffix: str  # table name after the ISO prefix
    description: str
    columns: tuple[tuple[str, str, str], ...]  # (name, type, comment) after iso_id
    keys: tuple[str, ...]
    generate: Callable[[Inputs], pd.DataFrame]  # one ISO's rows


UTC = ("interval_start_utc", "TIMESTAMP", "delivery interval start, UTC; join time series on this and iso_id")
LOCAL = ("interval_start_local", "TIMESTAMP", "delivery interval start on the ISO clock; calendar filters use this")
LOCATION = ("location_id", "INTEGER", "price location in core.dim_location; bus and hub grains differ")
PRICE = (
    ("lmp", "DOUBLE", "total locational marginal price, USD/MWh; equals energy + congestion + loss"),
    ("energy", "DOUBLE", "energy price component, USD/MWh"),
    ("congestion", "DOUBLE", "congestion price component, USD/MWh"),
    ("loss", "DOUBLE", "marginal-loss price component, USD/MWh"),
)
REFERENCES = {"location_id": "core.dim_location (location_id)", "fuel_id": "core.dim_fuel (fuel_id)"}
BUSES, HUBS = ("BUS_A", "BUS_B", "BUS_C"), ("HUB",)
LOCATIONS = BUSES + HUBS  # location_id = iso_id * 10 + position (1-based)


def _prices(inputs: Inputs, *, day_ahead: bool, labels: tuple[str, ...]) -> pd.DataFrame:
    """LMPs at the labelled locations, on the hourly clock for day-ahead and the five-minute clock for real-time."""
    base = inputs.hourly.keys if day_ahead else inputs.five.keys
    parts = []
    for location in (LOCATIONS.index(label) + 1 for label in labels):
        frame = base.copy()
        hour = frame.interval_start_local.dt.hour.to_numpy()
        day = frame.interval_start_local.dt.day.to_numpy()
        frame["location_id"] = inputs.iso_id * 10 + location
        # daily price arc plus a slow drift; evening congestion; real-time congestion wobbles per interval
        frame["energy"] = np.round(24 + inputs.iso_id * 1.3 + 8 * np.sin((hour - 9) * np.pi / 12) + day * 0.15, 2)
        frame["congestion"] = np.round(
            location * 1.7 + (hour >= 17) * (4 + inputs.iso_id)
            + (0.8 if day_ahead else np.sin(np.arange(len(base)) * 0.31)), 2,
        )
        frame["loss"] = np.round(0.2 * location + inputs.iso_id * 0.03, 2)
        frame["lmp"] = np.round(frame.energy + frame.congestion + frame.loss, 2)
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)


def _load_forecast(inputs: Inputs) -> pd.DataFrame:
    """Four vintages per delivery hour; the last one is published an hour AFTER delivery (hindsight)."""
    keys = inputs.hourly.keys
    return pd.concat([
        keys.assign(
            publish_time_utc=keys.interval_start_utc - pd.Timedelta(hours=hours_before),
            forecast_mw=np.round(inputs.hourly.demand * (1 + bias) + inputs.iso_id * 3, 2),
        )
        for hours_before, bias in ((30, 0.04), (18, 0.018), (6, -0.012), (-1, 0.001))
    ], ignore_index=True)


def _ancillary_prices(inputs: Inputs) -> pd.DataFrame:
    keys = inputs.hourly.keys
    return pd.concat([
        keys.assign(service_code=service, clearing_price=np.round(
            scale * (2 + inputs.iso_id + np.maximum(0, np.sin(np.arange(len(keys)) * 0.2)) * 8), 2))
        for service, scale in (("regulation_up", 1.8), ("regulation_down", 0.8), ("spinning_reserve", 1.2))
    ], ignore_index=True)


def _storage_dispatch(inputs: Inputs) -> pd.DataFrame:
    """Charge through the solar midday, discharge into the evening peak."""
    keys, peak = inputs.five.keys, inputs.solar_peak_mw
    hour = keys.interval_start_local.dt.hour.to_numpy()
    frame = keys.assign(
        charge_mw=np.round(np.where((hour >= 10) & (hour < 15), peak * 0.045, 0), 2),
        discharge_mw=np.round(np.where((hour >= 17) & (hour < 21), peak * 0.07, 0), 2),
    )
    frame["net_output_mw"] = frame.discharge_mw - frame.charge_mw
    frame["state_of_charge_mwh"] = np.round(peak * (0.12 + 0.05 * np.sin((hour - 9) * np.pi / 12)), 2)
    return frame


def _resource_outages(inputs: Inputs) -> pd.DataFrame:
    return pd.DataFrame([
        {"iso_id": inputs.iso_id, "market_date": day.date(), "fuel_id": inputs.fuel_ids[fuel], "outage_type": kind,
         "unavailable_mw": float(35 * inputs.iso_id + day.day * 2 + j * 17 + k * 43)}
        for day in pd.date_range(inputs.start, inputs.end)
        for j, fuel in enumerate(("natural_gas", "nuclear", "battery"))
        for k, kind in enumerate(("planned", "forced"))
    ])


def _curtailment(inputs: Inputs) -> pd.DataFrame:
    """A small share of solar and wind output."""
    keys = inputs.five.keys
    return pd.concat([
        keys.assign(fuel_id=inputs.fuel_ids[fuel],
                    curtailed_mw=np.round(inputs.five.fuels[fuel] * (0.018 + 0.002 * inputs.iso_id), 2))
        for fuel in ("solar", "wind")
    ], ignore_index=True)


PRODUCTS = (
    Product("lmp_rt_bus_5min",
            "Real-time five-minute LMPs at individual electrical buses; NOT hub prices or day-ahead prices.",
            (UTC, LOCAL, LOCATION, *PRICE), ("iso_id", "interval_start_utc", "location_id"),
            partial(_prices, day_ahead=False, labels=BUSES)),
    Product("lmp_rt_hub_5min",
            "Real-time five-minute trading-HUB LMPs; NOT bus prices or day-ahead prices.",
            (UTC, LOCAL, LOCATION, *PRICE), ("iso_id", "interval_start_utc", "location_id"),
            partial(_prices, day_ahead=False, labels=HUBS)),
    Product("lmp_da_hub_hourly",
            "Day-ahead hourly trading-HUB LMPs; compare against hourly averages of real-time hub prices.",
            (UTC, LOCAL, LOCATION, *PRICE), ("iso_id", "interval_start_utc", "location_id"),
            partial(_prices, day_ahead=True, labels=HUBS)),
    Product("load_forecast_hourly",
            "Hourly LOAD forecast vintages; multiple publication times per delivery hour. Not actual demand. "
            "Select the latest publication AT OR BEFORE the requested cutoff.",
            (UTC, LOCAL,
             ("publish_time_utc", "TIMESTAMP", "when this forecast became known, UTC; apply a cutoff before ranking"),
             ("forecast_mw", "DOUBLE", "forecast demand for the delivery hour, MW; never actual observed demand")),
            ("iso_id", "interval_start_utc", "publish_time_utc"), _load_forecast),
    Product("ancillary_prices_hourly",
            "Hourly ancillary service clearing prices by reserve product (regulation_up, regulation_down, "
            "spinning_reserve); NOT energy LMPs.",
            (UTC, LOCAL,
             ("service_code", "VARCHAR", "regulation_up, regulation_down or spinning_reserve"),
             ("clearing_price", "DOUBLE", "ancillary service clearing price, USD/MW-hour")),
            ("iso_id", "interval_start_utc", "service_code"), _ancillary_prices),
    Product("storage_dispatch_5min",
            "Observed five-minute battery dispatch and state of charge; positive charge/discharge magnitudes. "
            "Not proposed queue capacity or generation by fuel.",
            (UTC, LOCAL,
             ("charge_mw", "DOUBLE", "power entering batteries, positive MW"),
             ("discharge_mw", "DOUBLE", "power leaving batteries, positive MW"),
             ("net_output_mw", "DOUBLE", "discharge_mw minus charge_mw; negative while charging"),
             ("state_of_charge_mwh", "DOUBLE", "stored energy at interval start, MWh; not power or proposed capacity")),
            ("iso_id", "interval_start_utc"), _storage_dispatch),
    Product("resource_outage_daily",
            "Daily unavailable resource capacity by fuel and planned/forced outage type; neither demand nor "
            "interconnection queue status.",
            (("market_date", "DATE", "ISO-local calendar day"),
             ("fuel_id", "SMALLINT", "fuel in core.dim_fuel"),
             ("outage_type", "VARCHAR", "planned or forced; both are unavailable resource capacity"),
             ("unavailable_mw", "DOUBLE", "resource capacity unavailable during the day, MW; not lost energy")),
            ("iso_id", "market_date", "fuel_id", "outage_type"), _resource_outages),
    Product("renewable_curtailment_5min",
            "Five-minute curtailed solar/wind POWER, distinct from generated output or forecast production. "
            "Integrate MW/12 to MWh.",
            (UTC, LOCAL,
             ("fuel_id", "SMALLINT", "solar or wind, in core.dim_fuel"),
             ("curtailed_mw", "DOUBLE", "renewable output curtailed, MW; not actual generation")),
            ("iso_id", "interval_start_utc", "fuel_id"), _curtailment),
)


def table_name(iso: str, product: Product) -> str:
    return f"core.{iso.lower()}_{product.suffix}"


def _create(product: Product, scope: str, name: str, iso_check: str) -> str:
    """A CREATE TABLE in schema.sql's style: table comment above, column comments inline."""
    lines = [
        f"-- {scope} {product.description}",
        f"CREATE TABLE {name} (",
        f"    iso_id SMALLINT NOT NULL REFERENCES core.dim_iso (iso_id){iso_check},",
    ]
    for column, dtype, comment in product.columns:
        reference = f" REFERENCES {REFERENCES[column]}" if column in REFERENCES else ""
        lines.append(f"    {column} {dtype} NOT NULL{reference},  -- {comment}")
    lines += [f"    PRIMARY KEY ({', '.join(product.keys)})", ");"]
    return "\n".join(lines)


def schema(isos: Mapping[str, int], start: pd.Timestamp, end: pd.Timestamp) -> str:
    """Every product's CREATE TABLE for each ISO (code -> iso_id), pinned to that ISO by a CHECK."""
    return "\n\n".join(
        _create(product, f"{iso} only, local dates {start:%Y-%m-%d} through {end:%Y-%m-%d}.",
                table_name(iso, product), f" CHECK (iso_id = {iso_id})")
        for iso, iso_id in isos.items()
        for product in PRODUCTS
    )


def family_ddl(product: Product, isos: Sequence[str], start: pd.Timestamp, end: pd.Timestamp) -> str:
    """The definition routing reads for a product: the same columns, with the ISO left open."""
    return _create(product, f"One table per ISO ({', '.join(isos)}), local dates {start:%Y-%m-%d} through "
                   f"{end:%Y-%m-%d}.", f"core.<iso>_{product.suffix}", "")


def locations(isos: Mapping[str, int]) -> pd.DataFrame:
    return pd.DataFrame([
        {"location_id": iso_id * 10 + index, "iso_id": iso_id, "location_code": f"{iso}_{label}",
         "location_type": "hub" if label in HUBS else "bus"}
        for iso, iso_id in isos.items()
        for index, label in enumerate(LOCATIONS, 1)
    ])


def frames(iso: str, inputs: Inputs) -> dict[str, pd.DataFrame]:
    """Rows for every product of one ISO, by table name."""
    return {table_name(iso, product): product.generate(inputs) for product in PRODUCTS}
