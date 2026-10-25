"""The shared evaluation table stays runnable offline. Needs data/: python -m gridrag.warehouse.build."""

import math
import unittest

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


if __name__ == "__main__":
    unittest.main()
