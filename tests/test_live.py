"""End-to-end accuracy checks using real provider calls. Opt in with GRIDRAG_LIVE_TESTS=1 and an API key.

Asks every case in gridrag/warehouse/evals.py, the same table the UI presets come from."""

import os
import re
import unittest

from gridrag import answer, config
from gridrag.records import State
from gridrag.warehouse.evals import CASES, reference_value

NUMBER = re.compile(r"[-−]?\d[\d,]*(?:\.(\d+))?")


def states_value(text: str, expected: float, tolerance: float) -> bool:
    """Whether text states expected: within the case tolerance, or equal at the precision the text shows."""
    for number in NUMBER.finditer(text):
        value = float(number.group().replace(",", "").replace("−", "-"))
        shown = 0.5 * 10 ** -len(number.group(1) or "")  # "70,979" stands for 70,978.5 up to 70,979.5
        if abs(value - expected) <= max(tolerance, shown) + 1e-9:
            return True
    return False


@unittest.skipUnless(os.environ.get("GRIDRAG_LIVE_TESTS") == "1" and config.settings.openai_api_key,
                     "Set GRIDRAG_LIVE_TESTS=1 and an API key to run paid provider evaluations")
class LiveTests(unittest.TestCase):
    def test_evaluation_cases(self):
        for case in CASES:
            with self.subTest(case=case.id):
                res = answer.answer(case.question)
                tables = res["route"]["tables"] if res["route"] else []
                print(f"\n{case.id}: {res['state']} in {res['timings']['total']:.1f}s\n{res['answer']}\n{tables}")
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
                    self.assertTrue(states_value(res["answer"], expected, case.tolerance),
                                    f"expected {expected} {case.unit}")


if __name__ == "__main__":
    unittest.main()
