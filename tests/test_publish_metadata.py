"""Refresh recorded results without changing the existing comparison's scope."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.publish_metadata import refresh


class RefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = json.loads(Path("benchmarks/metadata-results.json").read_text())
        cls.previous = json.loads(Path("app/static/benchmark.json").read_text())

    def test_refresh_keeps_questions_vector_evidence_and_existing_method_keys(self):
        report = refresh(self.metadata, self.previous)
        self.assertEqual(report["cases"], self.previous["cases"])
        self.assertEqual(
            [row for row in report["runs"] if row["method"] == "vector-hybrid-p20"],
            [row for row in self.previous["runs"] if row["method"] == "vector-hybrid-p20"],
        )
        routed = [row for row in report["runs"] if row["method"] == "routed"]
        self.assertEqual(len(report["runs"]), 180)
        self.assertEqual(len(routed), 90)
        self.assertEqual(sum(row["correct"] for row in routed), 86)
        self.assertTrue(all(row["metadata_filter"]["enabled"] for row in routed))
        self.assertAlmostEqual(sum(row["cost_usd"] for row in routed) / 90, 0.0024695502222222224)
        self.assertEqual(report["paired_intervals"], [])
        self.assertIn("Qdrant was not rerun", report["manifest"]["result_provenance_note"])
        self.assertEqual(refresh(self.metadata, report), report)

    def test_incomplete_or_incompatible_sources_are_rejected(self):
        broken = deepcopy(self.metadata)
        broken["runs"].pop()
        with self.assertRaisesRegex(ValueError, "Complete paired"):
            refresh(broken, self.previous)
        broken = deepcopy(self.previous)
        broken["manifest"]["cases_sha256"] = "other questions"
        with self.assertRaisesRegex(ValueError, "share questions"):
            refresh(self.metadata, broken)
