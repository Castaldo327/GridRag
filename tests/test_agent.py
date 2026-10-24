"""Tool execution budgets and evidence handling with scripted model responses."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
            result = agent.run(model, "instructions", "question", {"core.example"}, progress.append)
        execute.assert_called_once_with("SELECT 1", agent.SQL_MAX_ROWS, {"core.example"})
        self.assertEqual(result["state"], "answered")
        self.assertIn("bad arguments", result["tool_calls"][0]["error"])
        self.assertEqual(result["tool_calls"][1]["csv"], "n\n1\n")
        requests = model.respond.call_args_list
        self.assertNotIn("previous_response_id", requests[0].kwargs)
        self.assertEqual(requests[1].kwargs["previous_response_id"], "query")
        self.assertIn("bad arguments", requests[1].args[2][0]["output"])
        self.assertEqual(progress[-1]["stage"], "answer")
        self.assertEqual(progress[-2]["tool_calls"], result["tool_calls"])


    def test_prose_without_queries_is_not_presented_as_verified(self):
        model = SimpleNamespace(respond=Mock(return_value=TEXT))
        with patch.object(agent.db, "run_model_sql") as execute:
            result = agent.run(model, "instructions", "question")
        execute.assert_not_called()
        self.assertEqual(result["state"], "abstained")
        self.assertEqual(result["tool_calls"], [])
        self.assertNotIn("claimed", result["answer"])

    def test_failed_queries_do_not_turn_into_claimed_answers(self):
        model = SimpleNamespace(respond=Mock(side_effect=[tool(), TEXT]))
        with patch.object(agent.db, "run_model_sql", return_value={"error": "Invalid column"}):
            result = agent.run(model, "instructions", "question")
        self.assertEqual(result["state"], "write_failed")
        self.assertNotIn("claimed", result["answer"])

    def test_provider_cannot_override_tool_budget_or_execute_partial_output(self):
        multiple = tool()
        multiple["output"] *= 2
        for response, rounds in ((tool(), 1), (multiple, 5), ({**tool(), "status": "incomplete"}, 5)):
            with (self.subTest(rounds=rounds, response=response),
                  patch.object(agent, "SQL_MAX_ROUNDS", rounds),
                  patch.object(agent.db, "run_model_sql") as execute,
                  self.assertRaises(RuntimeError)):
                agent.run(SimpleNamespace(respond=Mock(return_value=response)), "instructions", "question")
            execute.assert_not_called()
