"""Tool execution budgets and evidence handling with scripted model responses."""

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gridrag import config
from gridrag.records import Stage, State
from gridrag.sql import agent


def tool(arguments='{"query": "SELECT 1"}'):
    return {"id": "query", "status": "completed", "output": [{"type": "function_call", "name": "run_sql",
            "call_id": "call", "arguments": arguments}]}


TEXT = {"id": "answer", "status": "completed", "output": [{"type": "message", "content": [
    {"type": "output_text", "text": "A claimed answer."},
]}]}


class AgentTests(unittest.TestCase):
    def test_bad_arguments_can_be_repaired_without_running_them(self):
        model = SimpleNamespace(respond=Mock(side_effect=[tool('[]'), tool(), TEXT]))
        progress = []
        with patch.object(agent.db, "run_model_sql", return_value={"rows": 1, "csv": "n\n1\n"}) as execute:
            result = agent.run(model, "question", schema="CREATE TABLE core.example (n INTEGER);",
                               allowed_tables={"core.example"}, on_progress=progress.append)
        execute.assert_called_once_with("SELECT 1", config.settings.sql_max_rows, {"core.example"})
        self.assertEqual(result["state"], State.ANSWERED)
        self.assertIn("bad arguments", result["tool_calls"][0]["error"])
        self.assertEqual(result["tool_calls"][1]["csv"], "n\n1\n")
        self.assertNotIn("execution_seconds", result["tool_calls"][0])
        self.assertGreaterEqual(result["tool_calls"][1]["execution_seconds"], 0)
        requests = model.respond.call_args_list
        self.assertNotIn("previous_response_id", requests[0].kwargs)
        self.assertEqual(requests[1].kwargs["previous_response_id"], "query")
        self.assertIn("bad arguments", requests[1].args[2][0]["output"])
        self.assertEqual(progress[-1]["stage"], Stage.ANSWER)
        self.assertEqual(progress[-2]["tool_calls"], result["tool_calls"])

    def test_instructions_carry_the_routed_schema_and_answer_rules(self):
        model = SimpleNamespace(respond=Mock(return_value=TEXT))
        agent.run(model, "question", schema="CREATE TABLE core.example (n INTEGER);")
        stage, instructions, model_input = model.respond.call_args.args
        self.assertEqual((stage, model_input), (Stage.SQL, "question"))
        self.assertIn("CREATE TABLE core.example (n INTEGER);", instructions)
        self.assertIn(agent.ANSWER_RULES, instructions)

    def test_prose_without_queries_is_not_presented_as_verified(self):
        model = SimpleNamespace(respond=Mock(return_value=TEXT))
        with patch.object(agent.db, "run_model_sql") as execute:
            result = agent.run(model, "question", schema="")
        execute.assert_not_called()
        self.assertEqual(result["state"], State.ABSTAINED)
        self.assertEqual(result["tool_calls"], [])
        self.assertNotIn("claimed", result["answer"])

    def test_failed_queries_do_not_turn_into_claimed_answers(self):
        model = SimpleNamespace(respond=Mock(side_effect=[tool(), TEXT]))
        with patch.object(agent.db, "run_model_sql", return_value={"error": "Invalid column"}):
            result = agent.run(model, "question", schema="")
        self.assertEqual(result["state"], State.WRITE_FAILED)
        self.assertNotIn("claimed", result["answer"])

    def test_aggregate_binder_error_gives_the_model_a_repair_hint(self):
        bad_sql = "SELECT d.iso_code, MAX(b.demand_mw) FROM core.fact_balance_hourly b JOIN core.dim_iso d USING (iso_id)"
        corrected_sql = "SELECT MAX(b.demand_mw) FROM core.fact_balance_hourly b JOIN core.dim_iso d USING (iso_id)"
        error = 'BinderException: column "iso_code" must appear in the GROUP BY clause'
        model = SimpleNamespace(respond=Mock(side_effect=[
            tool(json.dumps({"query": bad_sql})),
            tool(json.dumps({"query": corrected_sql})),
            TEXT,
        ]))
        with patch.object(agent.db, "run_model_sql", side_effect=[
            {"error": error}, {"rows": 1, "csv": "max_demand\n47517\n"},
        ]) as execute:
            result = agent.run(model, "Peak demand?", schema="")
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(result["state"], State.ANSWERED)
        self.assertEqual(result["tool_calls"][0]["error"], error)
        repair_output = json.loads(model.respond.call_args_list[1].args[2][0]["output"])
        self.assertIn("GROUP BY", repair_output["hint"])
        self.assertIn("corrected SQL", repair_output["hint"])

    def test_provider_cannot_override_tool_budget_or_execute_partial_output(self):
        multiple = tool()
        multiple["output"] *= 2
        for response, rounds in ((tool(), 1), (multiple, 5), ({**tool(), "status": "incomplete"}, 5)):
            with (self.subTest(rounds=rounds, response=response),
                  patch.object(config, "settings", replace(config.settings, sql_max_rounds=rounds)),
                  patch.object(agent.db, "run_model_sql") as execute,
                  self.assertRaises(RuntimeError)):
                agent.run(SimpleNamespace(respond=Mock(return_value=response)), "question", schema="")
            execute.assert_not_called()

    def test_invalid_continuation_metadata_never_executes_sql(self):
        responses = [{**tool(), "id": value} for value in (None, "", " ", 1)]
        responses += [{**tool(), "status": value} for value in (None, "queued", "in_progress", "cancelled")]
        for response in responses:
            with (self.subTest(response=response),
                  patch.object(agent.db, "run_model_sql") as execute,
                  self.assertRaises(RuntimeError)):
                agent.run(SimpleNamespace(respond=Mock(return_value=response)), "question", schema="")
            execute.assert_not_called()

    def test_invalid_argument_shapes_are_repairable_and_records_remain_serializable(self):
        for arguments in (None, {"query": "SELECT 1"}, '{"query": "SELECT 1", "extra": true}'):
            with self.subTest(arguments=arguments), patch.object(agent.db, "run_model_sql") as execute:
                model = SimpleNamespace(respond=Mock(side_effect=[tool(arguments), TEXT]))
                result = agent.run(model, "question", schema="")
            execute.assert_not_called()
            self.assertEqual(result["state"], State.WRITE_FAILED)
            self.assertIn("bad arguments", result["tool_calls"][0]["error"])
            self.assertIsInstance(result["tool_calls"][0]["query"], (str, type(None)))
