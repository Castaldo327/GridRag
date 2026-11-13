"""End-to-end accuracy checks using real provider calls. Opt in with GRIDRAG_LIVE_TESTS=1 and an API key.

Asks every case in the versioned live regression suite in gridrag/warehouse/suite.py."""

import os
import unittest

from gridrag import answer, config
from gridrag.warehouse.evaluation import assess, evaluation_question, evidence_matches, states_value
from gridrag.warehouse.suite import EVALUATION_CASES as CASES


class EvaluationChecks(unittest.TestCase):
    def test_rounded_prose_cannot_hide_wrong_evidence(self):
        expected = 42.07465178730204
        result = {"tool_calls": [{"csv": "share\n42.06103487163652\n"}]}
        self.assertTrue(states_value("42.1%", expected, 0.01))
        self.assertFalse(evidence_matches(result, expected, 0.01))
        self.assertTrue(states_value("−$1.09/MWh", -1.0858, 0.01))
        self.assertFalse(states_value("$1.09/MWh", -1.0858, 0.01))


@unittest.skipUnless(
    os.environ.get("GRIDRAG_LIVE_TESTS") == "1" and config.settings.openai_api_key,
    "Set GRIDRAG_LIVE_TESTS=1 and an API key to run paid provider evaluations",
)
class LiveTests(unittest.TestCase):
    def test_evaluation_cases(self):
        for case in CASES:
            with self.subTest(case=case.id):
                res = answer.answer(evaluation_question(case))
                tables = res["route"]["tables"] if res["route"] else []
                print(
                    f"\n{case.id}: {res['state']} in {res['timings']['total']:.1f}s · "
                    f"{len(res['tool_calls'])} SQL queries · estimated ${res['usage']['cost_usd']:.6f}"
                    f"\n{res['answer']}\n{tables}"
                )
                assessment = assess(case, res)
                self.assertTrue(assessment["passed"], assessment["diagnostics"]["failed_checks"])


if __name__ == "__main__":
    unittest.main()
