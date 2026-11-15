"""DuckDB metadata snapshots and the schema excerpts used for column routing."""

import tempfile
import unittest
from dataclasses import replace
from graphlib import TopologicalSorter
from pathlib import Path
from unittest.mock import patch

import duckdb

from gridrag import config
from gridrag.catalog import Catalog, Column, Constraint, Table, demo_catalog, read_catalog
from gridrag.sql import db
from gridrag.warehouse import catalog as warehouse_catalog
from gridrag.warehouse import fixtures, products


class CatalogTests(unittest.TestCase):
    def test_demo_catalog_includes_every_region_and_physical_table(self):
        catalog = demo_catalog()
        self.assertEqual(len(catalog.tables), 65)
        self.assertEqual(catalog.isos, ("CAISO", "ERCOT", "ISONE", "MISO", "NYISO", "PJM", "SPP"))
        self.assertEqual(catalog.tables["core.ercot_lmp_rt_hub_5min"].references, {"core.dim_iso", "core.dim_location"})
        self.assertIs(demo_catalog(), catalog)

    def test_product_documentation_is_persisted_for_every_iso(self):
        catalog = demo_catalog()
        for iso in fixtures.ISOS:
            for product in products.PRODUCTS:
                with self.subTest(iso=iso.code, product=product.suffix):
                    table = catalog.tables[products.table_name(iso.code, product)]
                    self.assertIn(product.description, table.description)
                    self.assertIn(f"{iso.code} only", table.description)
                    self.assertIn("2026-10-15 through 2026-10-21", table.description)
                    descriptions = {column.name: column.description for column in table.column_metadata}
                    for column in product.columns:
                        self.assertEqual(descriptions[column.name], column.description)

    def test_every_demo_schema_is_executable_and_preserves_structural_metadata(self):
        tables = demo_catalog().tables
        order = TopologicalSorter({name: table.references - {name} for name, table in tables.items()}).static_order()
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            for name in order:
                with self.subTest(table=name):
                    connection.execute(tables[name].ddl)
            restored = read_catalog(connection, schemas=("core",))
        for name, table in tables.items():
            with self.subTest(table=name):
                self.assertEqual(list(restored.tables[name].columns), list(table.columns))
                self.assertEqual(restored.tables[name].references, table.references)
                self.assertEqual(restored.tables[name].structural_columns, table.structural_columns)

    def test_column_excerpts_preserve_documentation_and_skip_unselected_measures(self):
        table = demo_catalog().tables["core.fact_balance_hourly"]
        self.assertIn("demand (load), MW", table.columns["demand_mw"])
        excerpt = table.selected_schema(["iso_id", "interval_start_utc", "demand_mw"])
        self.assertIn("Primary key", excerpt)
        self.assertIn("demand (load), MW", excerpt)
        self.assertIn("Aggregate balance and fuel generation separately", excerpt)
        self.assertNotIn("net_generation_mw", excerpt)
        self.assertNotIn("demand_forecast_mw", excerpt)
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            connection.execute(demo_catalog().tables["core.dim_iso"].ddl)
            connection.execute(excerpt)

    def test_keys_types_defaults_and_comments_come_from_database_metadata(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA core;
                CREATE TABLE core.sample (code VARCHAR UNIQUE, parent VARCHAR,
                    stamp TIMESTAMPTZ, amount DECIMAL(12,3), note VARCHAR DEFAULT 'a,b(--x)',
                    FOREIGN KEY (parent) REFERENCES core.sample (code));
                COMMENT ON TABLE core.sample IS 'Sample; documentation with (parentheses).';
                COMMENT ON COLUMN core.sample.amount IS 'Measured amount, with three decimal places';
            """)
            table = read_catalog(connection, schemas=("core",)).tables["core.sample"]
        self.assertEqual(list(table.columns), ["code", "parent", "stamp", "amount", "note"])
        self.assertEqual(table.references, {"core.sample"})
        self.assertEqual(table.structural_columns, {"code", "parent", "stamp"})
        self.assertIn("DECIMAL(12,3)", table.columns["amount"])
        self.assertIn("Measured amount", table.columns["amount"])
        self.assertIn("a,b(--x)", table.columns["note"])
        excerpt = table.selected_schema(table.structural_columns)
        self.assertIn("FOREIGN KEY (parent)", excerpt)
        self.assertNotIn('"amount"', excerpt)
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            connection.execute(excerpt)

    def test_literals_and_descriptions_cannot_invent_keys_or_references(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA audit;
                CREATE TABLE audit.event (id INT, clock TIME, stamp TIMESTAMP_NS, zoned TIMETZ,
                    note VARCHAR DEFAULT 'TIMESTAMP REFERENCES audit.missing (id) UNIQUE PRIMARY KEY (id)');
                COMMENT ON COLUMN audit.event.note IS 'FOREIGN KEY(id) REFERENCES audit.missing(id)';
            """)
            table = read_catalog(connection, schemas=("audit",)).tables["audit.event"]
        self.assertEqual(table.references, frozenset())
        self.assertEqual(table.structural_columns, {"clock", "stamp", "zoned"})
        self.assertNotIn("-- Primary key:", table.selected_schema(["note"]))

    def test_composite_constraints_are_only_rendered_with_all_local_columns(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA core;
                CREATE TABLE core.sample (id INT, code INT, label VARCHAR,
                    PRIMARY KEY(id, code), UNIQUE(code), CHECK (id > 0 AND code > 0));
            """)
            table = read_catalog(connection, schemas=("core",)).tables["core.sample"]
        self.assertEqual(table.structural_columns, {"id", "code"})
        excerpt = table.selected_schema(["id", "label"])
        self.assertIn("-- Primary key: (id, code)", excerpt)
        self.assertNotIn("PRIMARY KEY(", excerpt)
        self.assertNotIn("UNIQUE(", excerpt)
        self.assertNotIn("CHECK(", excerpt)
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            connection.execute(excerpt)

    def test_reader_excludes_unapproved_schemas_views_temp_tables_and_attached_databases(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA approved;
                CREATE SCHEMA hidden;
                CREATE TABLE approved.item (id INT);
                CREATE TABLE hidden.secret (id INT);
                CREATE VIEW approved.summary AS SELECT * FROM approved.item;
                CREATE TEMP TABLE temp_item (id INT);
                ATTACH ':memory:' AS extra;
                CREATE SCHEMA extra.approved;
                CREATE TABLE extra.approved.other (id INT);
            """)
            catalog = read_catalog(connection, schemas=("APPROVED",))
        self.assertEqual(list(catalog.tables), ["approved.item"])

    def test_snapshots_work_after_connection_closes_and_do_not_follow_later_changes(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA core;
                CREATE TABLE core.item (id INT);
                COMMENT ON TABLE core.item IS 'Original description';
            """)
            snapshot = read_catalog(connection, schemas=("core",))
            connection.execute("COMMENT ON TABLE core.item IS 'Changed description'")
            changed = read_catalog(connection, schemas=("core",))
        self.assertIn("Original description", snapshot.tables["core.item"].ddl)
        self.assertIn("Changed description", changed.tables["core.item"].ddl)

    def test_quoted_names_and_multiline_defaults_render_without_changing_values(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA "Mixed Case";
                CREATE TABLE "Mixed Case"."Order" (
                    "select" VARCHAR DEFAULT 'first line
-- second line', "a""b" DECIMAL(12,3));
                COMMENT ON COLUMN "Mixed Case"."Order"."select" IS 'First line
Second line';
            """)
            table = read_catalog(connection, schemas=("Mixed Case",)).tables["mixed case.order"]
            expected = connection.execute('SELECT * FROM "Mixed Case"."Order"').description
        self.assertIn('"a""b" DECIMAL(12,3)', table.ddl)
        self.assertIn("-- Second line", table.columns["select"])
        with duckdb.connect() as connection:
            connection.execute('CREATE SCHEMA "Mixed Case"')
            connection.execute(table.ddl)
            connection.execute('INSERT INTO "Mixed Case"."Order" DEFAULT VALUES')
            value = connection.execute('SELECT "select" FROM "Mixed Case"."Order"').fetchone()[0]
            self.assertEqual(value, "first line\n-- second line")
            self.assertEqual(connection.execute('SELECT * FROM "Mixed Case"."Order"').description, expected)

    def test_catalog_order_is_deterministic_and_columns_retain_declaration_order(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA core;
                CREATE TABLE core.z_last (z INT, a INT);
                CREATE TABLE core.a_first (id INT);
            """)
            catalog = read_catalog(connection, schemas=("core",))
        self.assertEqual(list(catalog.tables), ["core.a_first", "core.z_last"])
        self.assertEqual(list(catalog.tables["core.z_last"].columns), ["z", "a"])

    def test_generated_columns_remain_queryable_when_source_columns_are_pruned(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA core;
                CREATE TABLE core.computed (source INTEGER, doubled INTEGER GENERATED ALWAYS AS (source * 2));
            """)
            table = read_catalog(connection, schemas=("core",)).tables["core.computed"]
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            connection.execute(table.ddl)
            connection.execute("INSERT INTO core.computed (source) VALUES (3)")
            self.assertEqual(connection.execute("SELECT doubled FROM core.computed").fetchone(), (6,))
        excerpt = table.selected_schema(["doubled"])
        self.assertIn("Generated as:", excerpt)
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            connection.execute(excerpt)

    def test_legacy_warehouse_without_stored_documentation_requests_a_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "warehouse.duckdb"
            with duckdb.connect(str(path)) as connection:
                connection.execute("CREATE SCHEMA core; CREATE TABLE core.dim_iso (iso_code VARCHAR)")
            with patch.object(config, "settings", replace(config.settings, db_path=path)):
                with self.assertRaisesRegex(ValueError, "descriptions are missing; rebuild"):
                    warehouse_catalog.load_catalog()

    def test_missing_warehouse_is_not_created_by_the_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.duckdb"
            with patch.object(config, "settings", replace(config.settings, db_path=path)):
                with self.assertRaisesRegex(FileNotFoundError, "warehouse missing"):
                    warehouse_catalog.load_catalog()
            self.assertFalse(path.exists())

    def test_metadata_and_guarded_connections_work_in_either_startup_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "warehouse.duckdb"
            with duckdb.connect(str(path)) as connection:
                connection.execute("""
                    CREATE SCHEMA core;
                    CREATE TABLE core.dim_iso (iso_code VARCHAR);
                    COMMENT ON TABLE core.dim_iso IS 'Grid region vocabulary';
                """)
            for guard_first in (False, True):
                with (
                    self.subTest(guard_first=guard_first),
                    patch.object(config, "settings", replace(config.settings, db_path=path)),
                    patch.object(db, "_db", None),
                ):
                    try:
                        if guard_first:
                            db._database()
                        first = warehouse_catalog.load_catalog()
                        db._database()
                        second = warehouse_catalog.load_catalog()
                        self.assertEqual(first.tables, second.tables)
                        with self.assertRaises(duckdb.Error):
                            db._database().execute("DELETE FROM core.dim_iso")
                    finally:
                        if db._db is not None:
                            db._db.close()

    def test_empty_schema_selection_is_rejected(self):
        with duckdb.connect() as connection:
            for schemas in ((), ("missing",)):
                with self.subTest(schemas=schemas), self.assertRaisesRegex(ValueError, "empty"):
                    read_catalog(connection, schemas=schemas)

    def test_case_insensitive_references_are_explicit_and_name_suffixes_are_not_keys(self):
        with duckdb.connect() as connection:
            connection.execute("""
                CREATE SCHEMA Retail;
                CREATE TABLE Retail.Department (name VARCHAR PRIMARY KEY);
                CREATE TABLE Retail.Item (sku VARCHAR PRIMARY KEY,
                    department VARCHAR REFERENCES Retail.Department(name),
                    updated TIMESTAMP, optional_id INT, optional_code VARCHAR);
            """)
            table = read_catalog(connection, schemas=("retail",)).tables["retail.item"]
        self.assertEqual(table.references, {"retail.department"})
        self.assertEqual(table.structural_columns, {"sku", "department", "updated"})

    def test_selected_columns_must_be_known_and_nonempty(self):
        table = Table("core", "sample", (Column("id", "INTEGER"),))
        for columns in ([], ["missing"]):
            with self.subTest(columns=columns), self.assertRaises(ValueError):
                table.selected_schema(columns)

    def test_inconsistent_catalogs_are_rejected(self):
        region = Table("core", "region", (Column("id", "INTEGER"),))
        site = Table(
            "core",
            "site",
            (Column("r", "INTEGER"),),
            (Constraint("FOREIGN KEY", ("r",), "FOREIGN KEY(r) REFERENCES core.region(id)", "core.region"),),
        )
        for tables in ([], [region, region], [site]):
            with self.subTest(tables=[table.name for table in tables]), self.assertRaises(ValueError):
                Catalog.of(tables)
        with self.assertRaises(ValueError):
            Catalog({"wrong": region})

    def test_catalog_and_table_own_immutable_snapshots_of_constructor_inputs(self):
        columns = [Column("id", "INTEGER")]
        constraints = [Constraint("PRIMARY KEY", ("id",), "PRIMARY KEY(id)")]
        table = Table("core", "region", columns, constraints)
        tables, isos = {table.name: table}, ["ISO"]
        catalog = Catalog(tables, isos=isos)
        columns.clear()
        constraints.clear()
        tables.clear()
        isos.clear()
        self.assertEqual(catalog.isos, ("ISO",))
        self.assertEqual(list(catalog.tables), [table.name])
        self.assertEqual(table.structural_columns, {"id"})
        with self.assertRaises(TypeError):
            catalog.tables["other"] = table
        with self.assertRaises(TypeError):
            table.columns["new"] = "new INTEGER"

    def test_invalid_column_metadata_is_rejected(self):
        for columns, constraints in (
            ((), ()),
            ((Column("id", "INTEGER"), Column("ID", "INTEGER")), ()),
            ((Column("id", "INTEGER"),), (Constraint("PRIMARY KEY", ("missing",), "PRIMARY KEY(missing)"),)),
        ):
            with self.subTest(columns=columns), self.assertRaises(ValueError):
                Table("core", "item", columns, constraints)
