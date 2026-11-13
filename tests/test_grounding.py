"""Caller-supplied vocabulary is generic, opt-in, and scoped to selected columns."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gridrag.catalog import Catalog, Table, demo_catalog
from gridrag.grounding import DimensionValue, render_grounding
from gridrag.sql import agent


class GroundingTests(unittest.TestCase):
    def test_demo_vocabulary_covers_only_the_seven_iso_entities(self):
        catalog = demo_catalog()
        self.assertEqual(len(catalog.vocabulary), 7)
        self.assertEqual({v.value for v in catalog.vocabulary}, set(catalog.isos))
        self.assertEqual({(v.table, v.column) for v in catalog.vocabulary}, {("core.dim_iso", "iso_code")})
        prompt = render_grounding(catalog.vocabulary, {"core.dim_iso": ["iso_code"]})
        self.assertIn("California, California ISO, CAISO => 'CAISO'", prompt)
        self.assertIn("Texas, ERCOT => 'ERCOT'", prompt)
        self.assertIn("New England, ISO New England, ISO-NE, ISONE => 'ISONE'", prompt)
        self.assertNotIn("fuel_code", prompt)
        self.assertNotIn("status_code", prompt)
        self.assertEqual(render_grounding(catalog.vocabulary, {"core.dim_iso": ["iso_id"]}), "")

    def test_supplied_vocabulary_is_column_scoped_and_reaches_sql(self):
        values = (DimensionValue("sales.order", "status", "shipped", ("dispatched",)),
                  DimensionValue("sales.order", "channel", "web", ("online",)))
        grounding = render_grounding(values, {"sales.order": ["status"]})
        self.assertIn("sales.order.status: dispatched => 'shipped'", grounding)
        self.assertNotIn("channel", grounding)
        self.assertNotIn("California", grounding)
        model = SimpleNamespace(respond=Mock(return_value={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "No data."}]}]}))
        agent.run(model, "How many orders were dispatched?", schema="schema", grounding=grounding)
        self.assertIn(grounding, model.respond.call_args.args[1])
        self.assertEqual(render_grounding(values, {"sales.order": ["order_id"]}), "")

    def test_custom_catalogs_do_not_inherit_entities_and_validate_supplied_columns(self):
        table = Table.parse("CREATE TABLE example.region (code VARCHAR);")
        self.assertEqual(Catalog.of([table]).vocabulary, ())
        with self.assertRaises(ValueError):
            Catalog.of([table], vocabulary=[DimensionValue("example.region", "missing", "X", ("X",))])

    def test_supplied_values_are_quoted_without_domain_assumptions(self):
        values = (DimensionValue("retail.store", "label", "O'Reilly", ("store",)),)
        self.assertIn("'O''Reilly'", render_grounding(values, {"retail.store": ["label"]}))
