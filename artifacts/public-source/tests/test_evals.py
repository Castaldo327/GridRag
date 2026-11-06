"""The shared evaluation table stays runnable offline. Needs data/: python -m gridrag.warehouse.build."""

import csv
import io
import math
import unittest

from gridrag import db
from gridrag.catalog import demo_catalog
from gridrag.records import State
from gridrag.warehouse import evals
from gridrag.warehouse.evaluation import assess


class EvalTests(unittest.TestCase):
    def test_reference_queries_compute_one_number(self):
        for case in evals.CASES:
            if case.sql:
                with self.subTest(case=case.id):
                    self.assertTrue(math.isfinite(evals.reference_value(case)))

    def test_cases_name_catalog_tables_and_answerable_cases_have_references(self):
        tables = demo_catalog().tables
        self.assertEqual(len({case.id for case in evals.CASES}), len(evals.CASES))
        for case in evals.CASES:
            with self.subTest(case=case.id):
                self.assertLessEqual(set(case.tables) | set(case.excluded), tables.keys())
                self.assertEqual(bool(case.sql), case.state is State.ANSWERED)

    def test_assessment_checks_answer_and_behavior_cases(self):
        peak = evals.CASES[0]
        expected = evals.reference_value(peak)
        result = {"state": "answered", "route": {"tables": list(peak.tables)},
                  "tool_calls": [{"query": "SELECT max(demand_mw)", "csv": f"value\n{expected}\n"}],
                  "answer": f"Peak demand was {expected:,.2f} MW."}
        self.assertTrue(assess(peak, result)["passed"])
        wrong = {**result, "tool_calls": [{"query": "SELECT 1", "csv": "value\n1\n"}]}
        self.assertFalse(assess(peak, wrong)["passed"])
        self.assertTrue(assess(evals.CASES[-2], {"state": "declined", "route": None,
                                                  "tool_calls": [], "answer": "Off topic."})["passed"])

    def test_hard_case_warehouse_verification(self):
        case = next(case for case in evals.CASES if case.id == "spread_forecast_error")
        def row(sql):
            result = db.run_model_sql(sql, 1)
            self.assertNotIn("error", result)
            return list(csv.reader(io.StringIO(result["csv"])))[1]

        hour = row("""SELECT date_trunc('hour', rt.interval_start_utc) AS utc_hour,
                    avg(rt.lmp) - max(da.lmp) AS spread
                FROM core.caiso_lmp_rt_hub_5min rt
                JOIN core.caiso_lmp_da_hub_hourly da
                  ON date_trunc('hour', rt.interval_start_utc) = da.interval_start_utc
                WHERE rt.interval_start_local::DATE = DATE '2026-10-21'
                GROUP BY 1 HAVING count(*) = 12
                ORDER BY spread DESC, utc_hour ASC LIMIT 1""")
        self.assertEqual(hour[0], "2026-10-21 15:00:00")
        self.assertAlmostEqual(float(hour[1]), -0.285)

        forecast = row("""SELECT publish_time_utc, forecast_mw
                FROM core.caiso_load_forecast_hourly
                WHERE interval_start_utc = TIMESTAMP '2026-10-21 15:00'
                  AND publish_time_utc <= TIMESTAMP '2026-10-21 12:00'
                ORDER BY publish_time_utc DESC LIMIT 1""")
        actual = float(row("""SELECT demand_mw FROM core.fact_balance_hourly
                WHERE iso_id = 1 AND interval_start_utc = TIMESTAMP '2026-10-21 15:00'""")[0])
        self.assertEqual(forecast[0], "2026-10-21 09:00:00")
        self.assertAlmostEqual(float(forecast[1]), 34708.94)
        self.assertAlmostEqual(actual, 35127.47)
        self.assertAlmostEqual(evals.reference_value(case), float(forecast[1]) - actual)
        self.assertAlmostEqual(evals.reference_value(case), -418.53)


if __name__ == "__main__":
    unittest.main()
