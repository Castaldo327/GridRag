"""Routing contracts on small catalogs, independent of the warehouse's products and column types."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from gridrag import config
from gridrag.catalog import Catalog, Family, Table
from gridrag.records import Stage
from gridrag.route import RoutingFailed, RoutingTooBroad, route

PRICES = Catalog.of(
    [Table.parse("CREATE TABLE core.dim_iso (iso_id SMALLINT PRIMARY KEY);"),
     Table.parse("CREATE TABLE core.demand (iso_id SMALLINT REFERENCES core.dim_iso (iso_id), mw DOUBLE);"),
     *(Table.parse(f"CREATE TABLE core.{iso}_price (iso_id SMALLINT REFERENCES core.dim_iso (iso_id), lmp DOUBLE);")
       for iso in ("caiso", "ercot", "pjm"))],
    [Family("core.<iso>_price", "-- One table per ISO. Hub prices.\nCREATE TABLE core.<iso>_price (lmp DOUBLE);",
            {"CAISO": "core.caiso_price", "ERCOT": "core.ercot_price", "PJM": "core.pjm_price"})],
)


def scored(units, isos=()):
    """A Decisions stand-in returning these probabilities for the routed units, then the ISOs, in order."""
    answers = {**{f"t{i}": {"probability": p} for i, p in enumerate(units) if p is not None},
               **{f"iso{i}": {"probability": p} for i, p in enumerate(isos) if p is not None}}
    return SimpleNamespace(decide=lambda stage, question, questions: answers)


class RouteTests(unittest.TestCase):
    def test_new_schema_routes_without_product_rules_and_keeps_reference_chain(self):
        catalog = Catalog.of([
            Table.parse("CREATE TABLE core.region (id INTEGER PRIMARY KEY);"),
            Table.parse("CREATE TABLE core.station (region INTEGER REFERENCES core.region (id));"),
            Table.parse("-- Daily precipitation\nCREATE TABLE core.weather (station INTEGER REFERENCES "
                        "core.station (id), rain DECIMAL(12,3), attributes JSON);"),
            Table.parse("CREATE TABLE core.unrelated (value DOUBLE);"),
        ])

        def decide(stage, question, questions):
            self.assertEqual(stage, Stage.ROUTE)
            self.assertEqual(len(questions), 4)  # no families, so no ISO questions
            self.assertIn("Daily precipitation", questions[2]["instructions"])
            self.assertIn("attributes JSON", questions[2]["instructions"])
            return {f"t{i}": {"probability": p} for i, p in enumerate([0.01, 0.01, 0.99, 0.01])}

        selected = route("Rain by region?", SimpleNamespace(decide=decide), catalog)
        self.assertEqual(selected["tables"], ["core.region", "core.station", "core.weather"])
        self.assertFalse(selected["fallback"])

    def test_a_family_is_scored_once_and_keeps_only_the_requested_isos(self):
        def decide(stage, question, questions):
            self.assertEqual([q["name"] for q in questions], ["t0", "t1", "t2", "iso0", "iso1", "iso2"])
            self.assertIn("Hub prices", questions[2]["instructions"])
            self.assertIn("PJM", questions[5]["instructions"])
            return scored([0.01, 0.01, 0.97], [0.95, 0.02, 0.9]).decide(stage, question, questions)

        selected = route("CAISO and PJM hub prices?", SimpleNamespace(decide=decide), PRICES)
        self.assertEqual(selected["tables"], ["core.dim_iso", "core.caiso_price", "core.pjm_price"])
        self.assertEqual(selected["scores"], {"core.dim_iso": 0.01, "core.demand": 0.01, "core.<iso>_price": 0.97})
        self.assertEqual(selected["iso_scores"], {"CAISO": 0.95, "ERCOT": 0.02, "PJM": 0.9})

    def test_iso_choice_only_matters_for_families(self):
        selected = route("ERCOT demand?", scored([0.01, 0.99, 0.01], [0.01, 0.99, 0.01]), PRICES)
        self.assertEqual(selected["tables"], ["core.dim_iso", "core.demand"])

    def test_when_no_iso_stands_out_every_iso_is_kept(self):
        selected = route("Hub prices?", scored([0.01, 0.01, 0.9], [0.01, 0.01, 0.01]), PRICES)
        self.assertEqual(selected["tables"], ["core.dim_iso", "core.caiso_price", "core.ercot_price", "core.pjm_price"])

    def test_malformed_scores_widen_instead_of_dropping_context(self):
        for value in [float("nan"), float("inf"), -1, 2, "0.9", True]:
            with self.subTest(value=value):
                selected = route("CAISO hub prices?", scored([0.01, 0.01, value], [0.9, 0.01, value]), PRICES)
                self.assertEqual(selected["tables"], ["core.dim_iso", "core.caiso_price", "core.pjm_price"])
                self.assertTrue(selected["fallback"])

    def test_mostly_unusable_scores_are_a_routing_failure(self):
        for llm in (SimpleNamespace(decide=lambda *args: {}), scored([0.9, None, None], [None, None, 0.9])):
            with self.subTest(llm=llm), self.assertRaises(RoutingFailed):
                route("Hub prices?", llm, PRICES)

    def test_budget_is_enforced_after_expanding_families(self):
        llm = scored([0.01, 0.01, 0.9], [0.9, 0.9, 0.9])
        self.assertEqual(len(route("Hub prices?", llm, PRICES)["tables"]), 4)
        with (patch.object(config, "settings", replace(config.settings, max_routed_tables=3)),
              self.assertRaises(RoutingTooBroad) as raised):
            route("Hub prices?", llm, PRICES)
        self.assertEqual(len(raised.exception.selection["tables"]), 4)  # the selection stays visible
