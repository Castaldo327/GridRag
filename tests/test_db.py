"""Model-written SQL runs read-only, guarded and bounded. Needs data/: python -m gridrag.warehouse.build."""

import unittest
from dataclasses import replace
from unittest.mock import patch

import duckdb

from gridrag import config, db


def limits(**changes):
    return patch.object(config, "settings", replace(config.settings, **changes))


class GuardTests(unittest.TestCase):
    def test_rejects_anything_but_one_select_over_catalog_tables(self):
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

    def test_comments_and_semicolons_cannot_break_the_row_limit(self):
        # The guard runs the query as the parser regenerates it, so a trailing comment cannot swallow the wrapper.
        for sql in ["SELECT count(*) AS n FROM core.dim_iso -- count ISOs",
                    "SELECT count(*) AS n FROM core.dim_iso; -- done",
                    "SELECT count(*) AS n /* how many */ FROM core.dim_iso",
                    "SELECT 7 AS n -- FROM core.queue_project"]:
            with self.subTest(sql=sql):
                self.assertEqual(db.run_model_sql(sql, 1, {"core.dim_iso"}), {"rows": 1, "csv": "n\n7\n"})

    def test_routed_out_tables_cannot_be_queried(self):
        routed = {"core.dim_iso", "core.fact_balance_hourly"}
        for sql in [
            "SELECT count(*) FROM core.queue_project",
            "WITH q AS (SELECT * FROM core.queue_project) SELECT count(*) FROM q",
            "SELECT * FROM core.fact_balance_hourly WHERE iso_id IN (SELECT iso_id FROM core.queue_project)",
            "SELECT count(*) FROM CORE.Queue_Project",
        ]:
            with self.subTest(sql=sql):
                self.assertIn("not available: core.queue_project", db.run_model_sql(sql, 10, routed)["error"])
        allowed = "SELECT count(*) AS n FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id)"
        self.assertEqual(db.run_model_sql(allowed, 10, routed)["rows"], 1)

    def test_table_and_cte_names_are_case_insensitive_like_duckdb(self):
        for sql in ["SELECT count(*) AS n FROM Core.Dim_Iso",
                    "WITH Isos AS (SELECT * FROM CORE.DIM_ISO) SELECT count(*) AS n FROM isos"]:
            with self.subTest(sql=sql):
                self.assertEqual(db.run_model_sql(sql, 1, {"core.dim_iso"})["csv"], "n\n7\n")

    def test_fractions_keep_their_digits_and_large_values_keep_cents(self):
        out = db.run_model_sql("SELECT 0.42072033::DOUBLE AS share, 70979.2216::DOUBLE AS mw, "
                               "-0.000123456::DOUBLE AS tiny, NULL::DOUBLE AS missing", 1)
        self.assertEqual(out["csv"], "share,mw,tiny,missing\n0.42072033,70979.2216,-0.000123456,\n")

    def test_sql_errors_come_back_as_data(self):
        out = db.run_model_sql("SELECT no_such_column FROM core.dim_iso", 10)
        self.assertIn("Binder", out["error"])

    def test_query_timeout_recovers_and_large_results_are_rejected(self):
        with limits(sql_timeout_s=0.05):
            out = db.run_model_sql("SELECT sum(sin(i)) FROM range(1000000000) t(i)", 1)
        self.assertIn("execution budget", out["error"])
        self.assertEqual(db.run_model_sql("SELECT 1 AS n", 1)["csv"], "n\n1\n")
        with limits(sql_max_result_bytes=10):
            out = db.run_model_sql("SELECT repeat('x', 20) AS text", 1)
        self.assertIn("result exceeds", out["error"])

    def test_connection_blocks_writes_and_files_even_without_the_guard(self):
        for sql in ["DELETE FROM core.dim_iso", "SELECT * FROM read_csv('/etc/passwd')"]:
            with self.subTest(sql=sql), self.assertRaises(duckdb.Error):
                db._database().cursor().execute(sql)


if __name__ == "__main__":
    unittest.main()
