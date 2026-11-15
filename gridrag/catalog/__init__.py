"""Public catalog API: DuckDB metadata, immutable snapshots, and approved vocabulary."""

from functools import cache

from gridrag.catalog.duckdb import read_catalog
from gridrag.catalog.models import Catalog, Column, Constraint, DimensionValue, Table, render_grounding

__all__ = [
    "Catalog",
    "Column",
    "Constraint",
    "DimensionValue",
    "Table",
    "demo_catalog",
    "read_catalog",
    "render_grounding",
]


@cache
def demo_catalog() -> Catalog:
    """Load the built fictional warehouse's metadata once per process."""
    from gridrag.warehouse.catalog import load_catalog

    return load_catalog()
