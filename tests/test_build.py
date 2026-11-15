"""The warehouse builds from code alone: no downloads, keys or model calls."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd

from gridrag import config
from gridrag.catalog import read_catalog
from gridrag.warehouse import build, fixtures, products, synthetic


class BuildTests(unittest.TestCase):
    def test_failed_insert_preserves_previous_snapshot_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "warehouse.duckdb"
            with duckdb.connect(str(database)) as connection:
                connection.execute("CREATE TABLE previous AS SELECT 42 AS value")
            previous = database.read_bytes()
            # The first table loads successfully; the second fails a constraint.
            frames = {
                "first_table": pd.DataFrame({"value": [1]}),
                "second_table": pd.DataFrame({"value": [-1]}),
            }
            schema = (
                "CREATE TABLE first_table (value INTEGER); CREATE TABLE second_table (value INTEGER CHECK (value > 0))"
            )
            with (
                patch.object(config, "settings", replace(config.settings, db_path=database)),
                patch.object(synthetic, "frames", return_value=frames),
                patch.object(build, "schema_text", return_value=schema),
            ):
                with self.assertRaises(duckdb.ConstraintException):
                    build.build()
            self.assertEqual(database.read_bytes(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [database])

    def test_failed_rebuild_preserves_previous_snapshot_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "warehouse.duckdb"
            with duckdb.connect(str(database)) as connection:
                connection.execute("CREATE TABLE previous AS SELECT 42 AS value")
            previous = database.read_bytes()
            with (
                patch.object(config, "settings", replace(config.settings, db_path=database)),
                patch.object(synthetic, "frames", return_value={}),
                patch.object(build, "schema_text", return_value="INVALID SQL"),
            ):
                with self.assertRaises(duckdb.Error):
                    build.build()
            self.assertEqual(database.read_bytes(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [database])

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        database = Path(cls.tmp.name) / "warehouse.duckdb"
        with patch.object(config, "settings", replace(config.settings, db_path=database)):
            cls.counts = build.build()
        cls.con = duckdb.connect(str(database), read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def test_local_days_follow_each_iso_clock(self):
        # CAISO falls back on 2025-11-02, so that local day has 25 hours; MISO's fixed EST has 24.
        sql = """SELECT count(*) FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id)
                 WHERE iso_code = ? AND interval_start_local::DATE = DATE '2025-11-02'"""
        self.assertEqual(self.con.execute(sql, ["CAISO"]).fetchone()[0], 25)
        self.assertEqual(self.con.execute(sql, ["MISO"]).fetchone()[0], 24)

    def test_net_generation_is_the_sum_of_fuel_rows(self):
        # Fuel shares divide by net_generation_mw, so it must equal the fuel rows it summarizes.
        worst, hours = self.con.execute("""SELECT max(abs(b.net_generation_mw - g.mw)), count(*)
            FROM core.fact_balance_hourly b
            JOIN (SELECT iso_id, interval_start_utc, sum(generation_mw) AS mw FROM core.fact_generation_hourly
                  GROUP BY ALL) g USING (iso_id, interval_start_utc)""").fetchone()
        self.assertEqual(hours, self.counts["core.fact_balance_hourly"])
        self.assertLess(worst, 0.006)  # rounding to cents only

    def test_iso_ids_are_explicit_everywhere_they_appear(self):
        isos = self.con.execute("SELECT iso_id, iso_code, timezone FROM core.dim_iso ORDER BY iso_id").fetchall()
        self.assertEqual(isos, [(iso.id, iso.code, iso.tz) for iso in fixtures.ISOS])
        for iso in fixtures.ISOS:
            with self.subTest(iso=iso.code):
                table = products.table_name(iso.code, products.PRODUCTS[0])
                self.assertEqual(self.con.execute(f"SELECT DISTINCT iso_id FROM {table}").fetchall(), [(iso.id,)])
                locations = self.con.execute(
                    "SELECT min(location_id) FROM core.dim_location WHERE iso_id = ?", [iso.id]
                ).fetchone()[0]
                self.assertEqual(locations, iso.id * 10 + 1)

    def test_every_product_generates_rows_for_every_iso(self):
        for product in products.PRODUCTS:
            with self.subTest(product=product.suffix):
                self.assertTrue(all(self.counts[products.table_name(iso.code, product)] for iso in fixtures.ISOS))

    def test_built_snapshot_contains_the_documentation_used_for_routing(self):
        catalog = read_catalog(self.con, schemas=("core",))
        self.assertEqual(len(catalog.tables), len(self.counts))
        balance = catalog.tables["core.fact_balance_hourly"]
        self.assertIn("Aggregate balance and fuel generation separately", balance.description)
        self.assertIn("demand (load), MW", balance.columns["demand_mw"])
        forecast = catalog.tables["core.ercot_load_forecast_hourly"]
        self.assertIn("ERCOT only", forecast.description)
        self.assertIn("publication", forecast.description)
        self.assertIn("UTC;", forecast.columns["interval_start_utc"])

    def test_every_built_table_has_authored_routing_labels(self):
        catalog = read_catalog(self.con, schemas=("core",))
        self.assertEqual(len(catalog.tables), 65)
        for name, table in catalog.tables.items():
            with self.subTest(table=name):
                self.assertTrue(table.routing_tags)
                self.assertNotIn("@routing_tags:", table.ddl)
        self.assertEqual(catalog.tables["core.fact_balance_hourly"].routing_tags, ("forecast", "generation", "load"))
        self.assertEqual(catalog.tables["core.dim_fuel"].routing_tags, ("dimensions", "fuel"))
        for iso in fixtures.ISOS:
            for product in products.PRODUCTS:
                with self.subTest(iso=iso.code, product=product.suffix):
                    table = catalog.tables[products.table_name(iso.code, product)]
                    self.assertEqual(table.routing_tags, tuple(sorted(product.routing_tags)))


if __name__ == "__main__":
    unittest.main()
