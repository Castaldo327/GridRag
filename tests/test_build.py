"""The warehouse builds from code alone: no downloads, keys or model calls."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from gridrag.warehouse import build


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        database = Path(cls.tmp.name) / "warehouse.duckdb"
        with patch.object(build, "DB", database):
            cls.counts = build.build()
        cls.con = duckdb.connect(str(database), read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def test_every_table_is_populated(self):
        self.assertEqual(self.counts["core.dim_iso"], 7)
        print(f"\n{'table':<40}{'rows':>10}")
        for table, rows in self.counts.items():
            print(f"{table:<40}{rows:>10}")
            print(self.con.execute(f"SELECT * FROM {table} LIMIT 5").df().to_string(index=False), "\n")
            self.assertEqual(self.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], rows, table)

    def test_local_days_follow_each_iso_clock(self):
        # CAISO falls back on 2025-11-02, so that local day has 25 hours; MISO's fixed EST has 24.
        sql = """SELECT count(*) FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id)
                 WHERE iso_code = ? AND interval_start_local::DATE = DATE '2025-11-02'"""
        self.assertEqual(self.con.execute(sql, ["CAISO"]).fetchone()[0], 25)
        self.assertEqual(self.con.execute(sql, ["MISO"]).fetchone()[0], 24)


if __name__ == "__main__":
    unittest.main()
