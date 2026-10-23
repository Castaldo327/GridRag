"""Two-level routing, so the SQL model sees only the tables a question needs.

    1. one Decisions call picks the data families (hourly, queue)
    2. per selected family, one Decisions call scores each fact table from its schema.sql comment
    3. the dimensions those facts REFERENCE are added deterministically (dim_iso always)

Uncertainty widens: a missing probability, or no family scoring confidently, selects every family, and a
table with a missing probability is kept. A confidently rejected table stays out even in a chosen family.
"""

import re

from gridrag.warehouse.build import SCHEMA

DOMAINS = {
    "hourly": ("core.fact_balance_hourly", "core.fact_generation_hourly"),
    "queue": ("core.queue_project",),
}
# Each family is asked about separately, so the wording says a family counts if ANY part of the answer
# needs it; otherwise the model scores only the request's main subject and drops one side of a comparison.
DOMAIN_QUESTIONS = {
    "hourly": (
        "Does answering the request require, even as one part or one side of a comparison, observed hourly "
        "demand (load) or generation by fuel, a demand peak, a fuel share of generation, or hourly interval counts?"
    ),
    "queue": (
        "Does answering the request require, even as one part or one side of a comparison, interconnection "
        "queue projects, proposed project capacity or historical queue status?"
    ),
}


def schema_blocks() -> dict[str, str]:
    """Each CREATE TABLE in schema.sql with the comments above it, keyed by table name."""
    return {
        m[1]: block.strip()
        for block in SCHEMA.read_text().split("\n\n")
        if (m := re.search(r"CREATE TABLE (core\.\w+)", block))
    }


def description(block: str) -> str:
    """A table's description: the comment lines above its CREATE TABLE."""
    return " ".join(line.removeprefix("--").strip() for line in block.splitlines() if line.startswith("--"))


def _families(question: str, llm) -> tuple[list[str], dict, bool]:
    answers = llm.decide(
        "route",
        question,
        [
            {"type": "predicate", "name": name, "instructions": text} for name, text in DOMAIN_QUESTIONS.items()
        ],
    )
    probabilities = {name: (answers.get(name) or {}).get("probability") for name in DOMAINS}
    fallback = any(p is None for p in probabilities.values()) or max(probabilities.values()) < 0.65
    domains = list(DOMAINS) if fallback else [name for name, p in probabilities.items() if p >= 0.2]
    return domains, probabilities, fallback


def _tables(domain: str, question: str, llm, blocks: dict[str, str]) -> dict[str, float | None]:
    facts = DOMAINS[domain]
    answers = llm.decide(
        f"tables-{domain}",
        question,
        [
            {
                "type": "predicate",
                "name": f"t{i}",
                "instructions": f"Does the question need table {table}: {description(blocks[table])}? "
                "Select every table needed to compute the answer.",
            }
            for i, table in enumerate(facts)
        ],
    )
    return {table: (answers.get(f"t{i}") or {}).get("probability") for i, table in enumerate(facts)}


def route(question: str, llm) -> dict:
    """{domains, tables, probabilities, table_probabilities, fallback}; tables start with core.dim_iso,
    then the referenced dimensions, then the selected facts."""
    domains, probabilities, fallback = _families(question, llm)
    blocks = schema_blocks()
    scores = {table: p for domain in domains for table, p in _tables(domain, question, llm, blocks).items()}
    facts = [table for table, p in scores.items() if p is None or p >= 0.2]
    dimensions = re.findall(r"REFERENCES (core\.\w+)", "\n".join(blocks[table] for table in facts))
    tables = list(dict.fromkeys(["core.dim_iso", *dimensions, *facts]))
    return {"domains": domains, "tables": tables, "probabilities": probabilities,
            "table_probabilities": scores, "fallback": fallback or any(p is None for p in scores.values())}
