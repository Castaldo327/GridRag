"""Catalog metadata, immutable snapshots, and schema excerpts used for column routing."""

import unittest

import duckdb

from gridrag.catalog import Catalog, Family, Table, demo_catalog, parse


class CatalogTests(unittest.TestCase):
    def test_demo_catalog_preserves_complete_executable_definitions(self):
        tables = demo_catalog().tables
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            for table in tables.values():
                connection.execute(table.ddl)
            count = connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'").fetchone()[0]
        self.assertEqual(count, len(tables))
        # The UTC column comment contains a semicolon; it must not truncate the DDL.
        self.assertIn("PRIMARY KEY", tables["core.ercot_load_forecast_hourly"].ddl)

    def test_demo_families_stand_in_for_every_per_iso_table(self):
        catalog = demo_catalog()
        units = catalog.units()
        self.assertEqual(len(units), 17)  # 9 core tables + 8 product families
        self.assertEqual(catalog.isos, ("CAISO", "ERCOT", "ISONE", "MISO", "NYISO", "PJM", "SPP"))
        members = {table for family in catalog.families.values() for table in family.tables.values()}
        self.assertEqual(len(members), 56)
        self.assertEqual(members | (units.keys() - catalog.families.keys()), catalog.tables.keys())
        family = catalog.families["core.<iso>_lmp_rt_hub_5min"]
        self.assertEqual(family.tables["ERCOT"], "core.ercot_lmp_rt_hub_5min")
        self.assertIn("One table per ISO", family.ddl)
        self.assertEqual(catalog.tables["core.ercot_lmp_rt_hub_5min"].references, {"core.dim_iso", "core.dim_location"})

    def test_references_come_from_code_not_comments_and_ignore_case(self):
        table = Table.parse("-- Formerly REFERENCES core.legacy\nCREATE TABLE Core.Station (\n"
                            "    region INTEGER references CORE.Region (id)  -- see REFERENCES core.other\n);")
        self.assertEqual((table.name, table.references), ("core.station", {"core.region"}))

    def test_scripts_split_into_statements_with_their_comments(self):
        tables = parse("-- Regions\nCREATE TABLE core.region (\n    id INTEGER\n);\n\n"
                       "CREATE TABLE core.site (\n    region INTEGER REFERENCES core.region (id),\n\n    x INT\n);")
        self.assertEqual([table.name for table in tables], ["core.region", "core.site"])
        self.assertTrue(tables[0].ddl.startswith("-- Regions\n"))
        self.assertTrue(tables[1].ddl.endswith("x INT\n);"))  # blank lines inside the statement are kept

    def test_column_excerpts_preserve_comments_and_skip_unselected_measures(self):
        table = demo_catalog().tables["core.fact_balance_hourly"]
        self.assertIn("demand_mw", table.columns)
        self.assertIn("demand (load), MW", table.columns["demand_mw"])
        excerpt = table.selected_schema(["iso_id", "interval_start_utc", "demand_mw"])
        self.assertIn("Primary key", excerpt)
        self.assertIn("demand (load), MW", excerpt)
        self.assertNotIn("net_generation_mw", excerpt)
        self.assertNotIn("demand_forecast_mw", excerpt)

    def test_compact_column_parser_handles_commas_inside_types(self):
        table = Table.parse("CREATE TABLE core.sample (id INT, amount DECIMAL(12,3), "
                            "name VARCHAR, PRIMARY KEY (id));")
        self.assertEqual(list(table.columns), ["id", "amount", "name"])

    def test_declared_keys_survive_pruning_and_literals_do_not_split_columns(self):
        table = Table.parse("CREATE TABLE core.sample (code VARCHAR UNIQUE, parent VARCHAR, "
                            "stamp TIMESTAMPTZ, note VARCHAR DEFAULT 'a,b(--x)', "
                            "FOREIGN KEY (parent) REFERENCES core.sample (code));")
        self.assertEqual(list(table.columns), ["code", "parent", "stamp", "note"])
        self.assertEqual(table.structural_columns, {"code", "parent", "stamp"})
        excerpt = table.selected_schema(table.structural_columns)
        self.assertIn("FOREIGN KEY (parent)", excerpt)
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            connection.execute(table.selected_schema(table.columns))
        with self.assertRaises(TypeError):
            table.columns["new"] = "new INTEGER"
        with self.assertRaises(ValueError):
            Table.parse("CREATE TABLE core.broken (value INTEGER")

    def test_inconsistent_catalogs_are_rejected(self):
        region = Table.parse("CREATE TABLE core.region (id INTEGER);")
        for tables, families in (
            ([], []),
            ([region, region], []),
            ([Table.parse("CREATE TABLE core.site (r INTEGER REFERENCES core.region (id));")], []),
            ([region], [Family("core.<iso>_x", "-- x", {"CAISO": "core.caiso_x"})]),
        ):
            with self.subTest(tables=[t.name for t in tables], families=len(families)), self.assertRaises(ValueError):
                Catalog.of(tables, families)

    def test_family_collisions_cannot_silently_drop_routing_units(self):
        table = Table.parse("CREATE TABLE core.region (id INTEGER);")
        family = Family("regions", "-- regions", {"ISO": table.name})
        for families in (
            [family, family],
            [Family(table.name, "-- collision", {"ISO": table.name})],
            [family, Family("other", "-- overlap", {"ISO": table.name})],
            [Family("regions", "-- duplicate member", {"A": table.name, "B": table.name})],
        ):
            with self.subTest(families=families), self.assertRaises(ValueError):
                Catalog.of([table], families)
        with self.assertRaises(ValueError):
            Family("empty", "-- empty", {})

    def test_catalog_owns_immutable_snapshots_of_constructor_inputs(self):
        table = Table.parse("CREATE TABLE core.region (id INTEGER);")
        members = {"ISO": table.name}
        family = Family("regions", "-- regions", members)
        tables, families = {table.name: table}, {family.name: family}
        catalog = Catalog(tables, families)
        members.clear()
        tables.clear()
        families.clear()
        self.assertEqual(catalog.isos, ("ISO",))
        self.assertEqual(list(catalog.tables), [table.name])
        with self.assertRaises(TypeError):
            catalog.tables["other"] = table
        with self.assertRaises(TypeError):
            family.tables["other"] = table.name

    def test_direct_constructor_rejects_mismatched_keys(self):
        table = Table.parse("CREATE TABLE core.region (id INTEGER);")
        with self.assertRaises(ValueError):
            Catalog({"wrong": table})
        family = Family("regions", "-- regions", {"ISO": table.name})
        with self.assertRaises(ValueError):
            Catalog({table.name: table}, {"wrong": family})
