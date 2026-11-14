"""Run a paired comparison: python -m benchmarks.run --live --repeats 3.

Without --live, evaluate deterministic hybrid fusion (no OpenAI
requests). Settings are fixed within each run. This is a development comparison,
not a held-out test. All attempts are retained.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
import statistics
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks import hybrid
from benchmarks.cases import BENCHMARK_CASES, EXPERIMENT
from benchmarks.vector import MODEL, VectorRetriever
from gridrag import config
from gridrag.answer import answer
from gridrag.catalog import Catalog, demo_catalog
from gridrag.llm import LLM, Model
from gridrag.records import Selection
from gridrag.route import RoutingTooBroad, _with_references, route
from gridrag.warehouse.evals import Case, reference_result, reference_value
from gridrag.warehouse.evaluation import assess, evaluation_question, evidence_matches, table_evidence_matches

SEED = 42
LIVE_METHODS = ("routed", "vector-hybrid-p20")
RETRIEVAL_METHODS = ("vector-hybrid-p20",)
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_CI_INDICES = (50, 1949)
TAIL_PERCENTILE = 0.95
BENCHMARK_TABLE_BUDGET = 25
BENCHMARK_SQL_OUTPUT_TOKENS = 4096


def strict_evidence(result: dict[str, Any], expected: float, tolerance: float) -> bool:
    """Check the final scalar SQL result against the expected value."""
    return evidence_matches(result, expected, tolerance)


def retrieval_metrics(case: Case, selection: Selection, catalog: Catalog) -> dict[str, Any]:
    """Measure required-table coverage and delivered schema size for an attempt."""
    selected = set(selection.get("tables", []))
    required = _with_references(catalog, set(case.tables)) if case.tables else set()
    schema = "\n\n".join(
        catalog.tables[name].selected_schema(selection["columns"][name])
        for name in selected
        if name in selection.get("columns", {})
    )
    # Candidate availability is measured before reranking; reference expansion is
    # applied so a recoverable dimension is not counted as an irretrievable miss.
    retrieval = selection.get("retrieval")
    candidates = _with_references(catalog, set(retrieval["shortlist"])) if retrieval else set(catalog.tables)
    missing_candidates = sorted(required - candidates)
    # Required source tables that cannot be recovered from another required
    # table's foreign keys. Keep broad tasks visible when k cannot cover them.
    referenced_tables = set().union(*(_with_references(catalog, {name}) - {name} for name in required))
    seeds = required - referenced_tables
    policy = (retrieval or {}).get("candidate_policy")
    return {
        "required_seed_tables": len(seeds),
        "candidate_budget_shortfall": max(0, len(seeds) - policy["candidate_top_k"]) if policy else 0,
        "candidate_table_recall": len(required & candidates) / len(required) if required else None,
        "candidate_missing_tables": missing_candidates,
        "selected_columns": sum(len(columns) for columns in selection.get("columns", {}).values()),
        "required_table_recall": len(required & selected) / len(required) if required else None,
        "all_required_tables": required <= selected if required else None,
        "selected_tables": len(selected),
        "schema_chars": len(schema),
        # Other tables may be valid alternatives; do not label this value precision.
        "extra_tables": len(selected - required) if required else None,
    }


def _mean(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    return statistics.mean(values) if values else None


def summarize(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate every attempt by method, retaining failures in accuracy totals."""
    summary = []
    for name in sorted({row["method"] for row in rows}):
        group = [row for row in rows if row["method"] == name]
        seconds = sorted(row["seconds"] for row in group)
        summary.append(
            {
                "method": name,
                "attempts": len(group),
                "accuracy": _mean(group, "correct"),
                "required_table_recall": _mean(group, "required_table_recall"),
                "candidate_table_recall": _mean(group, "candidate_table_recall"),
                "mean_selected_columns": _mean(group, "selected_columns"),
                "all_required_tables": _mean(group, "all_required_tables"),
                "median_seconds": statistics.median(seconds),
                "p95_seconds": seconds[math.ceil(TAIL_PERCENTILE * len(seconds)) - 1],
                "mean_cost_usd": _mean(group, "cost_usd"),
                "mean_schema_chars": _mean(group, "schema_chars"),
                "mean_input_tokens": _mean(group, "input_tokens"),
                "failures": sum(row.get("state") == "failed" for row in group),
            }
        )
    return summary


def paired_intervals(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Case-cluster bootstrap preserves repeated attempts within each question."""
    baseline = "vector-hybrid-p20"
    differences = []
    for case in BENCHMARK_CASES:
        by_method = {
            name: [row["correct"] for row in rows if row["case"] == case.id and row["method"] == name]
            for name in ("routed", baseline)
        }
        if all(by_method.values()):
            differences.append(statistics.mean(by_method["routed"]) - statistics.mean(by_method[baseline]))
    if not differences:
        return []
    rng = random.Random(SEED)
    samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(BOOTSTRAP_SAMPLES))
    return [
        {
            "comparison": "routed minus " + baseline,
            "accuracy_delta": statistics.mean(differences),
            "ci95": [samples[index] for index in BOOTSTRAP_CI_INDICES],
            "independent_cases": len(differences),
        }
    ]


@dataclass(frozen=True)
class Attempt:
    """One scheduled method evaluation of a frozen benchmark case."""

    case: Case
    method: str
    repeat: int


def scheduled_attempts(cases: Sequence[Case], methods: Sequence[str], repeats: int) -> Iterator[Attempt]:
    """Keep the seeded case/method order independent of execution and scoring."""
    rng = random.Random(SEED)
    for repeat in range(repeats):
        shuffled_cases = list(cases)
        rng.shuffle(shuffled_cases)
        for case in shuffled_cases:
            order = list(methods)
            rng.shuffle(order)
            yield from (Attempt(case, method, repeat) for method in order)


def live_attempt(
    case: Case,
    catalog: Catalog,
    retriever: Callable[[str, Model, Catalog], Selection],
    references: Mapping[str, float | dict[str, Any]],
) -> tuple[dict[str, Any], Selection | None]:
    """Score a model-backed answer against the shared evaluation contract."""
    with closing(LLM(api_key=config.settings.openai_api_key)) as llm:
        result = answer(evaluation_question(case), llm=llm, catalog=catalog, retriever=retriever)
    checks = assess(case, result)
    numeric = None
    if case.sql:
        compare = table_evidence_matches if case.result_kind == "table" else strict_evidence
        numeric = compare(result, references[case.id], case.tolerance)
    # Accuracy and diagnostic checks share the evaluation suite's scoring contract.
    row = {
        "state": result["state"],
        "correct": checks["correct"],
        "checks_passed": checks["passed"],
        "cost_usd": result["usage"]["cost_usd"],
        "input_tokens": result["usage"]["input_tokens"],
        "output_tokens": result["usage"]["output_tokens"],
        "result": result,
        "strict_numeric_evidence": numeric,
        "checks": checks["checks"],
    }
    return row, result.get("route")


def retrieval_attempt(
    case: Case, catalog: Catalog, retriever: Callable[[str, Model | None, Catalog], Selection]
) -> tuple[dict[str, Any], Selection]:
    """Record deterministic retrieval, preserving selections that exceed the budget."""
    try:
        selection = retriever(case.question, None, catalog)
        state = "retrieved"
    except RoutingTooBroad as exc:
        selection, state = exc.selection, "clarification"
    return {"state": state, "correct": None, "cost_usd": None, "input_tokens": None}, selection


def run_attempt(
    attempt: Attempt,
    catalog: Catalog,
    vector: VectorRetriever,
    references: Mapping[str, float | dict[str, Any]],
    *,
    live: bool,
) -> dict[str, Any]:
    """Record one scheduled attempt with elapsed time and retrieval diagnostics."""
    case, method = attempt.case, attempt.method
    if method not in LIVE_METHODS:
        raise ValueError(f"Unknown comparison method: {method}")
    retriever = route if method == "routed" else vector.retrieve_hybrid
    started = time.perf_counter()
    if live:
        row, selection = live_attempt(case, catalog, retriever, references)
    else:
        row, selection = retrieval_attempt(case, catalog, retriever)
    row.update(
        {
            "case": case.id,
            "split": "development",
            "method": method,
            "repeat": attempt.repeat,
            "seconds": time.perf_counter() - started,
        }
    )
    if selection:
        row.update(retrieval_metrics(case, selection, catalog))
    elif case.tables:
        row.update(required_table_recall=0.0, all_required_tables=False, schema_chars=0)
    return row


def benchmark_manifest(args: argparse.Namespace, vector: VectorRetriever) -> dict[str, Any]:
    """Capture settings and fixture hashes needed to reproduce a benchmark run."""
    return {
        "format_version": 8,
        "experiment": EXPERIMENT,
        "scoring_version": "strict-sql-evidence-v3",
        "created_utc": datetime.now(UTC).isoformat(),
        "live": args.live,
        "repeats": args.repeats,
        "cases": len(BENCHMARK_CASES),
        "embedding_model": MODEL,
        "models": {"routing": config.settings.decisions_model, "sql": config.settings.answer_model},
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("qdrant-client", "fastembed", "openai", "duckdb")
        },
        "schema_sha256": vector.schema_sha256,
        "cases_sha256": hashlib.sha256(repr(BENCHMARK_CASES).encode()).hexdigest(),
        "index_seconds": vector.index_seconds,
        "seed": SEED,
        "selection_threshold": config.settings.route_min_probability,
        "column_threshold": config.settings.route_min_column_probability,
        "column_workers": config.settings.route_column_workers,
        "methods": list(LIVE_METHODS if args.live else RETRIEVAL_METHODS),
        "max_routed_tables": config.settings.max_routed_tables,
        "sql_max_output_tokens": config.settings.answer_max_output_tokens,
        "grounding": {
            "version": "iso-entities-v1",
            "shared_by_all_methods": True,
            "curated_vocabulary": True,
            "scope": "ISO entities only",
            "entries": len(demo_catalog().vocabulary),
            "sha256": hashlib.sha256(repr(demo_catalog().vocabulary).encode()).hexdigest(),
        },
        "pipeline_version": "schema-driven-iso-entities-v1",
        "hybrid": {
            **hybrid.candidate_policy(len(vector.catalog.tables)),
            "weights": hybrid.WEIGHTS,
            "reranker": config.settings.decisions_model if args.live else "fusion-only",
            "reranker_endpoint": "/v1/decisions" if args.live else None,
            "fusion_version": hybrid.FUSION_VERSION,
        },
        "cost_basis": "Configured model token rates; excludes local embedding compute, Qdrant hosting and failed-call billing",
        "rates_per_million": {
            name: {"input": rates.input, "cached_input": rates.cached_input, "output": rates.output}
            for name, rates in config.settings.prices.items()
        },
    }


def save_report(output: Path, manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    """Replace the report atomically without sharing a temporary path with other runs."""
    report = {
        "manifest": manifest,
        "summary": summarize(rows),
        "paired_intervals": paired_intervals(rows) if manifest["live"] else [],
        "runs": rows,
    }
    payload = json.dumps(report, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, prefix=output.name + ".", suffix=".tmp", delete=False
    )
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(payload)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def run_benchmark(
    args: argparse.Namespace,
    catalog: Catalog,
    vector: VectorRetriever,
    references: Mapping[str, float | dict[str, Any]],
) -> None:
    """Checkpoint each completed attempt before reporting CLI progress."""
    manifest = benchmark_manifest(args, vector)
    methods = LIVE_METHODS if args.live else RETRIEVAL_METHODS
    rows = []
    for attempt in scheduled_attempts(BENCHMARK_CASES, methods, args.repeats):
        row = run_attempt(attempt, catalog, vector, references, live=args.live)
        rows.append(row)
        save_report(args.output, manifest, rows)
        print(
            f"{len(rows)} {attempt.method} {attempt.case.id}: {row['state']} "
            f"correct={row['correct']} {row['seconds']:.2f}s",
            flush=True,
        )
    print(f"Saved {len(rows)} attempts to {args.output}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make paid model calls with the local configured key")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    parser.add_argument(
        "--max-tables",
        type=int,
        default=BENCHMARK_TABLE_BUDGET,
        help="Shared evaluation-only table budget, including references (default: 25)",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.max_tables < BENCHMARK_TABLE_BUDGET:
        parser.error("--max-tables must allow the 23-table broad price comparison (minimum: 25)")
    if args.live and not config.settings.openai_api_key:
        parser.error("Set OPENAI_API_KEY locally before using --live")
    return args


def main() -> None:
    """Run the benchmark with validated CLI settings and scoped resources."""
    args = _parse_args()
    catalog = demo_catalog()
    # Preflight every reference before incurring model usage.
    references = {
        case.id: reference_result(case) if case.result_kind == "table" else reference_value(case)
        for case in BENCHMARK_CASES
        if case.sql
    }
    original_settings = config.settings
    try:
        # All compared methods share the larger context budget. The app's default stays unchanged.
        config.settings = replace(
            original_settings, max_routed_tables=args.max_tables, answer_max_output_tokens=BENCHMARK_SQL_OUTPUT_TOKENS
        )
        with closing(VectorRetriever(catalog, args.url)) as vector:
            run_benchmark(args, catalog, vector, references)
    finally:
        config.settings = original_settings


if __name__ == "__main__":
    main()
