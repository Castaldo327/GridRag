"""Build explicit public JSON artifacts from fictional data; no settings or credentials."""

import json
import re
from pathlib import Path
from typing import Any

from gridrag.catalog import Catalog, demo_catalog
from gridrag.evals.cases import CASES, Case, reference_result, reference_value

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

MAX_QUESTION_CHARS = 2000


def _demo_record(case: Case, catalog: Catalog) -> dict[str, Any]:
    if not case.demo_answer:
        raise ValueError(f"Demo {case.id!r} has no prepared answer template")
    evidence = reference_result(case)
    value = reference_value(case, evidence=evidence)
    formatted_value = f"{value:,.0f}" if case.unit == "projects" else f"{value:,.2f}"
    return {
        "id": case.id,
        "label": case.label,
        "question": case.question,
        "sql": case.sql,
        "concept": case.concept,
        "tables": [name for name in catalog.tables if re.search(rf"\b{re.escape(name)}\b", case.sql)],
        "evidence": evidence["csv"],
        "answer": case.demo_answer.format(value=formatted_value) + " All measurements are from the fictional dataset.",
    }


def build() -> None:
    """Write the frontend demo artifact using the fictional warehouse's reference queries."""
    catalog = demo_catalog()
    demos = [_demo_record(case, catalog) for case in CASES if case.label]
    payload = {
        "catalog_tables": len(catalog.tables),
        "isos": list(catalog.isos),
        "max_question_chars": MAX_QUESTION_CHARS,
        "model_ready": False,
        "requires_api_key": True,
        "presets": [{key: demo[key] for key in ("id", "label", "concept", "question")} for demo in demos],
        "demos": demos,
        "catalog": [
            {"name": table.name, "ddl": table.ddl, "routing_tags": list(table.routing_tags)}
            for table in catalog.tables.values()
        ],
    }
    (STATIC / "demo.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
