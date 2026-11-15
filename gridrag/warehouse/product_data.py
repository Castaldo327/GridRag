"""Deterministic synthetic rows for the per-ISO product tables.

These formulas create fictional analytical fixtures, not market observations or
physical simulations. Each generator returns a new frame and leaves its inputs
untouched. Table definitions and routing descriptions live in products.py.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IntervalSeries:
    """Aligned interval keys, demand, and generation by fuel at a single cadence.

    keys contains iso_id, interval_start_utc, and interval_start_local. Timestamps
    are timezone-naive; the UTC and ISO-local clocks are represented separately.
    Every MW array follows the row order of keys.
    """

    keys: pd.DataFrame
    demand_mw: np.ndarray
    generation_mw: Mapping[str, np.ndarray]


@dataclass(frozen=True)
class ProductInputs:
    """Shared inputs for one ISO, covering inclusive ISO-local dates start..end."""

    iso_id: int
    solar_peak_mw: float
    fuel_ids: Mapping[str, int]
    start: pd.Timestamp
    end: pd.Timestamp
    hourly: IntervalSeries
    five_minute: IntervalSeries


# Explicit offsets keep location IDs stable if the declarations are reordered.
# location_id = iso_id * 10 + offset, with one hub and three buses per ISO.
_LOCATION_ID_STRIDE = 10
_LOCATION_OFFSETS = {"BUS_A": 1, "BUS_B": 2, "BUS_C": 3, "HUB": 4}
_BUS_CODES = ("BUS_A", "BUS_B", "BUS_C")
_HUB_CODES = ("HUB",)


def _location_id(iso_id: int, location_code: str) -> int:
    return iso_id * _LOCATION_ID_STRIDE + _LOCATION_OFFSETS[location_code]


def locations(isos: Mapping[str, int]) -> pd.DataFrame:
    """Build the price-location dimension with the same IDs used by price rows."""
    return pd.DataFrame(
        [
            {
                "location_id": _location_id(iso_id, code),
                "iso_id": iso_id,
                "location_code": f"{iso}_{code}",
                "location_type": "hub" if code in _HUB_CODES else "bus",
            }
            for iso, iso_id in isos.items()
            for code in _LOCATION_OFFSETS
        ]
    )


def real_time_bus_prices(inputs: ProductInputs) -> pd.DataFrame:
    """Five-minute LMPs for each electrical bus."""
    return _prices(inputs, day_ahead=False, location_codes=_BUS_CODES)


def real_time_hub_prices(inputs: ProductInputs) -> pd.DataFrame:
    """Five-minute LMPs for the trading hub."""
    return _prices(inputs, day_ahead=False, location_codes=_HUB_CODES)


def day_ahead_hub_prices(inputs: ProductInputs) -> pd.DataFrame:
    """Hourly day-ahead LMPs for the trading hub."""
    return _prices(inputs, day_ahead=True, location_codes=_HUB_CODES)


def _prices(inputs: ProductInputs, *, day_ahead: bool, location_codes: tuple[str, ...]) -> pd.DataFrame:
    keys = inputs.hourly.keys if day_ahead else inputs.five_minute.keys
    hour = keys.interval_start_local.dt.hour.to_numpy()
    day = keys.interval_start_local.dt.day.to_numpy()
    congestion_variation = 0.8 if day_ahead else np.sin(np.arange(len(keys)) * 0.31)
    parts = []
    for code in location_codes:
        offset = _LOCATION_OFFSETS[code]
        frame = keys.copy()
        frame["location_id"] = _location_id(inputs.iso_id, code)
        # Daily energy arc, evening congestion, and a real-time wobble per interval.
        frame["energy"] = np.round(24 + inputs.iso_id * 1.3 + 8 * np.sin((hour - 9) * np.pi / 12) + day * 0.15, 2)
        frame["congestion"] = np.round(offset * 1.7 + (hour >= 17) * (4 + inputs.iso_id) + congestion_variation, 2)
        frame["loss"] = np.round(0.2 * offset + inputs.iso_id * 0.03, 2)
        frame["lmp"] = np.round(frame.energy + frame.congestion + frame.loss, 2)
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)


def load_forecasts(inputs: ProductInputs) -> pd.DataFrame:
    """Four vintages per hour, including a hindsight revision published after delivery.

    A historical forecast query must filter publish_time_utc by its cutoff before
    selecting the latest vintage. The final revision deliberately tests that rule.
    """
    keys = inputs.hourly.keys
    vintages = ((30, 0.04), (18, 0.018), (6, -0.012), (-1, 0.001))  # (hours before delivery, demand bias)
    parts = []
    for hours_before_delivery, bias in vintages:
        parts.append(
            keys.assign(
                publish_time_utc=keys.interval_start_utc - np.timedelta64(hours_before_delivery, "h"),
                forecast_mw=np.round(inputs.hourly.demand_mw * (1 + bias) + inputs.iso_id * 3, 2),
            )
        )
    return pd.concat(parts, ignore_index=True)


def ancillary_prices(inputs: ProductInputs) -> pd.DataFrame:
    """Hourly clearing prices for three reserve services."""
    keys = inputs.hourly.keys
    services = (("regulation_up", 1.8), ("regulation_down", 0.8), ("spinning_reserve", 1.2))
    price_shape = 2 + inputs.iso_id + np.maximum(0, np.sin(np.arange(len(keys)) * 0.2)) * 8
    return pd.concat(
        [
            keys.assign(service_code=service, clearing_price=np.round(scale * price_shape, 2))
            for service, scale in services
        ],
        ignore_index=True,
    )


def storage_dispatch(inputs: ProductInputs) -> pd.DataFrame:
    """Charge at midday and discharge in the evening; net output is positive when discharging.

    State of charge is an independent illustrative curve, not an energy balance
    integrated from these charge and discharge values.
    """
    keys = inputs.five_minute.keys
    peak_mw = inputs.solar_peak_mw
    hour = keys.interval_start_local.dt.hour.to_numpy()
    charging = (hour >= 10) & (hour < 15)
    discharging = (hour >= 17) & (hour < 21)
    frame = keys.assign(
        charge_mw=np.round(np.where(charging, peak_mw * 0.045, 0), 2),
        discharge_mw=np.round(np.where(discharging, peak_mw * 0.07, 0), 2),
    )
    frame["net_output_mw"] = frame.discharge_mw - frame.charge_mw
    frame["state_of_charge_mwh"] = np.round(peak_mw * (0.12 + 0.05 * np.sin((hour - 9) * np.pi / 12)), 2)
    return frame


def resource_outages(inputs: ProductInputs) -> pd.DataFrame:
    """Daily unavailable MW for each fuel and planned/forced outage type."""
    fuels = ("natural_gas", "nuclear", "battery")
    outage_types = ("planned", "forced")
    rows = []
    for day in pd.date_range(inputs.start, inputs.end):
        for fuel_index, fuel in enumerate(fuels):
            for outage_index, outage_type in enumerate(outage_types):
                rows.append(
                    {
                        "iso_id": inputs.iso_id,
                        "market_date": day.date(),
                        "fuel_id": inputs.fuel_ids[fuel],
                        "outage_type": outage_type,
                        "unavailable_mw": float(35 * inputs.iso_id + day.day * 2 + fuel_index * 17 + outage_index * 43),
                    }
                )
    return pd.DataFrame(rows)


def renewable_curtailment(inputs: ProductInputs) -> pd.DataFrame:
    """Curtailed MW as a small share of solar and wind generation at each interval."""
    keys = inputs.five_minute.keys
    curtailed_share = 0.018 + 0.002 * inputs.iso_id
    return pd.concat(
        [
            keys.assign(
                fuel_id=inputs.fuel_ids[fuel],
                curtailed_mw=np.round(inputs.five_minute.generation_mw[fuel] * curtailed_share, 2),
            )
            for fuel in ("solar", "wind")
        ],
        ignore_index=True,
    )
