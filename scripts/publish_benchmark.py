"""Verify completeness and build a safe public projection of a local benchmark run."""

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmarks import hybrid
from benchmarks.cases import BENCHMARK_CASES, EXPERIMENT
from benchmarks.experiment import HYBRID_METHOD, LIVE_METHODS, cases_fingerprint, report_contract
from benchmarks.run import summarize
from gridrag.catalog import demo_catalog
from gridrag.evals.cases import Case, reference_result, reference_value
from scripts.security_audit import local_secrets, scan

PUBLIC_REPORT_PATH = Path("app/static/benchmark.json")
PUBLIC_RUN_FIELDS = frozenset(
    {
        "case",
        "method",
        "repeat",
        "split",
        "state",
        "correct",
        "checks_passed",
        "seconds",
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "required_table_recall",
        "candidate_table_recall",
        "candidate_missing_tables",
        "required_seed_tables",
        "candidate_budget_shortfall",
        "selected_columns",
        "all_required_tables",
        "selected_tables",
        "schema_chars",
        "extra_tables",
        "strict_numeric_evidence",
    }
)


def _validate_completeness(manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    if type(manifest.get("repeats")) is not int or manifest["repeats"] < 1:
        raise ValueError("A benchmark requires a positive integer attempt count")
    methods = set(manifest.get("methods", ()))
    if methods != set(LIVE_METHODS):
        raise ValueError("The capability experiment must include both declared methods")
    if manifest.get("experiment") != EXPERIMENT:
        raise ValueError("Publish a fresh two-pipeline comparison")
    if manifest.get("cases_sha256") != cases_fingerprint(BENCHMARK_CASES):
        raise ValueError("Benchmark questions do not match the recorded run")
    expected = {
        (case.id, method, repeat)
        for case in BENCHMARK_CASES
        for method in methods
        for repeat in range(manifest["repeats"])
    }
    actual = [(row["case"], row["method"], row["repeat"]) for row in rows]
    if not manifest["live"] or set(actual) != expected or len(actual) != len(expected):
        raise ValueError("Only a complete live run with every declared case/method/repetition can be published")


def _validate_pipeline(manifest: Mapping[str, Any]) -> None:
    expected = report_contract(demo_catalog())
    if any(manifest.get(field) != value for field, value in expected.items() if field != "hybrid"):
        raise ValueError("Publish a fresh schema-driven run with shared ISO-only entity grounding")
    retrieval = manifest.get("hybrid", {})
    if any(
        retrieval.get(field) != expected["hybrid"][field] for field in ("weights", "fusion_version")
    ) or retrieval.get("metadata"):
        raise ValueError("Publish a fresh run with the declared fusion policy")


def _validate_candidates(manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    policy = hybrid.candidate_policy(len(demo_catalog().tables))
    if any(manifest.get("hybrid", {}).get(key) != value for key, value in policy.items()):
        raise ValueError("Publish a fresh run with the 20% combined candidate cap")
    for row in rows:
        selection = row.get("result", {}).get("route")
        if selection is not None and not selection.get("metadata_filter", {}).get("enabled"):
            raise ValueError("Both pipelines must use the shared metadata filter")
        if row["method"] != HYBRID_METHOD:
            continue
        if selection is None:
            continue  # Failures at the shared request gate remain in the denominator.
        retrieval = selection.get("retrieval", {})
        allowed = set(selection["metadata_filter"]["candidates"])
        if (
            not set(retrieval.get("dense_candidates", ())) <= allowed
            or not set(retrieval.get("shortlist", ())) <= allowed
            or retrieval.get("candidate_policy") != policy
            or len(retrieval.get("dense_candidates", ())) > policy["dense_pool"]
            or len(retrieval.get("shortlist", ())) > policy["candidate_top_k"]
        ):
            raise ValueError("Recorded vector candidates violate the 20% combined candidate cap")


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key in PUBLIC_RUN_FIELDS}
    result = row["result"]
    selection = result.get("route") or {}
    public["answer"] = result["answer"]
    public["tables"] = selection.get("tables", [])
    public["columns"] = selection.get("columns", {})
    public["queries"] = [
        {key: call.get(key) for key in ("query", "csv", "rows", "error", "truncated")}
        for call in result.get("tool_calls", [])
    ]
    public["timings"] = result["timings"]
    if "metadata_filter" in selection:
        public["metadata_filter"] = selection["metadata_filter"]
    if "retrieval" in selection:
        public["retrieval"] = {**selection["retrieval"], "rerank_scores": selection["scores"]}
    return public


def _public_case(case: Case) -> dict[str, Any]:
    return {
        "id": case.id,
        "question": case.question,
        "concept": case.concept,
        "type": case.result_kind,
        "difficulty": case.difficulty,
        "category": case.category,
        "unit": case.unit,
        "expected": reference_value(case) if case.result_kind == "scalar" else None,
        "reference_csv": reference_result(case)["csv"] if case.result_kind == "table" else None,
    }


def public_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project a complete, current live benchmark into the public report format.

    Raise ValueError when completeness or pipeline integrity checks fail.
    """
    manifest, rows = report["manifest"], report["runs"]
    _validate_completeness(manifest, rows)
    _validate_pipeline(manifest)
    _validate_candidates(manifest, rows)
    public_rows = [_public_row(row) for row in rows]
    numeric = {case.id for case in BENCHMARK_CASES if case.sql}
    return {
        "manifest": {**manifest, "gridrag_routing": "metadata-filtered", "shared_metadata_filter": True},
        "summary": summarize(rows),
        "paired_intervals": report["paired_intervals"],
        "trial_summaries": [
            {"trial": repeat + 1, "summary": summarize([row for row in rows if row["repeat"] == repeat])}
            for repeat in range(manifest["repeats"])
        ],
        "numeric_summary": summarize([row for row in rows if row["case"] in numeric]),
        "behavior_summary": summarize([row for row in rows if row["case"] not in numeric]),
        "cases": [_public_case(case) for case in BENCHMARK_CASES],
        "runs": public_rows,
    }


def main() -> None:
    """Write a verified public report from the requested local benchmark artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("artifacts/benchmark.json"))
    args = parser.parse_args()
    report = public_report(json.loads(args.input.read_text(encoding="utf-8")))
    payload = json.dumps(report, indent=2) + "\n"
    if scan(payload.encode(), local_secrets()):
        raise ValueError("Public report failed redacted secret checks")
    PUBLIC_REPORT_PATH.write_text(payload, encoding="utf-8")
    print(f"Saved {len(report['runs'])} completed attempts to {PUBLIC_REPORT_PATH} (local only).")


if __name__ == "__main__":
    main()
