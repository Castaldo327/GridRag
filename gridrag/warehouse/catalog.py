"""Load the built warehouse's schema metadata and approved ISO vocabulary."""

import duckdb

from gridrag import config
from gridrag.catalog import Catalog, DimensionValue, read_catalog
from gridrag.warehouse import fixtures

ISO_ENTITIES = (
    DimensionValue("core.dim_iso", "iso_code", "CAISO", ("California", "California ISO", "CAISO")),
    DimensionValue("core.dim_iso", "iso_code", "ERCOT", ("Texas", "ERCOT")),
    DimensionValue("core.dim_iso", "iso_code", "ISONE", ("New England", "ISO New England", "ISO-NE", "ISONE")),
    DimensionValue("core.dim_iso", "iso_code", "MISO", ("Midcontinent", "Midcontinent ISO", "MISO")),
    DimensionValue("core.dim_iso", "iso_code", "NYISO", ("New York", "New York ISO", "NYISO")),
    DimensionValue("core.dim_iso", "iso_code", "PJM", ("PJM",)),
    DimensionValue("core.dim_iso", "iso_code", "SPP", ("Southwest Power Pool", "SPP")),
)


def load_catalog() -> Catalog:
    """Read documented metadata from the built warehouse without loading its rows."""
    settings = config.settings
    path = settings.db_path
    if not path.exists():
        raise FileNotFoundError(f"warehouse missing: {path}; run python -m gridrag.warehouse.build")
    with duckdb.connect(str(path), read_only=True, config=settings.db_connection_config) as connection:
        catalog = read_catalog(connection, schemas=("core",), vocabulary=ISO_ENTITIES, isos=fixtures.ISO_IDS)
    if not any(table.description for table in catalog.tables.values()):
        raise ValueError("Warehouse descriptions are missing; rebuild with python -m gridrag.warehouse.build")
    return catalog
