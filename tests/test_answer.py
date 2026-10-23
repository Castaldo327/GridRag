"""A failing stage becomes a failed record, never a crash or a silent fallback. No provider calls."""

import unittest
from unittest.mock import patch

from gridrag import answer

ALLOWED = {"allowed": True, "reason": "Relevant analytical question", "relevance": 0.99, "malicious": 0.01}


class FailureTests(unittest.TestCase):
    def test_gate_outage_is_a_failure_not_a_refusal_and_hides_details(self):
        with (patch.object(answer, "gate", side_effect=RuntimeError("secret diagnostic")),
              self.assertLogs("gridrag.answer", level="ERROR") as logs):
            res = answer.answer("What was ERCOT demand?")
        self.assertEqual((res["state"], res["stage"], res["error"]), ("failed", "gate", "RuntimeError"))
        self.assertEqual(set(res["timings"]), {"gate", "total"})
        self.assertEqual(res["usage"]["calls"], 0)
        self.assertNotIn("secret diagnostic", str(res))
        self.assertIn("secret diagnostic", "\n".join(logs.output))  # the detail is logged instead

    def test_routing_failure_never_reaches_sql(self):
        with (patch.object(answer, "gate", return_value=ALLOWED),
              patch.object(answer, "route", side_effect=RuntimeError("routing unavailable")),
              patch.object(answer.agent, "run") as sql,
              self.assertLogs("gridrag.answer", level="ERROR")):
            res = answer.answer("What was ERCOT demand?")
        sql.assert_not_called()
        self.assertEqual((res["state"], res["stage"]), ("failed", "route"))
        self.assertEqual(res["gate"], ALLOWED)


if __name__ == "__main__":
    unittest.main()
