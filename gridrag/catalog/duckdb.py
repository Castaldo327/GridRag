"""Read a catalog from DuckDB's metadata functions; no SQL text is parsed here."""

from collections import defaultdict
from collections.abc import Collection, Iterable

import duckdb

from gridrag.catalog.models import Catalog, Column, Constraint, DimensionValue, Table

ROUTING_TAGS_PREFIX = "@routing_tags:"


def _table_documentation(comment: str | None) -> tuple[str, tuple[str, ...]]:
    """Separate authored routing labels from ordinary persisted documentation.

    DuckDB comments are the storage contract: one dedicated marker line contains
    comma-separated labels. Labels are metadata, so SQL prompts retain only the
    original table documentation. Untagged databases remain valid catalogs.
    """
    documentation, tags = [], []
    for line in (comment or "").splitlines():
        if line.startswith(ROUTING_TAGS_PREFIX):
            tags.extend(line[len(ROUTING_TAGS_PREFIX) :].split(","))
        else:
            documentation.append(line)
    return "\n".join(documentation).strip(), tuple(tags)


def read_catalog(
    connection: duckdb.DuckDBPyConnection,
    *,
    schemas: Collection[str],
    vocabulary: Iterable[DimensionValue] = (),
    isos: Iterable[str] = (),
) -> Catalog:
    """Snapshot persistent base tables in approved schemas of the current database.

    Views, temporary tables, internal objects, and attached databases are excluded.
    The caller owns the connection; the returned catalog has no live DB resources.
    """
    schemas = [schema.lower() for schema in schemas]
    tables = connection.execute(
        """SELECT schema_name, table_name, comment FROM duckdb_tables()
           WHERE database_name = current_database() AND lower(schema_name) IN (SELECT unnest(?))
             AND NOT internal AND NOT temporary
           ORDER BY schema_name, table_name""",
        [schemas],
    ).fetchall()
    columns = defaultdict(list)
    for schema, table, name, data_type, nullable, default, description, expression in connection.execute(
        """SELECT schema_name, table_name, column_name, data_type, is_nullable,
                  column_default, comment, generation_expression
           FROM duckdb_columns()
           WHERE database_name = current_database() AND lower(schema_name) IN (SELECT unnest(?))
             AND NOT internal
           ORDER BY schema_name, table_name, column_index""",
        [schemas],
    ).fetchall():
        columns[schema, table].append(Column(name, data_type, nullable, default, description or "", expression))
    constraints = defaultdict(list)
    for schema, table, kind, names, sql, referenced in connection.execute(
        """SELECT schema_name, table_name, constraint_type, constraint_column_names,
                  constraint_text, referenced_table
           FROM duckdb_constraints()
           WHERE database_name = current_database() AND lower(schema_name) IN (SELECT unnest(?))
             AND constraint_type <> 'NOT NULL'
           ORDER BY schema_name, table_name, constraint_index""",
        [schemas],
    ).fetchall():
        # DuckDB foreign keys are restricted to tables in the same schema.
        reference = f"{schema.lower()}.{referenced.lower()}" if referenced else None
        constraints[schema, table].append(Constraint(kind, tuple(name.lower() for name in names), sql, reference))
    snapshots = []
    for schema, table, comment in tables:
        description, tags = _table_documentation(comment)
        snapshots.append(
            Table(schema, table, tuple(columns[schema, table]), tuple(constraints[schema, table]), description, tags)
        )
    return Catalog.of(snapshots, vocabulary=vocabulary, isos=isos)
