"""Table-first, column-second routing on catalogs independent of the demo warehouse."""

import re
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from gridrag import config
from gridrag.catalog import Catalog, Table
from gridrag.records import Stage
from gridrag.route import RoutingFailed, RoutingTooBroad, route

CATALOG = Catalog.of([
    Table.parse("CREATE TABLE core.dim_iso (iso_id INTEGER PRIMARY KEY, iso_code VARCHAR);"),
    Table.parse("-- Hourly demand\nCREATE TABLE core.demand (iso_id INTEGER REFERENCES core.dim_iso (iso_id), "
                "interval_start_local TIMESTAMP, demand_mw DOUBLE, unused DOUBLE);"),
    Table.parse("-- CAISO hub prices\nCREATE TABLE core.caiso_price (iso_id INTEGER REFERENCES core.dim_iso (iso_id), "
                "lmp DOUBLE);"),
    Table.parse("-- ERCOT hub prices\nCREATE TABLE core.ercot_price (iso_id INTEGER REFERENCES core.dim_iso (iso_id), "
                "lmp DOUBLE);"),
])


class ScoredModel:
    def __init__(self, tables, columns=None, barrier=None):
        self.tables = tables
        self.columns = columns or {}
        self.barrier = barrier
        self.calls = []
        self.lock = threading.Lock()

    def decide(self, stage, input_text, questions):
        assert stage is Stage.ROUTE
        with self.lock:
            self.calls.append((input_text, questions))
        if questions[0]["name"] == "t0":
            return {f"t{i}": {"probability": self.tables.get(name, 0.01)}
                    for i, name in enumerate(CATALOG.tables) if self.tables.get(name, 0.01) is not None}
        if self.barrier:
            self.barrier.wait(timeout=2)
        table = re.search(r"CREATE TABLE (core\.\w+)", input_text)[1]
        names = list(CATALOG.tables[table].columns)
        return {f"c{i}": {"probability": self.columns.get(table, {}).get(name, 0.01)}
                for i, name in enumerate(names) if self.columns.get(table, {}).get(name, 0.01) is not None}


class RouteTests(unittest.TestCase):
    def test_each_physical_table_is_scored_before_its_columns(self):
        model = ScoredModel(
            {"core.ercot_price": 0.99, "core.caiso_price": 0.01},
            {"core.ercot_price": {"lmp": 0.95}, "core.dim_iso": {"iso_code": 0.9}},
        )
        selected = route("ERCOT hub price?", model, CATALOG)
        self.assertEqual(selected["tables"], ["core.dim_iso", "core.ercot_price"])
        self.assertIn("core.caiso_price", selected["scores"])
        self.assertNotIn("core.caiso_price", selected["column_scores"])
        self.assertEqual(selected["columns"]["core.ercot_price"], ["iso_id", "lmp"])
        self.assertEqual(selected["columns"]["core.dim_iso"], ["iso_id", "iso_code"])
        self.assertEqual(len(model.calls), 3)  # one table call, two column calls
        self.assertEqual(len(model.calls[0][1]), len(CATALOG.tables))
        self.assertIn("CAISO hub prices", model.calls[0][1][2]["instructions"])

    def test_column_scoring_prunes_measures_but_keeps_join_and_time_columns(self):
        model = ScoredModel({"core.demand": 0.99}, {"core.demand": {"demand_mw": 0.9}})
        selected = route("Peak demand?", model, CATALOG)
        self.assertEqual(selected["tables"], ["core.dim_iso", "core.demand"])
        self.assertEqual(selected["columns"]["core.demand"],
                         ["iso_id", "interval_start_local", "demand_mw"])
        self.assertNotIn("unused", selected["columns"]["core.demand"])
        excerpt = CATALOG.tables["core.demand"].selected_schema(selected["columns"]["core.demand"])
        self.assertNotIn("unused", excerpt)
        self.assertIn("Hourly demand", excerpt)

    def test_independent_column_decisions_run_concurrently(self):
        model = ScoredModel(
            {"core.demand": 0.99, "core.ercot_price": 0.99},
            barrier=threading.Barrier(3),
        )
        with patch.object(config, "settings", replace(config.settings, route_column_workers=3)):
            selected = route("Compare demand and price", model, CATALOG)
        self.assertEqual(len(selected["tables"]), 3)

    def test_uncertain_scores_are_kept_but_mostly_missing_scores_fail(self):
        model = ScoredModel({"core.demand": None}, {"core.demand": {"demand_mw": None}})
        selected = route("Demand?", model, CATALOG)
        self.assertTrue(selected["fallback"])
        self.assertIn("core.demand", selected["tables"])
        self.assertIn("demand_mw", selected["columns"]["core.demand"])
        with self.assertRaises(RoutingFailed):
            route("Question?", ScoredModel({name: None for name in CATALOG.tables}), CATALOG)

    def test_unusable_column_decision_fails_instead_of_returning_partial_schema(self):
        model = ScoredModel({"core.demand": 0.99},
                            {"core.dim_iso": {"iso_id": None, "iso_code": None}})
        with self.assertRaises(RoutingFailed):
            route("Demand?", model, CATALOG)

    def test_table_budget_stops_before_column_calls(self):
        model = ScoredModel({"core.demand": 0.99, "core.ercot_price": 0.99})
        with (patch.object(config, "settings", replace(config.settings, max_routed_tables=2)),
              self.assertRaises(RoutingTooBroad) as raised):
            route("Compare demand and price", model, CATALOG)
        self.assertEqual(len(raised.exception.selection["tables"]), 3)
        self.assertEqual(len(model.calls), 1)
