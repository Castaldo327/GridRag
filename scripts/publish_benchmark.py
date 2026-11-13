"""Verify completeness and build a safe public projection of a local benchmark run."""
import hashlib
import json
from pathlib import Path

from benchmarks.cases import BENCHMARK_CASES
from benchmarks.run import LIVE_METHODS, summarize
from gridrag.warehouse.evals import reference_result, reference_value
from scripts.security_audit import local_secrets, scan


def public_report(report):
    manifest, rows = report["manifest"], report["runs"]
    if type(manifest.get("repeats")) is not int or manifest["repeats"] < 1:
        raise ValueError("A benchmark requires a positive integer attempt count")
    methods = set(manifest.get("methods", ()))
    if methods != set(LIVE_METHODS):
        raise ValueError("The capability experiment must include all three declared methods")
    if manifest.get("cases_sha256") != hashlib.sha256(repr(BENCHMARK_CASES).encode()).hexdigest():
        raise ValueError("Benchmark questions do not match the recorded run")
    expected = {(case.id, method, repeat) for case in BENCHMARK_CASES for method in methods
                for repeat in range(manifest["repeats"])}
    actual = [(row["case"], row["method"], row["repeat"]) for row in rows]
    if not manifest["live"] or set(actual) != expected or len(actual) != len(expected):
        raise ValueError("Only a complete live run with every declared case/method/repetition can be published")
    fields = {"case", "method", "repeat", "split", "state", "correct", "checks_passed", "seconds", "cost_usd",
              "input_tokens", "output_tokens", "required_table_recall", "all_required_tables", "selected_tables",
              "schema_chars", "extra_tables", "strict_numeric_evidence"}
    public_rows = [{key: value for key, value in row.items() if key in fields} for row in rows]
    for original, public in zip(rows, public_rows, strict=True):
        result = original["result"]
        public["answer"] = result["answer"]
        public["tables"] = (result.get("route") or {}).get("tables", [])
        public["queries"] = [{key: call.get(key) for key in ("query", "csv", "rows", "error", "truncated")}
                             for call in result.get("tool_calls", [])]
        public["timings"] = result["timings"]
        if "retrieval" in (result.get("route") or {}):
            public["retrieval"] = {**result["route"]["retrieval"],
                                   "rerank_scores": result["route"]["scores"]}
    numeric = {case.id for case in BENCHMARK_CASES if case.sql}
    return {"manifest": manifest, "summary": summarize(rows), "paired_intervals": report["paired_intervals"],
            "numeric_summary": summarize([row for row in rows if row["case"] in numeric]),
            "behavior_summary": summarize([row for row in rows if row["case"] not in numeric]),
            "cases": [{"id": case.id, "question": case.question, "type": case.result_kind,
                       "difficulty": case.difficulty, "category": case.category, "unit": case.unit,
                       "expected": reference_value(case) if case.result_kind == "scalar" else None,
                       "reference_csv": reference_result(case)["csv"] if case.result_kind == "table" else None}
                      for case in BENCHMARK_CASES], "runs": public_rows}


def main():
    report = public_report(json.loads(Path("artifacts/benchmark.json").read_text()))
    payload = json.dumps(report, indent=2) + "\n"
    if scan(payload.encode(), local_secrets()):
        raise ValueError("Public report failed redacted secret checks")
    Path("app/static/benchmark.json").write_text(payload)
    print(f"Saved {len(report['runs'])} completed attempts to app/static/benchmark.json (local only).")


if __name__ == "__main__":
    main()
