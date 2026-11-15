"""The shared report contract for running and publishing the comparison."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from benchmarks import hybrid
from gridrag.catalog import Catalog
from gridrag.evals.cases import Case
from gridrag.route import TABLE_QUESTION

FORMAT_VERSION = 9
LIVE_METHODS = ("routed", "vector-hybrid-p20")
HYBRID_METHOD = LIVE_METHODS[1]
# Only fields that define the question, expected result, or scoring affect its hash.
CASE_FIELDS = (
    "id",
    "question",
    "sql",
    "unit",
    "tolerance",
    "state",
    "tables",
    "excluded",
    "avoid",
    "category",
    "difficulty",
    "result_kind",
)


def fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def cases_fingerprint(cases: Sequence[Case]) -> str:
    return fingerprint([{field: getattr(case, field) for field in CASE_FIELDS} for case in cases])


def report_contract(catalog: Catalog) -> dict[str, Any]:
    """Fields shared by the runner and publication checks, derived from current inputs."""
    return {
        "format_version": FORMAT_VERSION,
        "pipeline_version": "schema-driven-iso-entities-v1",
        "scoring_version": "strict-sql-evidence-v3",
        "timing_scope": "answer-pipeline-only",
        "table_scoring_sha256": fingerprint(TABLE_QUESTION),
        "grounding": {
            "version": "iso-entities-v1",
            "shared_by_all_methods": True,
            "curated_vocabulary": True,
            "scope": "ISO entities only",
            "entries": len(catalog.vocabulary),
            "sha256": fingerprint([asdict(value) for value in catalog.vocabulary]),
        },
        "hybrid": {
            **hybrid.candidate_policy(len(catalog.tables)),
            "weights": dict(hybrid.WEIGHTS),
            "fusion_version": hybrid.FUSION_VERSION,
        },
    }
