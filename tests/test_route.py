"""Routing decisions with scripted probabilities: no provider calls."""

import unittest
from types import SimpleNamespace

from gridrag.route import DOMAINS, route


def scripted(families: dict, tables: dict):
    """A fake llm.decide: family scores for "route" (unlisted families confidently rejected at 0.01), and
    table scores by position for "tables-<family>"."""
    def decide(stage, question, questions):
        if stage == "route":
            return {name: {"probability": families.get(name, 0.01)} for name in DOMAINS}
        scores = tables[stage.removeprefix("tables-")]
        return {q["name"]: {"probability": p} for q, p in zip(questions, scores) if p is not None}
    return SimpleNamespace(decide=decide)


class RouteTests(unittest.TestCase):
    def test_rejected_table_stays_out_and_takes_its_dimension_with_it(self):
        llm = scripted({"hourly": 0.99, "queue": 0.01}, {"hourly": [0.99, 0.01]})
        chosen = route("ERCOT peak demand?", llm)
        self.assertEqual(chosen["tables"], ["core.dim_iso", "core.fact_balance_hourly"])
        self.assertFalse(chosen["fallback"])

    def test_missing_table_probability_keeps_the_table_and_its_dimensions(self):
        llm = scripted({"hourly": 0.99, "queue": 0.01}, {"hourly": [0.99, None]})
        chosen = route("PJM gas share?", llm)
        self.assertEqual(chosen["tables"],
                         ["core.dim_iso", "core.dim_fuel", "core.fact_balance_hourly", "core.fact_generation_hourly"])
        self.assertTrue(chosen["fallback"])

    def test_shared_dimensions_are_listed_once_across_families(self):
        llm = scripted({"hourly": 0.9, "queue": 0.9}, {"hourly": [0.9, 0.9], "queue": [0.9]})
        tables = route("Compare queue capacity with generation", llm)["tables"]
        self.assertEqual(tables.count("core.dim_fuel"), 1)
        self.assertIn("core.dim_queue_status", tables)


if __name__ == "__main__":
    unittest.main()
