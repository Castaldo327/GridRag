"""Routing decisions with scripted probabilities: no provider calls."""

import re
import unittest
from types import SimpleNamespace

from gridrag.route import DOMAINS, render, route, schema_blocks


def scripted(families: dict, tables: dict, columns: dict | None = None):
    """A fake llm.decide: family scores for "route" (unlisted families confidently rejected at 0.01), table
    scores by position for "tables-<family>", and column scores by name for "columns-<family>" (unlisted
    columns kept at 0.99; None leaves the answer out, as an uncertain decision)."""
    def decide(stage, question, questions):
        if stage == "route":
            return {name: {"probability": families.get(name, 0.01)} for name in DOMAINS}
        if stage.startswith("columns-"):
            named = {q["name"]: (columns or {}).get(re.search(r"core\.\w+\.(\w+) \(", q["instructions"])[1], 0.99)
                     for q in questions}
            return {name: {"probability": p} for name, p in named.items() if p is not None}
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

    def test_rejected_columns_leave_the_sql_schema_but_keys_stay(self):
        unwanted = {name: 0.01 for name in ("queue_id", "project_name", "developer", "county", "state", "technology",
                                            "status_raw", "is_hybrid", "queue_date", "proposed_cod",
                                            "withdrawn_date", "completed_date")}
        llm = scripted({"queue": 0.99}, {"queue": [0.99]}, {**unwanted, "capacity_mw": 0.99})
        chosen = route("Total active solar capacity in ERCOT's queue?", llm)
        kept = chosen["columns"]["core.queue_project"]
        self.assertEqual(kept, ["project_id", "iso_id", "fuel_id", "status_code", "capacity_mw"])
        ddl = render(schema_blocks()["core.queue_project"], kept)
        self.assertIn("capacity_mw", ddl)
        self.assertNotIn("developer", ddl)
        self.assertIn("No historical status snapshots", ddl)  # the table comment survives
        self.assertFalse(chosen["fallback"])

    def test_missing_column_probability_keeps_the_column(self):
        llm = scripted({"hourly": 0.99}, {"hourly": [0.99, 0.01]}, {"net_generation_mw": None, "demand_mw": 0.99})
        chosen = route("ERCOT peak demand?", llm)
        self.assertIn("net_generation_mw", chosen["columns"]["core.fact_balance_hourly"])
        self.assertTrue(chosen["fallback"])


if __name__ == "__main__":
    unittest.main()
