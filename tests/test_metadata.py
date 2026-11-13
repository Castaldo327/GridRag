"""Public metadata reuses fixed reference calculations and owns response snapshots."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from app import metadata
from gridrag import config
from gridrag.warehouse.evals import CASES


class MetadataTests(unittest.TestCase):
    def setUp(self):
        metadata._evaluation_metadata.cache_clear()
        self.addCleanup(metadata._evaluation_metadata.cache_clear)

    def test_repeated_reads_do_not_rerun_references_or_share_mutable_responses(self):
        cases = CASES[:1]
        with patch.object(metadata, "case_info", wraps=metadata.case_info) as calculate:
            first = metadata.evaluation_metadata(cases)
            first["evaluation_cases"][0]["question"] = "changed by a consumer"
            second = metadata.evaluation_metadata(cases)
            calculate.assert_called_once_with(cases[0])
        self.assertEqual(second["evaluation_cases"][0]["question"], cases[0].question)

    def test_database_changes_invalidate_cached_reference_metadata(self):
        with patch.object(metadata, "case_info", return_value={}) as calculate:
            metadata.evaluation_metadata(CASES[:1])
            other = config.settings.db_path.with_name("other.duckdb")
            with patch.object(config, "settings", replace(config.settings, db_path=other)):
                metadata.evaluation_metadata(CASES[:1])
        self.assertEqual(calculate.call_count, 2)
