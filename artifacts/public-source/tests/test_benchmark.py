"""Benchmark integrity checks, without embeddings, network calls, or model use."""
import unittest

from benchmarks.run import strict_evidence, retrieval_metrics, summarize
from benchmarks.cases import BENCHMARK_CASES
from gridrag.catalog import demo_catalog
from gridrag.warehouse.evals import reference_value
from scripts.publish_benchmark import public_report
from scripts.security_audit import scan
from scripts.public_release import release_files, ROOT


class BenchmarkTests(unittest.TestCase):
    def test_scalar_check_rejects_coincidental_numbers_and_truncation(self):
        def result(csv, **kwargs):
            return {"tool_calls": [{"csv": csv, **kwargs}]}
        self.assertTrue(strict_evidence(result("answer\n12.5\n"), 12.5, .01))
        for csv in ("a,b\n0,12.5\n", "a\n12.5\n0\n", "a\nnan\n", "a\ninf\n", "a\n12.6\n"):
            self.assertFalse(strict_evidence(result(csv), 12.5, .01))
        self.assertFalse(strict_evidence(result("a\n12.5\n", truncated="limit"), 12.5, .01))
        self.assertFalse(strict_evidence({"tool_calls": [{"csv": "a\n12.5\n"}, {"csv": "a\n9\n"}]}, 12.5, .01))

    def test_partial_or_duplicate_benchmarks_cannot_be_published(self):
        report = {"manifest": {"live": True, "repeats": 1}, "runs": []}
        with self.assertRaises(ValueError):
            public_report(report)
        rows = [{"case": c.id, "method": method, "repeat": 0} for c in BENCHMARK_CASES
                for method in ("routed", "vector-k4", "vector-k6")]
        report["runs"] = rows + [rows[0]]
        with self.assertRaises(ValueError):
            public_report(report)

    def test_reference_cases_are_valid_and_unique(self):
        self.assertEqual(len({c.id for c in BENCHMARK_CASES}), len(BENCHMARK_CASES))
        for case in BENCHMARK_CASES:
            if case.sql:
                with self.subTest(case=case.id):
                    self.assertIsInstance(reference_value(case), float)

    def test_budget_clarification_has_no_delivered_schema(self):
        catalog = demo_catalog()
        selection = {"tables": list(catalog.tables), "columns": {}}
        metrics = retrieval_metrics(BENCHMARK_CASES[0], selection, catalog)
        self.assertEqual(metrics["schema_chars"], 0)
        self.assertEqual(metrics["required_table_recall"], 1)

    def test_summary_keeps_failures_in_denominator(self):
        rows = [{"method": "a", "seconds": i+1, "correct": i == 0, "state": "answered" if i == 0 else "failed"}
                for i in range(2)]
        summary = summarize(rows)[0]
        self.assertEqual(summary["accuracy"], .5)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["p95_seconds"], 2)

    def test_secret_scan_is_redacted_and_checks_local_exact_values(self):
        secret = b"sk-" + b"a" * 40
        self.assertIn("provider credential", scan(secret))
        self.assertIn("copy of local secret", scan(b"example privatevalue", [b"privatevalue"]))
        self.assertNotIn(secret.decode(), str(scan(secret)))

    def test_public_snapshot_has_no_private_or_generated_directories(self):
        paths = [p.relative_to(ROOT) for p in release_files()]
        for path in paths:
            self.assertFalse(set(path.parts) & {".git", ".vercel", ".cache", "experimental", "output", "data", "artifacts"})
            self.assertNotIn(path.name, {".env", ".env.local"})
        self.assertTrue(any(str(p) == "app/static/demo.json" for p in paths))
