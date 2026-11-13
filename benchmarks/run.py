"""Run a paired comparison: python -m benchmarks.run --live --repeats 3.

Without --live, evaluate only dense retrieval (no OpenAI requests). Settings are
predeclared, never selected using benchmark outcomes. All attempts are retained.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import random
import statistics
import time
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gridrag import config
from gridrag.answer import answer
from gridrag.catalog import Catalog, demo_catalog
from gridrag.llm import LLM
from gridrag.route import RoutingTooBroad, _with_references, route
from gridrag.warehouse.evaluation import assess, evaluation_question, evidence_matches
from gridrag.warehouse.evals import Case, reference_value
from benchmarks.cases import BENCHMARK_CASES
from benchmarks.vector import MODEL, VectorRetriever


def strict_evidence(result, expected, tolerance):
    return evidence_matches(result, expected, tolerance)


def retrieval_metrics(case, selection, catalog):
    selected = set(selection.get("tables", []))
    required = _with_references(catalog, set(case.tables)) if case.tables else set()
    schema = "\n\n".join(catalog.tables[t].selected_schema(selection["columns"][t]) for t in selected if t in selection.get("columns", {}))
    return {
        "required_table_recall": len(required & selected) / len(required) if required else None,
        "all_required_tables": required <= selected if required else None,
        "selected_tables": len(selected), "schema_chars": len(schema),
        # Other tables may be valid alternatives; do not label this value precision.
        "extra_tables": len(selected - required) if required else None,
    }


def summarize(rows):
    summary = []
    for name in sorted({r["method"] for r in rows}):
        group = [r for r in rows if r["method"] == name]
        def mean(key):
            values = [r[key] for r in group if r.get(key) is not None]
            return statistics.mean(values) if values else None
        seconds = sorted(r["seconds"] for r in group)
        summary.append({"method": name, "attempts": len(group), "accuracy": mean("correct"),
                        "required_table_recall": mean("required_table_recall"),
                        "all_required_tables": mean("all_required_tables"),
                        "median_seconds": statistics.median(seconds),
                        "p95_seconds": seconds[math.ceil(.95 * len(seconds)) - 1],
                        "mean_cost_usd": mean("cost_usd"), "mean_schema_chars": mean("schema_chars"),
                        "mean_input_tokens": mean("input_tokens"),
                        "failures": sum(r.get("state") == "failed" for r in group)})
    return summary


def paired_intervals(rows):
    """Case-cluster bootstrap preserves repeated attempts within each question."""
    results = []
    for baseline in ("vector-k4", "vector-k6"):
        differences = []
        for case in BENCHMARK_CASES:
            by_method = {name: [r["correct"] for r in rows if r["case"] == case.id and r["method"] == name]
                         for name in ("routed", baseline)}
            if all(by_method.values()):
                differences.append(statistics.mean(by_method["routed"]) - statistics.mean(by_method[baseline]))
        if not differences:
            continue
        rng = random.Random(42)
        samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
        results.append({"comparison": "routed minus " + baseline, "accuracy_delta": statistics.mean(differences),
                        "ci95": [samples[50], samples[1949]], "independent_cases": len(differences)})
    return results


SEED = 42
LIVE_METHODS = ("routed", "vector-k4", "vector-k6")
RETRIEVAL_METHODS = ("vector-k4", "vector-k6")
PUBLIC_CASE_IDS = frozenset(case.id for case in BENCHMARK_CASES[:12])


@dataclass(frozen=True)
class Attempt:
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


def live_attempt(case, catalog, retriever, references):
    llm = LLM(api_key=config.settings.openai_api_key)
    try:
        result = answer(evaluation_question(case), llm=llm, catalog=catalog, retriever=retriever)
    finally:
        llm.close()
    checks = assess(case, result)
    numeric = strict_evidence(result, references[case.id], case.tolerance) if case.sql else None
    # Accuracy and diagnostic checks share the evaluation suite's scoring contract.
    row = {
        "state": result["state"], "correct": checks["correct"], "checks_passed": checks["passed"],
        "cost_usd": result["usage"]["cost_usd"], "input_tokens": result["usage"]["input_tokens"],
        "output_tokens": result["usage"]["output_tokens"], "result": result,
        "strict_numeric_evidence": numeric, "checks": checks["checks"],
    }
    return row, result.get("route")


def retrieval_attempt(case, catalog, retriever):
    try:
        selection = retriever(case.question, None, catalog)
        state = "retrieved"
    except RoutingTooBroad as exc:
        selection, state = exc.selection, "clarification"
    return {"state": state, "correct": None, "cost_usd": None, "input_tokens": None}, selection


def run_attempt(attempt: Attempt, catalog: Catalog, vector: VectorRetriever, references, *, live: bool):
    case, method = attempt.case, attempt.method
    retriever = route if method == "routed" else vector.retrieve
    vector.top_k = 4 if method == "vector-k4" else 6
    started = time.perf_counter()
    if live:
        row, selection = live_attempt(case, catalog, retriever, references)
    else:
        row, selection = retrieval_attempt(case, catalog, retriever)
    row.update({
        "case": case.id, "split": "public" if case.id in PUBLIC_CASE_IDS else "additional",
        "method": method, "repeat": attempt.repeat, "seconds": time.perf_counter() - started,
    })
    if selection:
        row.update(retrieval_metrics(case, selection, catalog))
    elif case.tables:
        row.update(required_table_recall=0., all_required_tables=False, schema_chars=0)
    return row


def benchmark_manifest(args, vector):
    return {
        "format_version": 2, "scoring_version": "strict-final-scalar-v2",
        "created_utc": datetime.now(timezone.utc).isoformat(), "live": args.live,
        "repeats": args.repeats, "cases": len(BENCHMARK_CASES), "embedding_model": MODEL,
        "models": {"routing": config.settings.decisions_model, "sql": config.settings.answer_model},
        "versions": {p: importlib.metadata.version(p) for p in ("qdrant-client", "fastembed", "openai", "duckdb")},
        "schema_sha256": vector.schema_sha256,
        "cases_sha256": hashlib.sha256(repr(BENCHMARK_CASES).encode()).hexdigest(),
        "index_seconds": vector.index_seconds, "seed": SEED,
        "cost_basis": "Configured model token rates; excludes local embedding compute, Qdrant hosting and failed-call billing",
        "rates_per_million": {k: {"input": v.input, "cached_input": v.cached_input, "output": v.output}
                              for k, v in config.settings.prices.items()},
    }


def save_report(output: Path, manifest, rows):
    """Replace the report atomically without sharing a temporary path with other runs."""
    report = {
        "manifest": manifest, "summary": summarize(rows),
        "paired_intervals": paired_intervals(rows) if manifest["live"] else [], "runs": rows,
    }
    payload = json.dumps(report, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         prefix=output.name + ".", suffix=".tmp", delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(payload)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def run_benchmark(args, catalog, vector, references):
    manifest = benchmark_manifest(args, vector)
    methods = LIVE_METHODS if args.live else RETRIEVAL_METHODS
    rows = []
    for attempt in scheduled_attempts(BENCHMARK_CASES, methods, args.repeats):
        row = run_attempt(attempt, catalog, vector, references, live=args.live)
        rows.append(row)
        save_report(args.output, manifest, rows)
        print(f"{len(rows)} {attempt.method} {attempt.case.id}: {row['state']} "
              f"correct={row['correct']} {row['seconds']:.2f}s", flush=True)
    print(f"Saved {len(rows)} attempts to {args.output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make paid model calls with the local configured key")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--url", default="http://127.0.0.1:6333")
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.live and not config.settings.openai_api_key:
        parser.error("Set OPENAI_API_KEY locally before using --live")
    catalog = demo_catalog()
    # Preflight every reference before incurring model usage.
    references = {case.id: reference_value(case) for case in BENCHMARK_CASES if case.sql}
    with closing(VectorRetriever(catalog, args.url)) as vector:
        run_benchmark(args, catalog, vector, references)


if __name__ == "__main__":
    main()
