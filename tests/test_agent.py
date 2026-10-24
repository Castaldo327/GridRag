"""Tool execution budgets and evidence handling with scripted model responses."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gridrag import config
from gridrag.records import Stage, State
from gridrag.sql import agent


def tool(arguments='{"query": "SELECT 1"}'):
    return {"id": "query", "output": [{"type": "function_call", "name": "run_sql",
            "call_id": "call", "arguments": arguments}]}


TEXT = {"id": "answer", "output": [{"type": "message", "content": [
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
