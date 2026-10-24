"""A failing stage becomes a failed record, never a crash or a silent fallback. No provider calls."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gridrag import answer, config
from gridrag.catalog import demo_catalog
from gridrag.records import Stage, State

ALLOWED = {"allowed": True, "reason": "Relevant analytical question", "relevance": 0.99, "malicious": 0.01}
USAGE = {"calls": 0, "failed_calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
         "cost_usd": 0.0, "per_call": []}


def model(**methods):
    return SimpleNamespace(totals=lambda: USAGE, **methods)


class FailureTests(unittest.TestCase):
    def test_gate_outage_is_a_failure_not_a_refusal_and_hides_details(self):
        with (patch.object(answer, "gate", side_effect=RuntimeError("secret diagnostic")),
              self.assertLogs("gridrag.answer", level="ERROR") as logs):
            res = answer.answer("What was ERCOT demand?")
        self.assertEqual((res["state"], res["stage"], res["error"]), (State.FAILED, Stage.GATE, "RuntimeError"))
        self.assertEqual(set(res["timings"]), {"gate", "total"})
        self.assertEqual(res["usage"]["calls"], 0)
        self.assertNotIn("secret diagnostic", str(res))
        self.assertIn("secret diagnostic", "\n".join(logs.output))  # the detail is logged instead

    def test_routing_outage_is_a_failure_not_a_clarification(self):
        # No usable scores would otherwise keep all 65 tables and ask the user to narrow the question.
        with (patch.object(answer, "gate", return_value=ALLOWED),
              patch.object(answer.agent, "run") as sql,
              self.assertLogs("gridrag.answer", level="ERROR")):
            res = answer.answer("What was ERCOT demand?", model(decide=lambda *args: {}))
        sql.assert_not_called()
        self.assertEqual((res["state"], res["stage"], res["error"]), (State.FAILED, Stage.ROUTE, "RoutingFailed"))
        self.assertIsNone(res["route"])

    def test_too_broad_a_route_asks_to_narrow_and_keeps_the_selection(self):
        selection = {"tables": [f"core.t{i}" for i in range(23)]}
        with (patch.object(answer, "gate", return_value=ALLOWED),
              patch.object(answer, "route", side_effect=answer.RoutingTooBroad(selection)),
              patch.object(answer.agent, "run") as sql):
            res = answer.answer("Compare every energy price")
        sql.assert_not_called()
        self.assertEqual(res["state"], State.CLARIFICATION)
        self.assertIn("Which region", res["answer"])
        self.assertEqual(res["route"], selection)  # what was chosen stays visible

    def test_sql_receives_only_the_routed_schema(self):
        selection = {"tables": ["core.dim_iso", "core.dim_location"], "scores": {}, "iso_scores": {},
                     "fallback": False}
        output = {"answer": "28 locations", "state": State.ANSWERED, "tool_calls": []}
        with (patch.object(answer, "gate", return_value=ALLOWED),
              patch.object(answer, "route", return_value=selection),
              patch.object(answer.agent, "run", return_value=output) as sql):
            res = answer.answer("  How many price locations are there?  ", model())
        tables = demo_catalog().tables
        sql.assert_called_once()
        self.assertEqual(sql.call_args.args[1], "How many price locations are there?")
        self.assertEqual(sql.call_args.kwargs["schema"],
                         f"{tables['core.dim_iso'].ddl}\n\n{tables['core.dim_location'].ddl}")
        self.assertEqual(sql.call_args.kwargs["allowed_tables"], selection["tables"])
        self.assertEqual((res["state"], res["answer"]), (State.ANSWERED, "28 locations"))
        self.assertEqual(set(res["timings"]), {"gate", "route", "sql", "total"})

    def test_questions_outside_the_length_limit_are_rejected(self):
        for question in ("", "   ", "x" * (config.settings.max_question_chars + 1), None):
            with self.subTest(question=question), self.assertRaises(ValueError):
                answer.answer(question)


if __name__ == "__main__":
    unittest.main()
