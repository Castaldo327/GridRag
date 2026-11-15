"""The paired evaluation protects its budgets, evidence and rollout decision offline."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from benchmarks import metadata
from benchmarks.run import Attempt
from gridrag import config
from gridrag.catalog import demo_catalog
from gridrag.evals.cases import CASES


class MetadataBenchmarkTests(unittest.TestCase):
    def row(self, method, *, correct=True, behavior=False, cost=0.002, **changes):
        return {
            "suite": "example",
            "case": "peak",
            "repeat": 0,
            "method": method,
            "correct": correct,
            "checks_passed": correct,
            "behavior_case": behavior,
            "state": "answered",
            "cost_usd": cost,
            "uncached_cost_usd": cost,
            "seconds": 2.0,
            **changes,
        }

    def manifest(self):
        return {"repeats": 1, "suites": {"example": {"cases": 1, "case_ids": ["peak"]}}}

    def test_manifest_freezes_suite_budgets_and_never_copies_credentials(self):
        with patch.object(config, "settings", replace(config.settings, openai_api_key="test-secret")):
            result = metadata.manifest(metadata.suites(), 3, 2, demo_catalog())
        encoded = json.dumps(result)
        self.assertNotIn("test-secret", encoded)
        self.assertEqual(result["suites"]["benchmark"]["max_routed_tables"], 25)
        self.assertEqual(result["suites"]["regression"]["max_routed_tables"], 10)
        self.assertEqual(result["suites"]["benchmark"]["sql_max_output_tokens"], 4096)
        self.assertEqual(len(result["suites"]["regression"]["case_ids"]), 26)

    def test_rollout_requires_exact_cases_repeats_methods_and_preserves_failures(self):
        rows = [self.row("full-catalog"), self.row("metadata-filtered", cost=0.001)]
        self.assertTrue(metadata.rollout_assessment(self.manifest(), rows)["passes_observed_quality_cost_gate"])
        for changed in (
            rows[:1],
            rows + rows[:1],
            [rows[0], {**rows[1], "case": "different"}],
            [rows[0], {**rows[1], "repeat": 99}],
            [rows[0], {**rows[1], "correct": False}],
            [rows[0], {**rows[1], "cost_usd": 0.003}],
        ):
            with self.subTest(changed=changed):
                self.assertFalse(
                    metadata.rollout_assessment(self.manifest(), changed)["passes_observed_quality_cost_gate"]
                )
        assessment = metadata.rollout_assessment(
            self.manifest(),
            [
                self.row("full-catalog", behavior=True),
                self.row("metadata-filtered", behavior=True, correct=False, cost=0.001),
            ],
        )
        self.assertEqual(assessment["suites"][0]["new_behavior_failures"], ["peak"])

    def test_paired_interval_clusters_repeats_within_case(self):
        rows = [self.row(method, repeat=repeat) for method in metadata.METHODS for repeat in range(3)]
        result = metadata.paired_comparison(rows)[0]
        self.assertEqual(result["independent_cases"], 1)
        self.assertEqual(result["accuracy_delta"], 0)
        self.assertEqual(result["ci95"], [0, 0])

    def test_attempt_routes_with_explicit_toggle_and_keeps_candidate_misses(self):
        catalog = demo_catalog()
        case = CASES[0]
        row = {
            "result": {
                "usage": {
                    "per_call": [
                        {
                            "stage": "route",
                            "kind": "decisions",
                            "input_tokens": 1000,
                            "output_tokens": 0,
                            "cost_usd": 0.00001,
                            "error": None,
                        }
                    ]
                }
            },
        }
        selection = {"tables": [], "columns": {}, "scores": {}, "metadata_filter": {"candidates": []}}
        with patch.object(metadata, "live_attempt", return_value=(row, selection)) as live:
            result = metadata.run_attempt(
                Attempt(case, "metadata-filtered", 0), metadata.Suite("example", (case,), 10, 1600), catalog, {}
            )
        retriever = live.call_args.args[2]
        self.assertEqual(retriever.keywords, {"metadata_prefilter": True})
        self.assertEqual(result["candidate_tables"], 0)
        self.assertEqual(result["candidate_table_recall"], 0)
        self.assertIn("core.fact_balance_hourly", result["candidate_missing_tables"])
        self.assertAlmostEqual(result["uncached_cost_usd"], 0.0001)
        self.assertEqual(result["route_input_tokens"], 1000)

    def test_publication_preserves_evidence_and_rejects_partial_or_credential_payloads(self):
        evidence = {
            "answer": "42 MW",
            "tool_calls": [{"query": "SELECT 42", "csv": "value\n42\n"}],
            "usage": {"per_call": [{"cost_usd": 0.001}]},
        }
        rows = [self.row("full-catalog", result=evidence), self.row("metadata-filtered", cost=0.001, result=evidence)]
        with tempfile.TemporaryDirectory() as directory:
            source, output = (Path(directory) / name for name in ("raw.json", "public.json"))
            metadata.save_report(source, self.manifest(), rows[:1])
            with self.assertRaises(ValueError):
                metadata.publish_report(source, output)
            self.assertFalse(output.exists())
            metadata.save_report(source, self.manifest(), rows)
            metadata.publish_report(source, output)
            published = json.loads(output.read_text())
            self.assertEqual(published["runs"], rows)
            self.assertEqual(published["trial_summary"][0]["trial"], 1)
            with patch.object(config, "settings", replace(config.settings, openai_api_key="42 MW")):
                with self.assertRaises(ValueError):
                    metadata.publish_report(source, Path(directory) / "leak.json")
            self.assertFalse((Path(directory) / "leak.json").exists())

    def test_checkpoint_failure_preserves_previous_report(self):
        rows = [self.row("full-catalog")]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            metadata.save_report(output, self.manifest(), rows)
            previous = output.read_bytes()
            with patch.object(Path, "replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    metadata.save_report(output, self.manifest(), rows + [self.row("metadata-filtered")])
            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [output])
