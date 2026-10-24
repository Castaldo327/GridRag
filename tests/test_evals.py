"""The shared evaluation table stays runnable offline. Needs data/: python -m gridrag.warehouse.build."""

import math
import unittest

from gridrag.catalog import demo_catalog
from gridrag.records import State
from gridrag.warehouse import evals


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


if __name__ == "__main__":
    unittest.main()
