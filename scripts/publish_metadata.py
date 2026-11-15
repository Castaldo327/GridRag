"""Refresh GridRag results in the existing comparison, retaining recorded vector evidence."""

import argparse
import json
from copy import deepcopy
from pathlib import Path

from benchmarks.metadata import rollout_assessment
from benchmarks.run import summarize
from scripts.publish_benchmark import _public_row
from scripts.security_audit import local_secrets, scan

EXPERIMENT = "metadata-vs-recorded-reranker-30-v1"


def refresh(metadata: dict, baseline: dict) -> dict:
    """Keep the original questions and vector rows; replace only GridRag attempts."""
    manifest = metadata["manifest"]
    if (
        manifest["experiment"] != "metadata-prefilter-v1"
        or not rollout_assessment(manifest, metadata["runs"])["complete"]
    ):
        raise ValueError("Complete paired metadata results required")
    previous = baseline["manifest"]
    spec = manifest["suites"]["benchmark"]
    if (
        previous["experiment"] not in {"decisions-vs-reranker-30-v3", EXPERIMENT}
        or previous["cases_sha256"] != spec["cases_sha256"]
        or previous["table_scoring_sha256"] != manifest["table_prompt_sha256"]
        or previous["repeats"] != manifest["repeats"]
        or previous["max_routed_tables"] != spec["max_routed_tables"]
        or previous["sql_max_output_tokens"] != spec["sql_max_output_tokens"]
        or previous["models"] != {"routing": manifest["models"]["decisions"], "sql": manifest["models"]["responses"]}
    ):
        raise ValueError("Recorded comparisons must share questions, prompts, models and budgets")
    vector = [row for row in baseline["runs"] if row["method"] == "vector-hybrid-p20"]
    expected = {(case, repeat) for case in spec["case_ids"] for repeat in range(manifest["repeats"])}
    keys = [(row["case"], row["repeat"]) for row in vector]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("Complete recorded vector results required")
    routed = []
    for row in metadata["runs"]:
        if row["suite"] == "benchmark" and row["method"] == "metadata-filtered":
            public = _public_row(row)
            public.update(method="routed", source_method="metadata-filtered")
            public["metadata_filter"] = row["result"]["route"]["metadata_filter"]
            routed.append(public)
    report = deepcopy(baseline)
    report["manifest"].update(
        experiment=EXPERIMENT,
        created_utc=manifest["created_utc"],
        gridrag_routing="metadata-filtered",
        metadata_source_manifest=manifest,
    )
    vector_date = previous.get("vector_recorded_utc", previous["created_utc"])
    report["manifest"]["vector_recorded_utc"] = vector_date
    report["manifest"]["result_provenance_note"] = (
        f"GridRag uses metadata-filtered results recorded {manifest['created_utc']}. "
        f"Qdrant results are retained from {vector_date}; Qdrant was not rerun. "
        "These are separate recorded runs, not a new paired experiment. "
        "The paired metadata/full-catalog evaluation held rollout because analytical p95 rose from 8.46 to 12.22 seconds."
    )
    report["runs"] = routed + vector
    report["summary"] = summarize(report["runs"])
    report["numeric_summary"] = report["summary"]
    report["behavior_summary"] = []
    report["paired_intervals"] = []  # Separate source runs must not retain the old paired inference.
    report["trial_summaries"] = [
        {"trial": repeat + 1, "summary": summarize([row for row in report["runs"] if row["repeat"] == repeat])}
        for repeat in range(manifest["repeats"])
    ]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("benchmarks/metadata-results.json"))
    parser.add_argument("--output", type=Path, default=Path("app/static/benchmark.json"))
    args = parser.parse_args()
    report = refresh(json.loads(args.input.read_text()), json.loads(args.output.read_text()))
    payload = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if findings := scan(payload.encode(), local_secrets()):
        raise ValueError(f"Public report audit failed: {', '.join(findings)}")
    args.output.write_text(payload)


if __name__ == "__main__":
    main()
