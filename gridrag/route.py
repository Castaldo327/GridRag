"""Routing, so the SQL model sees only the tables and columns a question needs.

    1. one Decisions call picks the data families (hourly, five_minute, queue)
    2. per selected family, one Decisions call scores each fact table from its schema.sql comment
    3. then one call scores the non-key columns of the tables it kept, from their column comments
    4. the dimensions those facts REFERENCE are added deterministically (dim_iso always), whole

Key columns (primary key, REFERENCES, interval_start_local) are never scored and always kept, so selected
tables stay joinable and filterable. Uncertainty widens: a missing probability, or no family scoring
confidently, selects every family, and a table or column with a missing probability is kept. A confidently
rejected table stays out even in a chosen family.
"""

import re

from gridrag.warehouse.build import SCHEMA

DOMAINS = {
    "hourly": ("core.fact_balance_hourly", "core.fact_generation_hourly"),
    "five_minute": ("core.fact_load_5min", "core.fact_generation_5min"),
    "queue": ("core.queue_project",),
}
# Each family is asked about separately, so the wording says a family counts if ANY part of the answer
# needs it; otherwise the model scores only the request's main subject and drops one side of a comparison.
DOMAIN_QUESTIONS = {
    "hourly": (
        "Does answering the request require, even as one part or one side of a comparison, observed hourly "
        "demand (load) or generation by fuel, a demand peak, a fuel share of generation, or hourly interval counts?"
    ),
    "five_minute": (
        "Does answering the request require, even as one part or one side of a comparison, observed five-minute "
        "load or generation by fuel, such as a value at a five-minute timestamp like 5:05 pm?"
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


COLUMN = re.compile(r"^\s+(\w+)\s+(?:SMALLINT|INTEGER|VARCHAR|DOUBLE|TIMESTAMP|DATE|BOOLEAN)\b")


def table_columns(block: str) -> list[tuple[str, str, bool]]:
    """(name, description, is_key) per column line of a CREATE TABLE block."""
    primary = re.search(r"PRIMARY KEY \(([^)]*)\)", block)
    composite = {name.strip() for name in primary[1].split(",")} if primary else set()
    out = []
    for line in block.splitlines():
        if m := COLUMN.match(line):
            key = (m[1] in composite or m[1] == "interval_start_local"
                   or "PRIMARY KEY" in line or "REFERENCES" in line)
            out.append((m[1], line.partition("--")[2].strip(), key))
    return out


def render(block: str, keep: list[str] | None) -> str:
    """The block with only the kept column lines (all of them when keep is None)."""
    if keep is None:
        return block
    return "\n".join(line for line in block.splitlines() if not (m := COLUMN.match(line)) or m[1] in keep)


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


def _columns(domain: str, question: str, llm, blocks: dict[str, str], facts: list[str]) -> tuple[dict, bool]:
    """({table: kept column names}, any column uncertain) for one family's kept fact tables."""
    candidates = [(table, name, text) for table in facts for name, text, key in table_columns(blocks[table]) if not key]
    answers = llm.decide(
        f"columns-{domain}",
        question,
        [
            {
                "type": "predicate",
                "name": f"c{i}",
                # "Does the question need X?" scores nearly every related column high; asking whether the SQL
                # must use it separates needed columns from merely related ones.
                "instructions": f"Must the SQL that answers the question filter on, compute with, or return "
                f"{table}.{name} ({text or 'no description provided'})? Answer no if the column is only related "
                "to the topic. Keys used for joins are already included.",
            }
            for i, (table, name, text) in enumerate(candidates)
        ],
    ) if candidates else {}
    scores = {(table, name): (answers.get(f"c{i}") or {}).get("probability")
              for i, (table, name, _) in enumerate(candidates)}
    columns = {
        table: [name for name, _, key in table_columns(blocks[table])
                if key or (p := scores[(table, name)]) is None or p >= 0.15]
        for table in facts
    }
    return columns, any(p is None for p in scores.values())


def route(question: str, llm) -> dict:
    """{domains, tables, columns, probabilities, table_probabilities, fallback}. tables start with
    core.dim_iso, then the referenced dimensions, then the selected facts; columns lists the kept columns
    of each selected fact table (dimensions are kept whole)."""
    domains, probabilities, fallback = _families(question, llm)
    blocks = schema_blocks()
    scores, columns = {}, {}
    for domain in domains:
        domain_scores = _tables(domain, question, llm, blocks)
        kept = [table for table, p in domain_scores.items() if p is None or p >= 0.2]
        domain_columns, uncertain = _columns(domain, question, llm, blocks, kept)
        scores.update(domain_scores)
        columns.update(domain_columns)
        fallback = fallback or uncertain
    facts = list(columns)
    dimensions = re.findall(r"REFERENCES (core\.\w+)", "\n".join(blocks[table] for table in facts))
    tables = list(dict.fromkeys(["core.dim_iso", *dimensions, *facts]))
    return {"domains": domains, "tables": tables, "columns": columns, "probabilities": probabilities,
            "table_probabilities": scores, "fallback": fallback or any(p is None for p in scores.values())}
