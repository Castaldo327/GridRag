"""Benchmark integrity checks, without embeddings, network calls, or model use."""

import csv
import io
import unittest
from collections import Counter

from benchmarks import hybrid
from benchmarks.cases import BENCHMARK_CASES, EXPERIMENT
from benchmarks.experiment import LIVE_METHODS, cases_fingerprint, report_contract
from benchmarks.run import retrieval_metrics, summarize
from gridrag.catalog import demo_catalog
from gridrag.evals.cases import reference_result, reference_value
from gridrag.evals.scoring import evidence_matches
from gridrag.records import State
from gridrag.route import _with_references
from scripts.publish_benchmark import public_report
from scripts.security_audit import scan


class BenchmarkTests(unittest.TestCase):
    def test_capability_suite_covers_thirty_answerable_questions_in_difficulty_order(self):
        self.assertEqual(len(BENCHMARK_CASES), 30)
        self.assertEqual(
            Counter(case.difficulty for case in BENCHMARK_CASES), {"easy": 7, "medium": 8, "hard": 8, "very_hard": 7}
        )
        difficulties = ("easy", "medium", "hard", "very_hard")
        order = [difficulties.index(case.difficulty) for case in BENCHMARK_CASES]
        self.assertEqual(order, sorted(order))
        for case in BENCHMARK_CASES:
            with self.subTest(case=case.id):
                self.assertEqual(case.state, State.ANSWERED)
                self.assertTrue(case.sql)
                self.assertTrue(case.unit)

    def test_complete_price_comparison_has_every_region_product_and_fits_budget(self):
        case = next(case for case in BENCHMARK_CASES if case.id == "all_iso_prices")
        self.assertEqual(case.result_kind, "table")
        result = reference_result(case)
        rows = list(csv.DictReader(io.StringIO(result["csv"])))
        self.assertEqual(len(rows), 21)
        expected = {
            (iso, product)
            for iso in demo_catalog().isos
            for product in ("real_time_bus", "real_time_hub", "day_ahead_hub")
        }
        self.assertEqual({(row["iso_code"], row["product"]) for row in rows}, expected)
        self.assertLessEqual(len(_with_references(demo_catalog(), set(case.tables))), 25)

    def test_scalar_check_rejects_coincidental_numbers_and_truncation(self):
        def result(csv, **kwargs):
            return {"tool_calls": [{"csv": csv, **kwargs}]}

        self.assertTrue(evidence_matches(result("answer\n12.5\n"), 12.5, 0.01))
        for csv_text in ("a,b\n0,12.5\n", "a\n12.5\n0\n", "a\nnan\n", "a\ninf\n", "a\n12.6\n"):
            self.assertFalse(evidence_matches(result(csv_text), 12.5, 0.01))
        self.assertFalse(evidence_matches(result("a\n12.5\n", truncated="limit"), 12.5, 0.01))
        self.assertFalse(evidence_matches({"tool_calls": [{"csv": "a\n12.5\n"}, {"csv": "a\n9\n"}]}, 12.5, 0.01))

    def test_partial_or_duplicate_benchmarks_cannot_be_published(self):
        report = {
            "manifest": {
                "live": True,
                "experiment": EXPERIMENT,
                "repeats": 1,
                "methods": list(LIVE_METHODS),
                "cases_sha256": cases_fingerprint(BENCHMARK_CASES),
            },
            "runs": [],
        }
        with self.assertRaises(ValueError):
            public_report(report)
        rows = [{"case": c.id, "method": method, "repeat": 0} for c in BENCHMARK_CASES for method in LIVE_METHODS]
        report["runs"] = rows + [rows[0]]
        with self.assertRaises(ValueError):
            public_report(report)

    def test_empty_or_mismatched_suite_cannot_be_published(self):
        for count in (0, -1, True, 1.5):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "positive integer"):
                public_report({"manifest": {"live": True, "experiment": EXPERIMENT, "repeats": count}, "runs": []})
        with self.assertRaisesRegex(ValueError, "questions do not match"):
            public_report(
                {
                    "manifest": {
                        "live": True,
                        "experiment": EXPERIMENT,
                        "repeats": 1,
                        "methods": list(LIVE_METHODS),
                        "cases_sha256": "stale",
                    },
                    "runs": [],
                }
            )

    def test_complete_demo_tuned_run_cannot_be_republished_as_current(self):
        report = {
            "manifest": {
                "live": True,
                "experiment": EXPERIMENT,
                "repeats": 1,
                "methods": list(LIVE_METHODS),
                "cases_sha256": cases_fingerprint(BENCHMARK_CASES),
            },
            "runs": [{"case": c.id, "method": method, "repeat": 0} for c in BENCHMARK_CASES for method in LIVE_METHODS],
        }
        with self.assertRaisesRegex(ValueError, "fresh schema-driven run"):
            public_report(report)

    def test_three_trial_publication_aggregates_all_attempts_and_keeps_trial_scores(self):
        report = {
            "manifest": {
                "live": True,
                "experiment": EXPERIMENT,
                "repeats": 3,
                "methods": list(LIVE_METHODS),
                "cases_sha256": cases_fingerprint(BENCHMARK_CASES),
                **report_contract(demo_catalog()),
            },
            "paired_intervals": [],
            "runs": [],
        }
        for repeat in range(3):
            for case in BENCHMARK_CASES:
                for method in LIVE_METHODS:
                    correct = repeat < {"routed": 2, "vector-hybrid-p20": 3}[method]
                    report["runs"].append(
                        {
                            "case": case.id,
                            "method": method,
                            "repeat": repeat,
                            "correct": correct,
                            "seconds": 1.0,
                            "state": "answered" if correct else "failed",
                            "result": {"answer": "Recorded attempt", "timings": {}, "tool_calls": []},
                        }
                    )
        public = public_report(report)
        self.assertEqual(len(public["runs"]), 180)
        summaries = {s["method"]: s for s in public["summary"]}
        self.assertTrue(all(s["attempts"] == 90 for s in summaries.values()))
        self.assertAlmostEqual(summaries["routed"]["accuracy"], 2 / 3)
        self.assertEqual(summaries["routed"]["failures"], 30)
        self.assertEqual(summaries["vector-hybrid-p20"]["accuracy"], 1.0)
        self.assertEqual([trial["trial"] for trial in public["trial_summaries"]], [1, 2, 3])
        recorded_prompt = report["manifest"]["table_scoring_sha256"]
        report["manifest"]["table_scoring_sha256"] = "superseded-prompt"
        with self.assertRaisesRegex(ValueError, "fresh schema-driven run"):
            public_report(report)
        report["manifest"]["table_scoring_sha256"] = recorded_prompt
        for trial in public["trial_summaries"]:
            self.assertTrue(all(s["attempts"] == 30 for s in trial["summary"]))
        policy = hybrid.candidate_policy(len(demo_catalog().tables))
        report["manifest"]["hybrid"]["candidate_top_k"] = 60
        with self.assertRaisesRegex(ValueError, "fresh run with the 20%"):
            public_report(report)
        report["manifest"]["hybrid"]["candidate_top_k"] = policy["candidate_top_k"]
        vector_row = next(row for row in report["runs"] if row["method"] == "vector-hybrid-p20")
        names = list(demo_catalog().tables)
        vector_row["result"]["route"] = {
            "metadata_filter": {"enabled": True, "candidates": names},
            "scores": {},
            "retrieval": {"candidate_policy": policy, "dense_candidates": names[:13], "shortlist": names[:13]},
        }
        self.assertEqual(len(public_report(report)["runs"]), 180)
        for field in ("dense_candidates", "shortlist"):
            vector_row["result"]["route"]["retrieval"][field] = names[:14]
            with self.assertRaisesRegex(ValueError, "violate the 20%"):
                public_report(report)
            vector_row["result"]["route"]["retrieval"][field] = names[:13]
        report["manifest"]["grounding"]["curated_vocabulary"] = False
        with self.assertRaisesRegex(ValueError, "ISO-only entity grounding"):
            public_report(report)
        report["manifest"]["grounding"]["curated_vocabulary"] = True
        report["runs"].pop()
        with self.assertRaisesRegex(ValueError, "complete live run"):
            public_report(report)

    def test_reference_cases_are_valid_and_unique(self):
        self.assertEqual(len({c.id for c in BENCHMARK_CASES}), len(BENCHMARK_CASES))
        for case in BENCHMARK_CASES:
            if case.sql:
                with self.subTest(case=case.id):
                    if case.result_kind == "table":
                        self.assertEqual(reference_result(case)["rows"], 21)
                    else:
                        self.assertIsInstance(reference_value(case), float)

    def test_current_experiment_cannot_omit_the_hybrid_method(self):
        report = {
            "manifest": {
                "format_version": 4,
                "live": True,
                "experiment": EXPERIMENT,
                "repeats": 1,
                "methods": ["routed", "vector-k4", "vector-k6"],
            },
            "runs": [],
        }
        with self.assertRaisesRegex(ValueError, "both declared methods"):
            public_report(report)

    def test_budget_clarification_has_no_delivered_schema(self):
        catalog = demo_catalog()
        selection = {"tables": list(catalog.tables), "columns": {}}
        metrics = retrieval_metrics(BENCHMARK_CASES[0], selection, catalog)
        self.assertEqual(metrics["schema_chars"], 0)
        self.assertEqual(metrics["required_table_recall"], 1)

    def test_broad_task_records_structural_cap_shortfall_after_reference_recovery(self):
        catalog = demo_catalog()
        case = next(case for case in BENCHMARK_CASES if case.id == "all_iso_prices")
        selection = {
            "tables": [],
            "columns": {},
            "retrieval": {"shortlist": [], "candidate_policy": hybrid.candidate_policy(len(catalog.tables))},
        }
        metrics = retrieval_metrics(case, selection, catalog)
        self.assertEqual(metrics["required_seed_tables"], 21)
        self.assertEqual(metrics["candidate_budget_shortfall"], 8)
        selection.pop("retrieval")
        self.assertEqual(retrieval_metrics(case, selection, catalog)["candidate_budget_shortfall"], 0)

    def test_candidate_diagnostics_distinguish_shortlist_omissions_from_reference_recovery(self):
        catalog = demo_catalog()
        case = next(c for c in BENCHMARK_CASES if c.id == "pjm_solar_share")
        selection = {
            "tables": ["core.fact_generation_hourly", "core.dim_iso", "core.dim_fuel"],
            "columns": {},
            "retrieval": {"shortlist": ["core.fact_generation_hourly"]},
        }
        metrics = retrieval_metrics(case, selection, catalog)
        self.assertEqual(metrics["candidate_missing_tables"], ["core.fact_balance_hourly"])
        self.assertEqual(metrics["candidate_table_recall"], 0.75)
        # The fuel and ISO dimensions remain recoverable through foreign keys.
        self.assertEqual(metrics["required_table_recall"], 0.75)
        selection.pop("retrieval")
        self.assertEqual(retrieval_metrics(case, selection, catalog)["candidate_table_recall"], 1)

    def test_summary_keeps_failures_in_denominator(self):
        rows = [
            {"method": "a", "seconds": i + 1, "correct": i == 0, "state": "answered" if i == 0 else "failed"}
            for i in range(2)
        ]
        summary = summarize(rows)[0]
        self.assertEqual(summary["accuracy"], 0.5)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["p95_seconds"], 2)

    def test_secret_scan_is_redacted_and_checks_local_exact_values(self):
        secret = b"sk-" + b"a" * 40
        self.assertIn("provider credential", scan(secret))
        self.assertIn("copy of local secret", scan(b"example privatevalue", [b"privatevalue"]))
        self.assertNotIn(secret.decode(), str(scan(secret)))
