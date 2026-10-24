"""The catalog: documented tables with their references, and per-ISO families that routing scores once."""

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
