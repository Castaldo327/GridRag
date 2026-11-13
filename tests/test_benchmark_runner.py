"""Scheduling, checkpoint durability, and resource ownership without external services."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from benchmarks import run
from benchmarks.cases import BENCHMARK_CASES
from benchmarks.vector import VectorRetriever
from gridrag.catalog import demo_catalog
from gridrag.route import RoutingTooBroad


class BenchmarkRunnerTests(unittest.TestCase):
    def test_manifest_identifies_generic_fusion_for_new_results(self):
        args = SimpleNamespace(live=False, repeats=1)
        vector = SimpleNamespace(schema_sha256="test-schema", index_seconds=0.)
        with patch.object(run.importlib.metadata, "version", return_value="test"):
            manifest = run.benchmark_manifest(args, vector)
        settings = manifest["hybrid"]
        self.assertEqual(manifest["pipeline_version"], "schema-driven-iso-entities-v1")
        self.assertTrue(manifest["grounding"]["curated_vocabulary"])
        self.assertTrue(manifest["grounding"]["shared_by_all_methods"])
        self.assertEqual(manifest["grounding"]["entries"], 7)
        self.assertEqual(settings["fusion_version"], "semantic-bm25-v1")
        self.assertNotIn("metadata", settings)
        self.assertEqual(set(settings["weights"]), {"semantic", "keyword"})

    def test_seeded_schedule_preserves_order_and_every_attempt(self):
        attempts = list(run.scheduled_attempts(BENCHMARK_CASES, run.LIVE_METHODS, 2))
        actual = [(attempt.repeat, attempt.case.id, attempt.method) for attempt in attempts]
        expected = {(repeat, case.id, method) for repeat in range(2)
                    for case in BENCHMARK_CASES for method in run.LIVE_METHODS}
        self.assertEqual(set(actual), expected)
        self.assertEqual(len(actual), len(expected))
        self.assertEqual(attempts, list(run.scheduled_attempts(BENCHMARK_CASES, run.LIVE_METHODS, 2)))

    def test_retrieval_clarification_keeps_selection_and_never_creates_a_model(self):
        catalog = demo_catalog()
        selection = {"tables": list(catalog.tables), "columns": {}}
        vector = Mock()
        vector.retrieve.side_effect = RoutingTooBroad(selection)
        attempt = run.Attempt(BENCHMARK_CASES[0], "vector-k21", 0)
        with patch.object(run, "LLM") as model:
            row = run.run_attempt(attempt, catalog, vector, {}, live=False)
        model.assert_not_called()
        self.assertEqual(vector.top_k, 21)
        self.assertEqual((row["state"], row["schema_chars"]), ("clarification", 0))
        self.assertEqual(row["required_table_recall"], 1)

    def test_live_failure_remains_an_attempt_and_closes_the_client(self):
        case = BENCHMARK_CASES[0]
        result = {"state": "failed", "answer": "Failed", "tool_calls": [],
                  "usage": {"cost_usd": 0., "input_tokens": 0, "output_tokens": 0}}
        with patch.object(run, "LLM") as model, patch.object(run, "answer", return_value=result):
            row, selection = run.live_attempt(case, demo_catalog(), Mock(), {case.id: 0.})
        self.assertFalse(row["correct"])
        self.assertEqual(row["state"], "failed")
        self.assertIsNone(selection)
        model.return_value.close.assert_called_once()

    def test_unexpected_live_failure_also_closes_the_client(self):
        with patch.object(run, "LLM") as model, patch.object(run, "answer", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                run.live_attempt(BENCHMARK_CASES[0], demo_catalog(), Mock(), {})
        model.return_value.close.assert_called_once()

    def test_report_replace_failure_preserves_previous_checkpoint_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            run.save_report(output, {"live": False}, [])
            previous = output.read_bytes()
            with patch.object(Path, "replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    run.save_report(output, {"live": False, "new": True}, [])
            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_interruption_retains_completed_attempts(self):
        row = {"case": "example", "method": "vector-k4", "repeat": 0,
               "state": "retrieved", "correct": None, "seconds": 1.}
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(live=False, repeats=1, output=Path(directory) / "report.json")
            with (patch.object(run, "benchmark_manifest", return_value={"live": False}),
                  patch.object(run, "run_attempt", side_effect=[row, KeyboardInterrupt]),
                  patch("sys.stdout", io.StringIO())):
                with self.assertRaises(KeyboardInterrupt):
                    run.run_benchmark(args, demo_catalog(), Mock(), {})
            self.assertEqual(json.loads(args.output.read_text())["runs"], [row])

    def test_initial_report_setup_failure_closes_the_retriever(self):
        original_settings = run.config.settings
        with (patch("sys.argv", ["benchmarks.run"]),
              patch.object(run, "reference_value", return_value=1.),
              patch.object(run, "VectorRetriever") as vector,
              patch.object(run, "benchmark_manifest", side_effect=RuntimeError)):
            with self.assertRaises(RuntimeError):
                run.main()
        vector.return_value.close.assert_called_once()
        self.assertIs(run.config.settings, original_settings)


class VectorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.encoder = Mock()
        self.encoder.passage_embed.side_effect = lambda passages: [MagicMock() for _ in passages]
        self.embedding = Mock(return_value=self.encoder)
        dependencies = {
            "fastembed": SimpleNamespace(TextEmbedding=self.embedding),
            "qdrant_client": SimpleNamespace(QdrantClient=Mock(return_value=self.client), models=Mock()),
        }
        modules = patch.dict(sys.modules, dependencies)
        modules.start()
        self.addCleanup(modules.stop)

    def test_initialization_failures_release_only_resources_already_created(self):
        for stage in ("embedding", "create_collection", "upsert"):
            with self.subTest(stage=stage):
                self.client.reset_mock(side_effect=True)
                self.embedding.side_effect = RuntimeError if stage == "embedding" else None
                if stage != "embedding":
                    getattr(self.client, stage).side_effect = RuntimeError
                with self.assertRaises(RuntimeError):
                    VectorRetriever(demo_catalog(), "http://localhost:6333")
                self.client.close.assert_called_once()
                self.assertEqual(self.client.delete_collection.call_count, int(stage == "upsert"))

    def test_close_is_idempotent_and_releases_client_when_deletion_fails(self):
        vector = VectorRetriever(demo_catalog(), "http://localhost:6333")
        self.assertEqual(vector.top_k, 21)
        self.client.delete_collection.side_effect = RuntimeError
        with self.assertRaises(RuntimeError):
            vector.close()
        vector.close()
        self.client.delete_collection.assert_called_once_with(vector.collection)
        self.client.close.assert_called_once()
