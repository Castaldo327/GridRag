"""Grounding is approved metadata scoped to the supplied catalog and selected columns."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gridrag import db
from gridrag.catalog import Catalog, Table, demo_catalog
from gridrag.grounding import DimensionValue, mentioned_regions, render_grounding
from gridrag.sql import agent


class GroundingTests(unittest.TestCase):
    def test_all_approved_values_exist_in_the_fictional_warehouse(self):
        for entry in demo_catalog().vocabulary:
            with self.subTest(entry=entry):
                literal = entry.value.replace("'", "''")
                # Fact rows need not exercise every allowed status; validate against its dimension.
                table = "core.dim_queue_status" if entry.table == "core.queue_project" else entry.table
                result = db.run_model_sql(f"SELECT count(*) FROM {table} WHERE {entry.column}='{literal}'", 1)
                self.assertNotIn("error", result)
                self.assertGreater(int(result["csv"].splitlines()[1]), 0)

    def test_sql_prompt_receives_column_scoped_vocabulary(self):
        catalog = demo_catalog()
        grounding = render_grounding(catalog.vocabulary, {"core.dim_iso": ["iso_code"]})
        self.assertIn("California, California ISO, CAISO => 'CAISO'", grounding)
        self.assertIn("Texas, ERCOT => 'ERCOT'", grounding)
        self.assertIn("'ISONE'", grounding)
        self.assertNotIn("fuel_code", grounding)
        self.assertNotIn("location_code", grounding)
        model = SimpleNamespace(respond=Mock(return_value={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "No data."}]}]}))
        agent.run(model, "California demand?", schema="schema", grounding=grounding)
        self.assertIn(grounding, model.respond.call_args.args[1])
        self.assertEqual(render_grounding(catalog.vocabulary, {"core.dim_iso": ["iso_id"]}), "")

    def test_custom_catalogs_do_not_inherit_demo_entities(self):
        table = Table.parse("CREATE TABLE example.region (code VARCHAR);")
        self.assertEqual(Catalog.of([table]).vocabulary, ())
        with self.assertRaises(ValueError):
            Catalog.of([table], vocabulary=[DimensionValue("example.region", "missing", "X", ("X",))])

    def test_region_aliases_are_whole_and_allow_location_suffixes(self):
        self.assertEqual(mentioned_regions("California and ISO New England vs Texas"), {"CAISO", "ISONE", "ERCOT"})
        self.assertEqual(mentioned_regions("NYISO_BUS_A"), {"NYISO"})
        self.assertEqual(mentioned_regions("CA TX miscellaneous"), set())
