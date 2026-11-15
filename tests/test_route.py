"""Table-first, column-second routing on catalogs independent of the demo warehouse."""

import re
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

import duckdb

from gridrag import config
from gridrag.catalog import Catalog, read_catalog
from gridrag.records import Stage
from gridrag.route import RoutingTooBroad, route


def routing_catalog():
    with duckdb.connect() as connection:
        connection.execute("""
            CREATE SCHEMA core;
            CREATE TABLE core.dim_iso (iso_id INTEGER PRIMARY KEY, iso_code VARCHAR);
            CREATE TABLE core.demand (iso_id INTEGER REFERENCES core.dim_iso (iso_id),
                interval_start_local TIMESTAMP, demand_mw DOUBLE, unused DOUBLE);
            COMMENT ON TABLE core.demand IS 'Hourly demand';
            CREATE TABLE core.caiso_price (iso_id INTEGER REFERENCES core.dim_iso (iso_id), lmp DOUBLE);
            COMMENT ON TABLE core.caiso_price IS 'CAISO hub prices';
            CREATE TABLE core.ercot_price (iso_id INTEGER REFERENCES core.dim_iso (iso_id), lmp DOUBLE);
            COMMENT ON TABLE core.ercot_price IS 'ERCOT hub prices';
        """)
        catalog = read_catalog(connection, schemas=("core",))
    return Catalog.of(
        catalog.tables[name]
        for name in (
            "core.dim_iso",
            "core.demand",
            "core.caiso_price",
            "core.ercot_price",
        )
    )


CATALOG = routing_catalog()


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
            return {
                f"t{i}": {"probability": self.tables.get(name, 0.01)}
                for i, name in enumerate(CATALOG.tables)
                if self.tables.get(name, 0.01) is not None
            }
        if self.barrier:
            self.barrier.wait(timeout=2)
        table = re.search(r'CREATE TABLE "core"\."(\w+)"', input_text)[1]
        table = f"core.{table}"
        names = list(CATALOG.tables[table].columns)
        return {
            f"c{i}": {"probability": self.columns.get(table, {}).get(name, 0.01)}
            for i, name in enumerate(names)
            if self.columns.get(table, {}).get(name, 0.01) is not None
        }


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
        self.assertEqual(selected["columns"]["core.demand"], ["iso_id", "interval_start_local", "demand_mw"])
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

    def test_missing_table_score_fails_instead_of_treating_it_as_relevant(self):
        with self.assertRaisesRegex(ValueError, "Missing or invalid probability for t0"):
            route("Question?", ScoredModel({name: None for name in CATALOG.tables}), CATALOG)

    def test_missing_column_score_fails_instead_of_returning_partial_schema(self):
        model = ScoredModel({"core.demand": 0.99}, {"core.dim_iso": {"iso_id": None, "iso_code": None}})
        with self.assertRaisesRegex(ValueError, "Missing or invalid probability for c0"):
            route("Demand?", model, CATALOG)

    def test_table_budget_stops_before_column_calls(self):
        model = ScoredModel({"core.demand": 0.99, "core.ercot_price": 0.99})
        with (
            patch.object(config, "settings", replace(config.settings, max_routed_tables=2)),
            self.assertRaises(RoutingTooBroad) as raised,
        ):
            route("Compare demand and price", model, CATALOG)
        self.assertEqual(len(raised.exception.selection["tables"]), 3)
        self.assertEqual(len(model.calls), 1)


class MetadataRouteTests(unittest.TestCase):
    def setUp(self):
        tags = {
            "core.dim_iso": ("dimensions",),
            "core.demand": ("load", "forecast"),
            "core.caiso_price": ("prices",),
            "core.ercot_price": ("prices",),
        }
        self.catalog = Catalog.of(replace(table, routing_tags=tags[name]) for name, table in CATALOG.tables.items())
        self.calls = []

    def model(self, selected_tags, selected_tables=("core.demand",)):
        outer = self

        class Model:
            def decide(self, stage, input_text, questions):
                outer.calls.append(questions)
                answers = {}
                for item in questions:
                    name = item["name"]
                    if name.startswith("m"):
                        needed = item["instructions"].rsplit("Category: ", 1)[1] in selected_tags
                    elif name.startswith("t"):
                        table = re.search(r'CREATE TABLE "core"\."(\w+)"', item["instructions"])[1]
                        needed = f"core.{table}" in selected_tables
                    else:
                        needed = True
                    answers[name] = {"probability": 0.9 if needed else 0.01}
                return answers

        return Model()

    def test_only_matching_table_ddl_is_sent_and_references_recover_dimensions(self):
        selection = route("Peak demand", self.model({"load"}), self.catalog)
        self.assertEqual(selection["metadata_filter"]["candidates"], ["core.demand"])
        self.assertEqual(selection["scores"], {"core.demand": 0.9})
        self.assertEqual(selection["tables"], ["core.dim_iso", "core.demand"])
        self.assertEqual(len(self.calls[1]), 1)
        self.assertNotIn("CREATE TABLE", str(self.calls[0]))
        self.assertNotIn("caiso_price", str(self.calls))

    def test_multiple_categories_use_union_without_duplicate_candidates(self):
        selection = route(
            "Compare load, forecasts and prices", self.model({"load", "forecast", "prices"}), self.catalog
        )
        self.assertEqual(
            selection["metadata_filter"]["candidates"], ["core.demand", "core.caiso_price", "core.ercot_price"]
        )

    def test_untagged_tables_always_survive_filter(self):
        catalog = Catalog.of(
            replace(table, routing_tags=()) if name == "core.ercot_price" else table
            for name, table in self.catalog.tables.items()
        )
        selection = route("Peak demand", self.model({"load"}), catalog)
        self.assertEqual(selection["metadata_filter"]["candidates"], ["core.demand", "core.ercot_price"])

    def test_no_category_matches_falls_back_to_full_catalog(self):
        selection = route("Uncertain category", self.model(set()), self.catalog)
        self.assertEqual(selection["metadata_filter"]["fallback"], "no_matching_tags")
        self.assertEqual(selection["metadata_filter"]["candidates"], list(self.catalog.tables))

    def test_explicit_legacy_path_skips_metadata_call(self):
        selection = route("Peak demand", self.model({"load"}), self.catalog, metadata_prefilter=False)
        self.assertEqual(selection["metadata_filter"]["fallback"], "disabled")
        self.assertTrue(self.calls[0][0]["name"].startswith("t"))
        self.assertEqual(len(selection["scores"]), len(self.catalog.tables))

    def test_invalid_category_score_fails_explicitly(self):
        class MissingScore:
            def decide(self, *_):
                return {}

        with self.assertRaisesRegex(ValueError, "Missing or invalid probability for m0"):
            route("Peak demand", MissingScore(), self.catalog)
