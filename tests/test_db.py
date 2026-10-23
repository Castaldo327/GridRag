"""Model-written SQL runs read-only, guarded and bounded. Needs data/: python -m gridrag.warehouse.build."""

import unittest

import duckdb

from gridrag import db


class GuardTests(unittest.TestCase):
    def test_rejects_anything_but_one_select_over_core(self):
        for sql in [
            "DELETE FROM core.dim_iso",
            "SELECT 1; SELECT 2",
            "SELECT * FROM read_csv('/etc/passwd')",
            "SELECT * FROM query('SELECT * FROM core.dim_iso')",
            "SELECT * FROM information_schema.tables",
            "SELECT * FROM dim_iso",
        ]:
            with self.subTest(sql=sql):
                self.assertIn("error", db.run_model_sql(sql, 10))

    def test_select_returns_capped_csv(self):
        out = db.run_model_sql("WITH x AS (SELECT iso_code FROM core.dim_iso) SELECT * FROM x ORDER BY iso_code;", 2)
        self.assertEqual(out["rows"], 2)
        self.assertEqual(out["csv"], "iso_code\nCAISO\nERCOT\n")
        self.assertIn("truncated", out)

    def test_sql_errors_come_back_as_data(self):
        out = db.run_model_sql("SELECT no_such_column FROM core.dim_iso", 10)
        self.assertIn("Binder", out["error"])

    def test_connection_blocks_writes_and_files_even_without_the_guard(self):
        for sql in ["DELETE FROM core.dim_iso", "SELECT * FROM read_csv('/etc/passwd')"]:
            with self.subTest(sql=sql), self.assertRaises(duckdb.Error):
                db._database().cursor().execute(sql)


if __name__ == "__main__":
    unittest.main()
