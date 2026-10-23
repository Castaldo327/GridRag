"""Per-ISO source products: one table per ISO and product (prices, load-forecast vintages, ancillary prices,
storage dispatch, outages, curtailment), with distinct markets, grains and time semantics.

Similar products are intentional analytical alternatives (bus vs hub, real-time vs day-ahead, forecast vs
actual, reserve vs energy price, observed storage vs proposed queue capacity), not copies.
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
    Product("load_forecast_hourly", "forecasts",
            "Hourly LOAD forecast vintages; multiple publication times per delivery hour. Not actual demand. "
            "Select the latest publication AT OR BEFORE the requested cutoff.",
            (UTC, LOCAL,
             ("publish_time_utc", "TIMESTAMP", "when this forecast became known, UTC; apply a cutoff before ranking"),
             ("forecast_mw", "DOUBLE", "forecast demand for the delivery hour, MW; never actual observed demand")),
            ("iso_id", "interval_start_utc", "publish_time_utc")),
    Product("ancillary_prices_hourly", "ancillary",
            "Hourly ancillary service clearing prices by reserve product (regulation_up, regulation_down, "
            "spinning_reserve); NOT energy LMPs.",
            (UTC, LOCAL,
             ("service_code", "VARCHAR", "regulation_up, regulation_down or spinning_reserve"),
             ("clearing_price", "DOUBLE", "ancillary service clearing price, USD/MW-hour")),
            ("iso_id", "interval_start_utc", "service_code")),
    Product("storage_dispatch_5min", "storage",
            "Observed five-minute battery dispatch and state of charge; positive charge/discharge magnitudes. "
            "Not proposed queue capacity or generation by fuel.",
            (UTC, LOCAL,
             ("charge_mw", "DOUBLE", "power entering batteries, positive MW"),
             ("discharge_mw", "DOUBLE", "power leaving batteries, positive MW"),
             ("net_output_mw", "DOUBLE", "discharge_mw minus charge_mw; negative while charging"),
             ("state_of_charge_mwh", "DOUBLE", "stored energy at interval start, MWh; not power or proposed capacity")),
            ("iso_id", "interval_start_utc")),
    Product("resource_outage_daily", "outages",
            "Daily unavailable resource capacity by fuel and planned/forced outage type; neither demand nor "
            "interconnection queue status.",
            (("market_date", "DATE", "ISO-local calendar day"),
             ("fuel_id", "SMALLINT", "fuel in core.dim_fuel"),
             ("outage_type", "VARCHAR", "planned or forced; both are unavailable resource capacity"),
             ("unavailable_mw", "DOUBLE", "resource capacity unavailable during the day, MW; not lost energy")),
            ("iso_id", "market_date", "fuel_id", "outage_type")),
    Product("renewable_curtailment_5min", "curtailment",
            "Five-minute curtailed solar/wind POWER, distinct from generated output or forecast production. "
            "Integrate MW/12 to MWh.",
            (UTC, LOCAL,
             ("fuel_id", "SMALLINT", "solar or wind, in core.dim_fuel"),
             ("curtailed_mw", "DOUBLE", "renewable output curtailed, MW; not actual generation")),
            ("iso_id", "interval_start_utc", "fuel_id")),
)
REFERENCES = {"location_id": "core.dim_location (location_id)", "fuel_id": "core.dim_fuel (fuel_id)"}
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
                reference = f" REFERENCES {REFERENCES[name]}" if name in REFERENCES else ""
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


def _prices(product: Product, iso_id: int, hourly: pd.DataFrame, five: pd.DataFrame) -> pd.DataFrame:
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
    return pd.concat(parts, ignore_index=True)


def frames(iso: str, iso_id: int, solar_peak_mw: int, fuel_ids: dict[str, int], start: pd.Timestamp,
           end: pd.Timestamp, hourly: tuple, five: tuple) -> dict[str, pd.DataFrame]:
    """Rows for every product of one ISO. hourly and five are (keys, demand, fuels) from the builder's series
    over start..end, so products line up with the observed facts for the same intervals."""
    (hourly_keys, hourly_demand, _), (five_keys, _, five_fuels) = hourly, five
    out = {}
    for product in PRODUCTS:
        suffix = product.suffix
        if suffix.startswith("lmp_"):
            frame = _prices(product, iso_id, hourly_keys, five_keys)
        elif suffix == "load_forecast_hourly":
            # four vintages per delivery hour; the last one is published an hour AFTER delivery (hindsight)
            frame = pd.concat([
                hourly_keys.assign(
                    publish_time_utc=hourly_keys.interval_start_utc - pd.Timedelta(hours=hours_before),
                    forecast_mw=np.round(hourly_demand * (1 + bias) + iso_id * 3, 2),
                )
                for hours_before, bias in ((30, 0.04), (18, 0.018), (6, -0.012), (-1, 0.001))
            ], ignore_index=True)
        elif suffix == "ancillary_prices_hourly":
            frame = pd.concat([
                hourly_keys.assign(service_code=service, clearing_price=np.round(
                    scale * (2 + iso_id + np.maximum(0, np.sin(np.arange(len(hourly_keys)) * 0.2)) * 8), 2))
                for service, scale in (("regulation_up", 1.8), ("regulation_down", 0.8), ("spinning_reserve", 1.2))
            ], ignore_index=True)
        elif suffix == "storage_dispatch_5min":
            # charge through the solar midday, discharge into the evening peak
            hour = five_keys.interval_start_local.dt.hour.to_numpy()
            frame = five_keys.assign(
                charge_mw=np.round(np.where((hour >= 10) & (hour < 15), solar_peak_mw * 0.045, 0), 2),
                discharge_mw=np.round(np.where((hour >= 17) & (hour < 21), solar_peak_mw * 0.07, 0), 2),
            )
            frame["net_output_mw"] = frame.discharge_mw - frame.charge_mw
            frame["state_of_charge_mwh"] = np.round(solar_peak_mw * (0.12 + 0.05 * np.sin((hour - 9) * np.pi / 12)), 2)
        elif suffix == "resource_outage_daily":
            frame = pd.DataFrame([
                {"iso_id": iso_id, "market_date": day.date(), "fuel_id": fuel_ids[fuel], "outage_type": kind,
                 "unavailable_mw": float(35 * iso_id + day.day * 2 + j * 17 + k * 43)}
                for day in pd.date_range(start, end)
                for j, fuel in enumerate(("natural_gas", "nuclear", "battery"))
                for k, kind in enumerate(("planned", "forced"))
            ])
        else:  # renewable_curtailment_5min: a small share of solar and wind output
            frame = pd.concat([
                five_keys.assign(fuel_id=fuel_ids[fuel], curtailed_mw=np.round(five_fuels[fuel] * (0.018 + 0.002 * iso_id), 2))
                for fuel in ("solar", "wind")
            ], ignore_index=True)
        out[table_name(iso, product)] = frame
    return out
