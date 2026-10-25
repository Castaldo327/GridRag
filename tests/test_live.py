"""End-to-end accuracy checks using real provider calls. Opt in with GRIDRAG_LIVE_TESTS=1 and an API key.

Asks every case in gridrag/warehouse/evals.py, the same table the UI presets come from."""

import os
import unittest

from gridrag import answer, config
from gridrag.records import State
from gridrag.warehouse.evaluation import evidence_matches, states_value
from gridrag.warehouse.evals import CASES, reference_value


class EvaluationChecks(unittest.TestCase):
    def test_rounded_prose_cannot_hide_wrong_evidence(self):
        expected = 42.07465178730204
        result = {"tool_calls": [{"csv": "share\n42.06103487163652\n"}]}
        self.assertTrue(states_value("42.1%", expected, 0.01))
        self.assertFalse(evidence_matches(result, expected, 0.01))
        self.assertTrue(states_value("−$1.09/MWh", -1.0858, 0.01))
        self.assertFalse(states_value("$1.09/MWh", -1.0858, 0.01))


@unittest.skipUnless(os.environ.get("GRIDRAG_LIVE_TESTS") == "1" and config.settings.openai_api_key,
                     "Set GRIDRAG_LIVE_TESTS=1 and an API key to run paid provider evaluations")
class LiveTests(unittest.TestCase):
    def test_evaluation_cases(self):
        for case in CASES:
            with self.subTest(case=case.id):
                res = answer.answer(case.question)
                tables = res["route"]["tables"] if res["route"] else []
                print(f"\n{case.id}: {res['state']} in {res['timings']['total']:.1f}s · "
                      f"{len(res['tool_calls'])} SQL queries · estimated ${res['usage']['cost_usd']:.6f}"
                      f"\n{res['answer']}\n{tables}")
                self.assertEqual(res["state"], case.state)
                for table in case.tables:
                    self.assertIn(table, tables)
                for table in case.excluded:
                    self.assertNotIn(table, tables)
                queries = " ".join(call["query"] or "" for call in res["tool_calls"])
                for text in case.avoid:
                    self.assertNotIn(text, queries)
                if case.state is not State.ANSWERED:
                    self.assertEqual(res["tool_calls"], [])  # declined and clarified requests never reach SQL
                if case.sql:
                    expected = reference_value(case)
                    self.assertTrue(evidence_matches(res, expected, case.tolerance),
                                    f"query evidence did not match {expected} {case.unit}")
                    self.assertTrue(states_value(res["answer"], expected, case.tolerance),
                                    f"expected {expected} {case.unit}")


if __name__ == "__main__":
    unittest.main()
