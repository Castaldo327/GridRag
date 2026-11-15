"""Table catalog and SQL schema for the fictional per-ISO products.

Start at PRODUCTS to see each table's columns, primary key, and row generator.
Descriptions are persisted as database comments for routing: they distinguish
similar products by market, grain, and time semantics. Keep them precise.
Synthetic data formulas and their inputs live in product_data.py.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pandas as pd

from gridrag.warehouse import product_data


@dataclass(frozen=True)
class Column:
    """A required table column, including its retrieval comment and optional foreign key."""

    name: str
    sql_type: str
    description: str
    references: str | None = None


@dataclass(frozen=True)
class Product:
    """One table template. iso_id is implicit; all other columns are declared here."""

    suffix: str
    description: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    generate: Callable[[product_data.ProductInputs], pd.DataFrame]
    routing_tags: tuple[str, ...]


INTERVAL_START_UTC = Column(
    "interval_start_utc", "TIMESTAMP", "delivery interval start, UTC; join time series on this and iso_id"
)
INTERVAL_START_LOCAL = Column(
    "interval_start_local", "TIMESTAMP", "delivery interval start on the ISO clock; calendar filters use this"
)
LOCATION_ID = Column(
    "location_id",
    "INTEGER",
    "price location in core.dim_location; bus and hub grains differ",
    references="core.dim_location (location_id)",
)
PRICE_COLUMNS = (
    Column("lmp", "DOUBLE", "total locational marginal price, USD/MWh; equals energy + congestion + loss"),
    Column("energy", "DOUBLE", "energy price component, USD/MWh"),
    Column("congestion", "DOUBLE", "congestion price component, USD/MWh"),
    Column("loss", "DOUBLE", "marginal-loss price component, USD/MWh"),
)


PRODUCTS = (
    Product(
        suffix="lmp_rt_bus_5min",
        description="Real-time five-minute LMPs at individual electrical buses; NOT hub prices or day-ahead prices.",
        columns=(INTERVAL_START_UTC, INTERVAL_START_LOCAL, LOCATION_ID, *PRICE_COLUMNS),
        primary_key=("iso_id", "interval_start_utc", "location_id"),
        generate=product_data.real_time_bus_prices,
        routing_tags=("prices",),
    ),
    Product(
        suffix="lmp_rt_hub_5min",
        description="Real-time five-minute trading-HUB LMPs; NOT bus prices or day-ahead prices.",
        columns=(INTERVAL_START_UTC, INTERVAL_START_LOCAL, LOCATION_ID, *PRICE_COLUMNS),
        primary_key=("iso_id", "interval_start_utc", "location_id"),
        generate=product_data.real_time_hub_prices,
        routing_tags=("prices",),
    ),
    Product(
        suffix="lmp_da_hub_hourly",
        description="Day-ahead hourly trading-HUB LMPs; compare against hourly averages of real-time hub prices.",
        columns=(INTERVAL_START_UTC, INTERVAL_START_LOCAL, LOCATION_ID, *PRICE_COLUMNS),
        primary_key=("iso_id", "interval_start_utc", "location_id"),
        generate=product_data.day_ahead_hub_prices,
        routing_tags=("prices",),
    ),
    Product(
        suffix="load_forecast_hourly",
        description="Hourly LOAD forecast vintages; multiple publication times per delivery hour. Not actual demand. "
        "Select the latest publication AT OR BEFORE the requested cutoff.",
        columns=(
            INTERVAL_START_UTC,
            INTERVAL_START_LOCAL,
            Column(
                "publish_time_utc", "TIMESTAMP", "when this forecast became known, UTC; apply a cutoff before ranking"
            ),
            Column("forecast_mw", "DOUBLE", "forecast demand for the delivery hour, MW; never actual observed demand"),
        ),
        primary_key=("iso_id", "interval_start_utc", "publish_time_utc"),
        generate=product_data.load_forecasts,
        routing_tags=("load", "forecast"),
    ),
    Product(
        suffix="ancillary_prices_hourly",
        description="Hourly ancillary service clearing prices by reserve product (regulation_up, regulation_down, "
        "spinning_reserve); NOT energy LMPs.",
        columns=(
            INTERVAL_START_UTC,
            INTERVAL_START_LOCAL,
            Column("service_code", "VARCHAR", "regulation_up, regulation_down or spinning_reserve"),
            Column("clearing_price", "DOUBLE", "ancillary service clearing price, USD/MW-hour"),
        ),
        primary_key=("iso_id", "interval_start_utc", "service_code"),
        generate=product_data.ancillary_prices,
        routing_tags=("ancillary", "prices"),
    ),
    Product(
        suffix="storage_dispatch_5min",
        description="Observed five-minute battery dispatch and state of charge; positive charge/discharge magnitudes. "
        "Not proposed queue capacity or generation by fuel.",
        columns=(
            INTERVAL_START_UTC,
            INTERVAL_START_LOCAL,
            Column("charge_mw", "DOUBLE", "power entering batteries, positive MW"),
            Column("discharge_mw", "DOUBLE", "power leaving batteries, positive MW"),
            Column("net_output_mw", "DOUBLE", "discharge_mw minus charge_mw; negative while charging"),
            Column(
                "state_of_charge_mwh", "DOUBLE", "stored energy at interval start, MWh; not power or proposed capacity"
            ),
        ),
        primary_key=("iso_id", "interval_start_utc"),
        generate=product_data.storage_dispatch,
        routing_tags=("storage",),
    ),
    Product(
        suffix="resource_outage_daily",
        description="Daily unavailable resource capacity by fuel and planned/forced outage type; neither demand nor "
        "interconnection queue status.",
        columns=(
            Column("market_date", "DATE", "ISO-local calendar day"),
            Column("fuel_id", "SMALLINT", "fuel in core.dim_fuel", references="core.dim_fuel (fuel_id)"),
            Column("outage_type", "VARCHAR", "planned or forced; both are unavailable resource capacity"),
            Column("unavailable_mw", "DOUBLE", "resource capacity unavailable during the day, MW; not lost energy"),
        ),
        primary_key=("iso_id", "market_date", "fuel_id", "outage_type"),
        generate=product_data.resource_outages,
        routing_tags=("outages",),
    ),
    Product(
        suffix="renewable_curtailment_5min",
        description="Five-minute curtailed solar/wind POWER, distinct from generated output or forecast production. "
        "Integrate MW/12 to MWh.",
        columns=(
            INTERVAL_START_UTC,
            INTERVAL_START_LOCAL,
            Column("fuel_id", "SMALLINT", "solar or wind, in core.dim_fuel", references="core.dim_fuel (fuel_id)"),
            Column("curtailed_mw", "DOUBLE", "renewable output curtailed, MW; not actual generation"),
        ),
        primary_key=("iso_id", "interval_start_utc", "fuel_id"),
        generate=product_data.renewable_curtailment,
        routing_tags=("curtailment",),
    ),
)


def table_name(iso: str, product: Product) -> str:
    """Return the schema-qualified physical table name for an ISO product."""
    return f"core.{iso.lower()}_{product.suffix}"


def _create_table(product: Product, iso: str, iso_id: int, start: pd.Timestamp, end: pd.Timestamp) -> str:
    """Render one table with persisted routing documentation and an ISO constraint."""
    name = table_name(iso, product)
    description = f"{iso} only, local dates {start:%Y-%m-%d} through {end:%Y-%m-%d}. {product.description}"
    description += "\n@routing_tags: " + ", ".join(product.routing_tags)
    lines = [
        f"CREATE TABLE {name} (",
        f"    iso_id SMALLINT NOT NULL REFERENCES core.dim_iso (iso_id) CHECK (iso_id = {iso_id}),",
    ]
    for column in product.columns:
        reference = f" REFERENCES {column.references}" if column.references else ""
        lines.append(f"    {column.name} {column.sql_type} NOT NULL{reference},")
    lines += [f"    PRIMARY KEY ({', '.join(product.primary_key)})", ");"]
    literal = description.replace("'", "''")
    lines.append(f"COMMENT ON TABLE {name} IS '{literal}';")
    for column in product.columns:
        literal = column.description.replace("'", "''")
        lines.append(f"COMMENT ON COLUMN {name}.{column.name} IS '{literal}';")
    return "\n".join(lines)


def schema(isos: Mapping[str, int], start: pd.Timestamp, end: pd.Timestamp) -> str:
    """Create every product table for each ISO (code -> iso_id)."""
    return "\n\n".join(
        _create_table(product, iso, iso_id, start, end) for iso, iso_id in isos.items() for product in PRODUCTS
    )


def frames(iso: str, inputs: product_data.ProductInputs) -> dict[str, pd.DataFrame]:
    """Generate one ISO's product rows, indexed by physical table name."""
    return {table_name(iso, product): product.generate(inputs) for product in PRODUCTS}
