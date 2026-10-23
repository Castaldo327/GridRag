"""Domain routing: one Decisions call picks the data families a question needs, so the SQL model sees
only those tables (plus dim_iso, which every family joins to).

Uncertainty widens: a missing probability, or no family scoring confidently, selects every family.
"""

import re

from gridrag.warehouse.build import SCHEMA

DOMAINS = {
    "hourly": ("core.fact_balance_hourly",),
    "queue": ("core.queue_project", "core.dim_fuel", "core.dim_queue_status"),
}
DOMAIN_QUESTIONS = {
    "hourly": "The request needs observed hourly demand (load), a demand peak hour, or hourly interval counts.",
    "queue": "The request needs interconnection queue projects, proposed project capacity or historical queue status.",
}


def schema_blocks() -> dict[str, str]:
    """Each CREATE TABLE in schema.sql with the comments above it, keyed by table name."""
    return {
        m[1]: block.strip()
        for block in SCHEMA.read_text().split("\n\n")
        if (m := re.search(r"CREATE TABLE (core\.\w+)", block))
    }


def route(question: str, llm) -> dict:
    """{domains, tables, probabilities, fallback}; tables always start with core.dim_iso."""
    answers = llm.decide(
        question,
        [
            {"type": "predicate", "name": name, "instructions": f"Is this statement true about the user request? {text}"}
            for name, text in DOMAIN_QUESTIONS.items()
        ],
    )
    probabilities = {name: (answers.get(name) or {}).get("probability") for name in DOMAINS}
    fallback = any(p is None for p in probabilities.values()) or max(probabilities.values()) < 0.65
    domains = list(DOMAINS) if fallback else [name for name, p in probabilities.items() if p >= 0.2]
    tables = ["core.dim_iso"] + [table for name in domains for table in DOMAINS[name]]
    return {"domains": domains, "tables": tables, "probabilities": probabilities, "fallback": fallback}
