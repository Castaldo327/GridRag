"""Public evaluation metadata, shared by HTTP responses and the static build."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from gridrag import config
from gridrag.warehouse.evals import CASES, Case
from gridrag.warehouse.evaluation import case_info
from gridrag.warehouse.suite import EVALUATION_CASES, suite_info


def presets() -> list[dict[str, str]]:
    """Return labeled demo questions in their display order."""
    return [
        {"id": case.id, "label": case.label, "concept": case.concept, "question": case.question}
        for case in CASES
        if case.label
    ]


@lru_cache(maxsize=1)
def _evaluation_metadata(database: Path, cases: tuple[Case, ...]) -> dict[str, Any]:
    """Cache fixed reference metadata; the database path participates in the cache key."""
    return {"evaluation_cases": [case_info(case) for case in cases], "evaluation_suite": suite_info()}


def evaluation_metadata(cases: tuple[Case, ...] = EVALUATION_CASES) -> dict[str, Any]:
    """Return reference metadata that callers can mutate without changing the cache."""
    return deepcopy(_evaluation_metadata(config.settings.db_path, cases))
