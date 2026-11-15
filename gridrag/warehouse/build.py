"""Create and load the fictional DuckDB warehouse.

The build generates rows, creates the combined schema, and loads a temporary
snapshot. It closes the database before replacing the destination, so a failed
build leaves the previous snapshot intact.

    uv run python -m gridrag.warehouse.build

Fixture settings live in fixtures.py; row generation lives in synthetic.py and
product_data.py. Table definitions live in schema.sql and products.py.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pandas as pd

from gridrag import config
from gridrag.warehouse import fixtures, products, synthetic

SCHEMA = Path(__file__).with_name("schema.sql")


def schema_text() -> str:
    """Combine the shared schema with every per-ISO product table definition."""
    shared_schema = SCHEMA.read_text(encoding="utf-8").rstrip()
    product_schema = products.schema(fixtures.ISO_IDS, fixtures.RECENT_START, fixtures.END_DATE)
    return f"{shared_schema}\n\n{product_schema}\n"


def build() -> dict[str, int]:
    """Build the configured snapshot atomically and return row counts by table."""
    frames = synthetic.frames()
    database_path = config.settings.db_path
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix=".gridrag-build-", dir=database_path.parent) as directory:
        temporary_database = Path(directory) / database_path.name
        with duckdb.connect(str(temporary_database)) as connection:
            connection.execute(schema_text())
            for table, frame in frames.items():  # dimensions first, so foreign keys resolve
                _insert(connection, table, frame)
        temporary_database.replace(database_path)

    return {table: len(frame) for table, frame in frames.items()}


def _insert(connection: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame) -> None:
    """Load columns by name and always release the registered DataFrame."""
    connection.register("incoming", frame)
    try:
        connection.execute(f"INSERT INTO {table} BY NAME SELECT * FROM incoming")
    finally:
        connection.unregister("incoming")


if __name__ == "__main__":
    for table, rows in build().items():
        print(f"{table}: {rows:,} rows")
