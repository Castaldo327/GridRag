"""Per-call usage, cost and timing bookkeeping, with a fake client instead of the provider."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gridrag import llm
from gridrag.records import Stage


def reply(**payload):
    return SimpleNamespace(model_dump=lambda **kw: payload)


class UsageTests(unittest.TestCase):
    def test_every_call_is_recorded_with_its_stage_tokens_and_cost(self):
        def broken(**kw):
            raise TimeoutError("provider timed out")

        fake = SimpleNamespace(
            decisions=SimpleNamespace(create=lambda **kw: reply(
                answers=[{"name": "relevant", "probability": 0.9}], usage={"input_tokens": 1000, "output_tokens": 0},
            )),
            responses=SimpleNamespace(create=lambda **kw: reply(output=[], usage={
                "input_tokens": 3000, "input_tokens_details": {"cached_tokens": 2000}, "output_tokens": 100,
            })),
        )
        model = llm.LLM()
        with patch.object(llm, "client", return_value=fake):
            model.decide(Stage.GATE, "question", [])
            model.respond(Stage.SQL, "instructions", "question")
            fake.responses.create = broken
            with self.assertRaises(TimeoutError):
                model.respond(Stage.SQL, "instructions", "question")
        totals = model.totals()
        self.assertEqual([(c["stage"], c["kind"]) for c in totals["per_call"]],
                         [("gate", "decisions"), ("sql", "responses"), ("sql", "responses")])
        self.assertEqual((totals["calls"], totals["failed_calls"]), (3, 1))
        self.assertEqual((totals["input_tokens"], totals["cached_tokens"], totals["output_tokens"]), (4000, 2000, 100))
        # decisions: 1000 × $0.10/M; responses: 1000 uncached × $0.10 + 2000 cached × $0.01 + 100 out × $0.50
        self.assertAlmostEqual(totals["cost_usd"], (100 + 100 + 20 + 50) / 1e6)


if __name__ == "__main__":
    unittest.main()
