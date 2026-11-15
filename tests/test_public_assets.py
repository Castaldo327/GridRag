"""Prepared demos reuse one reference result for their answer and displayed evidence."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app import metadata
from gridrag.catalog import demo_catalog
from gridrag.evals import cases
from scripts import public_assets


class PublicAssetTests(unittest.TestCase):
    def test_each_demo_executes_reference_sql_once(self):
        example = next(case for case in cases.CASES if case.label)
        with patch.object(cases.db, "run_model_sql", wraps=cases.db.run_model_sql) as execute:
            record = public_assets._demo_record(example, demo_catalog())
        execute.assert_called_once()
        self.assertEqual(record["id"], example.id)
        self.assertTrue(record["evidence"])
        self.assertIn(example.unit, record["answer"])

    def test_templates_and_presets_are_derived_from_the_same_demo_definitions(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(public_assets, "STATIC", Path(directory)):
            public_assets.build()
            payload = json.loads(Path(directory, "demo.json").read_text())
        self.assertEqual(
            payload["presets"],
            [{key: demo[key] for key in ("id", "label", "concept", "question")} for demo in payload["demos"]],
        )
        self.assertEqual(metadata.presets(), payload["presets"])

    def test_missing_template_fails_before_running_a_reference_query(self):
        example = replace(cases.CASES[0], demo_answer="")
        with patch.object(public_assets, "reference_result") as execute:
            with self.assertRaisesRegex(ValueError, "no prepared answer"):
                public_assets._demo_record(example, demo_catalog())
        execute.assert_not_called()
