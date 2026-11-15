"""Paired cost/quality evaluation of full-catalog and metadata-filtered routing.

Run ``python -m benchmarks.metadata --live --repeats 3``. Every method sees the
same frozen questions, schema, gate, SQL instructions and suite-specific budgets.
Reference evidence is computed before the first paid request and never sent to
routing. This inspected development suite does not establish production accuracy.
"""

import argparse
import importlib.metadata
import json
import random
import statistics
import tempfile
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from benchmarks.cases import BENCHMARK_CASES
from benchmarks.experiment import cases_fingerprint, fingerprint
from benchmarks.run import live_attempt, scheduled_attempts, summarize
from gridrag import config
from gridrag.catalog import Catalog, demo_catalog
from gridrag.evals.cases import Case, reference_result, reference_value
from gridrag.evals.suite import EVALUATION_CASES
from gridrag.records import Stage, State
from gridrag.route import COLUMN_QUESTION, TABLE_QUESTION, _with_references, route

METHODS = ("full-catalog", "metadata-filtered")
SEED = 42
ACCURACY_MARGIN = 0.02
LATENCY_REGRESSION_RATIO = 1.10


@dataclass(frozen=True)
class Suite:
    """Frozen workload and its common runtime limits for both compared methods."""

    name: str
    cases: tuple[Case, ...]
    max_tables: int
    output_tokens: int


def suites() -> tuple[Suite, ...]:
    """Benchmark breadth uses 25 tables; application regressions retain app limits."""
    return (
        Suite("benchmark", BENCHMARK_CASES, 25, 4096),
        Suite(
            "regression", EVALUATION_CASES, config.settings.max_routed_tables, config.settings.answer_max_output_tokens
        ),
    )


def manifest(selected: Sequence[Suite], repeats: int, workers: int, catalog: Catalog) -> dict[str, Any]:
    """Fingerprint all schema metadata, scoring inputs and relevant runtime settings."""
    settings = config.settings
    # Import the routing module at runtime so this captures its category prompt as
    # well as the stable table/column prompts without copying any instructions.
    import gridrag.route as routing

    prompts = {name: value for name, value in vars(routing).items() if name.isupper() and isinstance(value, str)}
    return {
        "format_version": 1,
        "experiment": "metadata-prefilter-v1",
        "created_utc": datetime.now(UTC).isoformat(),
        "live": True,
        "split": "inspected-development",
        "timing_scope": "answer-pipeline-only",
        "seed": SEED,
        "repeats": repeats,
        "workers": workers,
        "methods": list(METHODS),
        "catalog_tables": len(catalog.tables),
        "catalog_sha256": fingerprint([asdict(table) for table in catalog.tables.values()]),
        "vocabulary_sha256": fingerprint([asdict(entry) for entry in catalog.vocabulary]),
        "prompts_sha256": fingerprint(prompts),
        "table_prompt_sha256": fingerprint(TABLE_QUESTION),
        "column_prompt_sha256": fingerprint(COLUMN_QUESTION),
        "suites": {
            suite.name: {
                "cases": len(suite.cases),
                "case_ids": [case.id for case in suite.cases],
                "cases_sha256": cases_fingerprint(suite.cases),
                "max_routed_tables": suite.max_tables,
                "sql_max_output_tokens": suite.output_tokens,
            }
            for suite in selected
        },
        "models": {"decisions": settings.decisions_model, "responses": settings.answer_model},
        "settings": {
            field.name: getattr(settings, field.name)
            for field in fields(settings)
            if field.name not in {"openai_api_key", "db_path", "prices", "route_metadata_prefilter"}
        },
        "versions": {package: importlib.metadata.version(package) for package in ("openai", "duckdb")},
        "rates_per_million": {name: asdict(rates) for name, rates in settings.prices.items()},
        "cost_basis": "Configured token-rate estimates; failed-call billing is not reported by the provider.",
        "rollout_rule": {
            "max_accuracy_loss_per_suite": ACCURACY_MARGIN,
            "no_new_behavior_failures": True,
            "lower_mean_cost_each_suite": True,
            "latency_review_ratio": LATENCY_REGRESSION_RATIO,
            "interpretation": "Practical observed gate, not a statistical noninferiority claim.",
        },
    }


def _uncached_cost(calls: Sequence[Mapping[str, Any]]) -> float:
    """Also compare token-equivalent cost without potentially order-sensitive caches."""
    return sum(
        (
            call["input_tokens"] * config.settings.prices[call["kind"]].input
            + call["output_tokens"] * config.settings.prices[call["kind"]].output
        )
        / 1e6
        for call in calls
    )


def run_attempt(attempt: Any, suite: Suite, catalog: Catalog, references: Mapping[str, Any]) -> dict[str, Any]:
    """Run one answer and retain both task correctness and stricter diagnostics."""
    retriever = partial(route, metadata_prefilter=attempt.method == "metadata-filtered")
    row, selection = live_attempt(attempt.case, catalog, retriever, references)
    calls = row["result"]["usage"]["per_call"]
    route_calls = [call for call in calls if call["stage"] == Stage.ROUTE]
    row.update(
        suite=suite.name,
        case=attempt.case.id,
        repeat=attempt.repeat,
        method=attempt.method,
        behavior_case=attempt.case.state != State.ANSWERED,
        uncached_cost_usd=_uncached_cost(calls),
        route_cost_usd=sum(call["cost_usd"] for call in route_calls),
        route_uncached_cost_usd=_uncached_cost(route_calls),
        route_input_tokens=sum(call["input_tokens"] for call in route_calls),
        calls=len(calls),
        failed_calls=sum(call.get("error") is not None for call in calls),
    )
    if selection is not None:
        candidates = set((selection.get("metadata_filter") or {}).get("candidates", selection["scores"]))
        required = _with_references(catalog, set(attempt.case.tables)) if attempt.case.tables else set()
        available = _with_references(catalog, candidates)
        selected = set(selection["tables"])
        row.update(
            candidate_tables=len(candidates),
            candidate_table_recall=len(required & available) / len(required) if required else None,
            candidate_missing_tables=sorted(required - available),
            required_table_recall=len(required & selected) / len(required) if required else None,
            all_required_tables=required <= selected if required else None,
            selected_tables=len(selected),
            selected_columns=sum(len(columns) for columns in selection["columns"].values()),
            schema_chars=sum(
                len(catalog.tables[name].selected_schema(columns)) for name, columns in selection["columns"].items()
            ),
        )
    elif attempt.case.tables:
        row.update(required_table_recall=0.0, all_required_tables=False, schema_chars=0)
    return row


def _summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for suite in sorted({row["suite"] for row in rows}):
        suite_rows = [row for row in rows if row["suite"] == suite]
        for result in summarize(suite_rows):
            group = [row for row in suite_rows if row["method"] == result["method"]]
            result["suite"] = suite
            result["checks_passed_rate"] = statistics.mean(row["checks_passed"] for row in group)
            for field in (
                "uncached_cost_usd",
                "route_cost_usd",
                "route_uncached_cost_usd",
                "route_input_tokens",
                "candidate_tables",
                "selected_tables",
                "calls",
                "failed_calls",
            ):
                values = [row[field] for row in group if row.get(field) is not None]
                result["mean_" + field] = statistics.mean(values) if values else None
            results.append(result)
    return results


def paired_comparison(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bootstrap cases as clusters; repeats stay within their source question."""
    comparisons = []
    for suite in sorted({row["suite"] for row in rows}):
        group = [row for row in rows if row["suite"] == suite]
        differences = []
        for case_id in sorted({row["case"] for row in group}):
            methods = {
                method: [row["correct"] for row in group if row["case"] == case_id and row["method"] == method]
                for method in METHODS
            }
            if all(methods.values()) and len(methods[METHODS[0]]) == len(methods[METHODS[1]]):
                differences.append(statistics.mean(methods[METHODS[1]]) - statistics.mean(methods[METHODS[0]]))
        if differences:
            rng = random.Random(SEED)
            samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
            comparisons.append(
                {
                    "suite": suite,
                    "comparison": "metadata-filtered minus full-catalog",
                    "accuracy_delta": statistics.mean(differences),
                    "ci95": [samples[50], samples[1949]],
                    "independent_cases": len(differences),
                }
            )
    return comparisons


def rollout_assessment(metadata: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A complete run is required; every attempted failure remains in the denominator."""
    expected = {
        (suite, case_id, repeat, method)
        for suite, spec in metadata["suites"].items()
        for case_id in spec["case_ids"]
        for repeat in range(metadata["repeats"])
        for method in METHODS
    }
    keys = [(row["suite"], row["case"], row["repeat"], row["method"]) for row in rows]
    expected_count = len(expected)
    complete = len(keys) == len(set(keys)) and set(keys) == expected
    suite_results = []
    for suite in metadata["suites"]:
        group = [row for row in rows if row["suite"] == suite]
        summaries = {row["method"]: row for row in _summary(group)}
        if not all(method in summaries for method in METHODS):
            continue
        old, new = (summaries[method] for method in METHODS)
        accuracy_delta = new["accuracy"] - old["accuracy"]
        old_behavior = {
            (row["case"], row["repeat"]): row["correct"]
            for row in group
            if row["method"] == METHODS[0] and row["behavior_case"]
        }
        new_behavior = {
            (row["case"], row["repeat"]): row["correct"]
            for row in group
            if row["method"] == METHODS[1] and row["behavior_case"]
        }
        regressions = sorted(
            case_id
            for (case_id, repeat), correct in old_behavior.items()
            if correct and not new_behavior.get((case_id, repeat), False)
        )
        cost_reduction = 1 - new["mean_cost_usd"] / old["mean_cost_usd"] if old["mean_cost_usd"] else None
        uncached_reduction = (
            1 - new["mean_uncached_cost_usd"] / old["mean_uncached_cost_usd"] if old["mean_uncached_cost_usd"] else None
        )
        latency_ratios = {key: new[key] / old[key] if old[key] else None for key in ("median_seconds", "p95_seconds")}
        suite_results.append(
            {
                "suite": suite,
                "accuracy_delta": accuracy_delta,
                "accuracy_acceptable": accuracy_delta >= -ACCURACY_MARGIN - 1e-12,
                "new_behavior_failures": regressions,
                "cost_reduction_fraction": cost_reduction,
                "uncached_cost_reduction_fraction": uncached_reduction,
                "cost_lower": cost_reduction is not None and cost_reduction > 0,
                "latency_ratios": latency_ratios,
                "latency_review_required": any(
                    ratio is not None and ratio > LATENCY_REGRESSION_RATIO for ratio in latency_ratios.values()
                ),
            }
        )
    return {
        "complete": complete,
        "expected_attempts": expected_count,
        "recorded_attempts": len(rows),
        "passes_observed_quality_cost_gate": complete
        and len(suite_results) == len(metadata["suites"])
        and all(
            row["accuracy_acceptable"] and not row["new_behavior_failures"] and row["cost_lower"]
            for row in suite_results
        ),
        "suites": suite_results,
        "note": "Observed development-set comparison; bootstrap intervals quantify sampling uncertainty.",
    }


def save_report(output: Path, metadata: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    """Atomically checkpoint completed paid attempts, including incomplete-run status."""
    report = {
        "manifest": metadata,
        "summary": _summary(rows),
        "trial_summary": [
            {**summary, "trial": repeat + 1}
            for repeat in range(metadata["repeats"])
            for summary in _summary([row for row in rows if row["repeat"] == repeat])
        ],
        "paired_comparison": paired_comparison(rows),
        "rollout": rollout_assessment(metadata, rows),
        "runs": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, prefix=output.name + ".", suffix=".tmp", delete=False
    )
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def publish_report(source: Path, output: Path) -> None:
    """Keep complete, independently auditable evidence in a compact tracked artifact."""
    report = json.loads(source.read_text(encoding="utf-8"))
    if not rollout_assessment(report["manifest"], report["runs"])["complete"]:
        raise ValueError("Only a complete paired report can be published")
    # Recompute aggregates with the same contract; preserve every original result,
    # including failures, SQL/CSV, selected metadata and per-call usage records.
    report["summary"] = _summary(report["runs"])
    report["trial_summary"] = [
        {**summary, "trial": repeat + 1}
        for repeat in range(report["manifest"]["repeats"])
        for summary in _summary([row for row in report["runs"] if row["repeat"] == repeat])
    ]
    report["paired_comparison"] = paired_comparison(report["runs"])
    report["rollout"] = rollout_assessment(report["manifest"], report["runs"])
    payload = json.dumps(report, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    credential = config.settings.openai_api_key
    if credential and credential in payload:
        raise ValueError("Configured credential detected in report; publication refused")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")


def run(selected: Sequence[Suite], repeats: int, workers: int, catalog: Catalog, output: Path) -> None:
    """Preflight every reference, then compare methods under identical suite settings."""
    metadata = manifest(selected, repeats, workers, catalog)
    references = {
        suite.name: {
            case.id: reference_result(case) if case.result_kind == "table" else reference_value(case)
            for case in suite.cases
            if case.sql
        }
        for suite in selected
    }
    original = config.settings
    rows: list[dict[str, Any]] = []
    save_report(output, metadata, rows)
    try:
        for suite in selected:
            config.settings = replace(
                original, max_routed_tables=suite.max_tables, answer_max_output_tokens=suite.output_tokens
            )
            attempts = list(scheduled_attempts(suite.cases, METHODS, repeats))
            # map preserves the seeded checkpoint order; each client is request-scoped.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                completed = pool.map(
                    partial(run_attempt, suite=suite, catalog=catalog, references=references[suite.name]), attempts
                )
                for row in completed:
                    rows.append(row)
                    save_report(output, metadata, rows)
                    print(
                        f"{len(rows)} {suite.name} {row['method']} {row['case']} trial={row['repeat'] + 1}: "
                        f"{row['state']} correct={row['correct']} {row['seconds']:.2f}s "
                        f"${row['cost_usd']:.6f}",
                        flush=True,
                    )
    finally:
        config.settings = original
    print(json.dumps(rollout_assessment(metadata, rows), indent=2), flush=True)
    print(f"Saved {len(rows)} attempts to {output}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Required opt-in to paid provider evaluation")
    parser.add_argument("--suite", choices=("benchmark", "regression", "all"), default="all")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1, help="Concurrent answers; recorded in the manifest")
    parser.add_argument("--output", type=Path, default=Path("artifacts/metadata-prefilter.json"))
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize provider requests; offline tests require no API")
    if not config.settings.openai_api_key:
        parser.error("Set OPENAI_API_KEY locally before using --live")
    if args.repeats < 1 or args.workers < 1:
        parser.error("--repeats and --workers must be positive")
    if args.output.exists():
        parser.error("--output already exists; choose a new path to preserve previous attempts")
    selected = tuple(suite for suite in suites() if args.suite in ("all", suite.name))
    run(selected, args.repeats, args.workers, demo_catalog(), args.output)


if __name__ == "__main__":
    main()
