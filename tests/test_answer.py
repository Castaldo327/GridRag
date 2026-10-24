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
        selection = {"tables": ["core.dim_iso", "core.dim_location"], "scores": {}, "column_scores": {},
                     "columns": {"core.dim_iso": ["iso_id", "iso_code"],
                                 "core.dim_location": ["location_id", "iso_id", "location_code"]},
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
                         "\n\n".join(tables[name].selected_schema(selection["columns"][name])
                                     for name in selection["tables"]))
        self.assertNotIn("location_type", sql.call_args.kwargs["schema"])
        self.assertEqual(sql.call_args.kwargs["allowed_tables"], selection["tables"])
        self.assertEqual((res["state"], res["answer"]), (State.ANSWERED, "28 locations"))
        self.assertEqual(set(res["timings"]), {"gate", "route", "sql", "total"})

    def test_first_token_measures_request_start_and_is_not_overwritten(self):
        now = [10.0]
        def stream(*args, on_progress, **kwargs):
            on_progress({"answer_delta": ""})
            now[0] = 13.0
            on_progress({"answer_delta": "Hello"})
            now[0] = 18.0
            on_progress({"answer_delta": " world"})
            now[0] = 20.0
            return {"state": State.ANSWERED, "answer": "Hello world", "tool_calls": []}
        with (patch.object(answer.time, "perf_counter", side_effect=lambda: now[0]),
              patch.object(answer, "gate", return_value=ALLOWED),
              patch.object(answer, "route", return_value={"tables": ["core.dim_iso"],
                                                               "columns": {"core.dim_iso": ["iso_id"]}}),
              patch.object(answer.agent, "run", side_effect=stream)):
            result = answer.answer("question", model())
        self.assertEqual(result["timings"]["first_token"], 3.0)
        self.assertEqual(result["timings"]["total"], 10.0)

    def test_questions_outside_the_length_limit_are_rejected(self):
        for question in ("", "   ", "x" * (config.settings.max_question_chars + 1), None):
            with self.subTest(question=question), self.assertRaises(ValueError):
                answer.answer(question)


class DependencyTests(unittest.TestCase):
    def test_progress_failure_keeps_stage_timing_and_disconnects_propagate(self):
        for error in (ValueError("consumer failed"), BrokenPipeError(), ConnectionResetError()):
            def callback(update):
                raise error

            with self.subTest(error=error), patch.object(answer, "gate") as gate:
                if isinstance(error, (BrokenPipeError, ConnectionResetError)):
                    with self.assertRaises(type(error)):
                        answer.answer("question", model(), callback)
                else:
                    with self.assertLogs("gridrag.answer", level="ERROR"):
                        result = answer.answer("question", model(), callback)
                    self.assertEqual(result["state"], State.FAILED)
                    self.assertIn("gate", result["timings"])
                gate.assert_not_called()

    def test_falsey_injected_model_is_used(self):
        class FalseyModel:
            def __bool__(self):
                return False

            def totals(self):
                return USAGE

        injected = FalseyModel()
        with patch.object(answer, "gate", return_value={**ALLOWED, "allowed": False}) as gate:
            answer.answer("question", injected)
        self.assertIs(gate.call_args.args[1], injected)


if __name__ == "__main__":
    unittest.main()
