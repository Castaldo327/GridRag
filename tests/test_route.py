"""Routing decisions with scripted probabilities: no provider calls."""

import re
import unittest
from types import SimpleNamespace

from gridrag.route import DOMAINS, RoutingTooBroad, render, route, schema_blocks


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
        if isinstance(scores, dict):  # by question name (iso_<ISO>, p<i>), unlisted ones rejected at 0.01
            return {q["name"]: {"probability": scores.get(q["name"], 0.01)} for q in questions}
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

    def test_one_price_table_brings_its_location_dimension(self):
        scores = {"iso_ERCOT": 0.99, "p0": 0.99}  # ERCOT × real-time bus
        chosen = route("ERCOT_BUS_A real-time LMP?", scripted({"prices": 0.99}, {"prices": scores}))
        self.assertEqual(chosen["tables"], ["core.dim_iso", "core.dim_location", "core.ercot_lmp_rt_bus_5min"])

    def test_iso_and_product_checks_keep_every_matching_pair(self):
        scores = {"iso_CAISO": 0.95, "iso_ERCOT": 0.9, "p1": 0.99, "p2": 0.8}  # two ISOs × RT hub and DA hub
        chosen = route("CAISO vs ERCOT hub spreads", scripted({"prices": 0.99}, {"prices": scores}))
        self.assertEqual(sorted(chosen["tables"][2:]), ["core.caiso_lmp_da_hub_hourly", "core.caiso_lmp_rt_hub_5min",
                                                        "core.ercot_lmp_da_hub_hourly", "core.ercot_lmp_rt_hub_5min"])
        self.assertEqual(chosen["table_probabilities"]["core.ercot_lmp_da_hub_hourly"], 0.8)  # min(ISO, product)

    def test_too_many_tables_ask_to_narrow_before_any_column_call(self):
        stages = []
        every = {f"iso_{iso}": 0.99 for iso in ("CAISO", "ERCOT", "ISONE", "MISO", "NYISO", "PJM", "SPP")}
        llm = scripted({"prices": 0.99}, {"prices": {**every, "p0": 0.99, "p1": 0.99, "p2": 0.99}})
        decide = llm.decide
        llm.decide = lambda stage, *args: stages.append(stage) or decide(stage, *args)
        with self.assertRaises(RoutingTooBroad) as raised:
            route("Compare every energy price", llm)
        self.assertEqual(len(raised.exception.selection["tables"]), 2 + 21)  # dim_iso, dim_location, 21 prices
        self.assertNotIn("columns-prices", stages)

    def test_missing_column_probability_keeps_the_column(self):
        llm = scripted({"hourly": 0.99}, {"hourly": [0.99, 0.01]}, {"net_generation_mw": None, "demand_mw": 0.99})
        chosen = route("ERCOT peak demand?", llm)
        self.assertIn("net_generation_mw", chosen["columns"]["core.fact_balance_hourly"])
        self.assertTrue(chosen["fallback"])


if __name__ == "__main__":
    unittest.main()
