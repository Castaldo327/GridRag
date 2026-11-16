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

    def test_fresh_paired_report_cannot_be_replaced_with_historical_vector_evidence(self):
        with self.assertRaisesRegex(ValueError, "share questions"):
            refresh(self.metadata, self.previous)

    def test_incomplete_or_incompatible_sources_are_rejected(self):
        broken = deepcopy(self.metadata)
        broken["runs"].pop()
        with self.assertRaisesRegex(ValueError, "Complete paired"):
            refresh(broken, self.previous)
        broken = deepcopy(self.previous)
        broken["manifest"]["cases_sha256"] = "other questions"
        with self.assertRaisesRegex(ValueError, "share questions"):
            refresh(self.metadata, broken)
