"""Routing contracts independent of the warehouse's products and column types."""

import unittest

import duckdb

from gridrag.catalog import schema_blocks
from types import SimpleNamespace
from unittest.mock import patch

from gridrag.route import RoutingTooBroad, route


class RouteTests(unittest.TestCase):
    def test_demo_catalog_preserves_complete_executable_definitions(self):
        blocks = schema_blocks()
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA core")
            for block in blocks.values():
                connection.execute(block)
            count = connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'").fetchone()[0]
        self.assertEqual(count, len(blocks))
        # The UTC column comment contains a semicolon; it must not truncate the DDL.
        self.assertIn("PRIMARY KEY", blocks["core.ercot_load_forecast_hourly"])

    def test_new_schema_routes_without_product_rules_and_keeps_reference_chain(self):
        blocks = {
            "core.region": "CREATE TABLE core.region (id INTEGER PRIMARY KEY);",
            "core.station": "CREATE TABLE core.station (region INTEGER REFERENCES core.region (id));",
            "core.weather": "-- Daily precipitation\nCREATE TABLE core.weather (station INTEGER REFERENCES "
                            "core.station (id), rain DECIMAL(12,3), attributes JSON);",
            "core.unrelated": "CREATE TABLE core.unrelated (value DOUBLE);",
        }
        def decide(stage, question, questions):
            self.assertIn("Daily precipitation", questions[2]["instructions"])
            self.assertIn("attributes JSON", questions[2]["instructions"])
            return {f"t{i}": {"probability": p} for i, p in enumerate([0.01, 0.01, 0.99, 0.01])}
        with patch("gridrag.route.schema_blocks", return_value=blocks):
            selected = route("Rain by region?", SimpleNamespace(decide=decide))
        self.assertEqual(selected["tables"], list(blocks)[:3])
        self.assertFalse(selected["fallback"])

    def test_malformed_scores_widen_instead_of_dropping_context(self):
        invalid = [float("nan"), float("inf"), -1, 2, "0.9", True]
        for value in invalid:
            with self.subTest(value=value), patch("gridrag.route.schema_blocks", return_value={"core.t": "CREATE TABLE core.t (n INTEGER);"}):
                selected = route("question", SimpleNamespace(decide=lambda *args: {"t0": {"probability": value}}))
                self.assertEqual(selected["tables"], ["core.t"])
                self.assertTrue(selected["fallback"])

    def test_uncertain_tables_are_retained_but_budget_is_enforced(self):
        blocks = {f"core.t{i}": f"CREATE TABLE core.t{i} (x INTEGER);" for i in range(3)}
        llm = SimpleNamespace(decide=lambda *args: {"t0": {"probability": 0.01}})
        with patch("gridrag.route.schema_blocks", return_value=blocks):
            selected = route("Unknown measure", llm)
            self.assertEqual(selected["tables"], ["core.t1", "core.t2"])
            self.assertTrue(selected["fallback"])
            with patch("gridrag.route.MAX_ROUTED_TABLES", 1), self.assertRaises(RoutingTooBroad):
                route("Unknown measure", llm)
