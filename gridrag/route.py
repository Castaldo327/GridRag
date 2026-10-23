"""Select whole tables from the schema, then include their referenced tables.

The schema is the routing catalog. Uncertain decisions retain context rather than
silently removing it. The table budget still bounds the SQL model's context.
"""

import re

from gridrag.config import MAX_ROUTED_TABLES
from gridrag.warehouse.build import schema_text


class RoutingTooBroad(RuntimeError):
    """The selection exceeds the schema budget; retain it for diagnostics."""

    def __init__(self, selection: dict):
        super().__init__("Which region or data product should I focus on? That question needs more tables than "
                         f"I can query at once ({len(selection['tables'])} of at most {MAX_ROUTED_TABLES}).")
        self.selection = selection


def schema_blocks() -> dict[str, str]:
    """CREATE TABLE definitions and their preceding documentation."""
    return {
        m[1]: block.strip()
        for block in schema_text().split("\n\n")
        if (m := re.search(r"CREATE TABLE (core\.\w+)", block))
    }


def route(question: str, llm) -> dict:
    blocks = schema_blocks()
    answers = llm.decide("route", question, [
        {
            "type": "predicate", "name": f"t{i}",
            "instructions": "Could this table contribute to answering any part of the request, including "
            "a comparison or a denominator? Judge each table independently; multiple tables may be needed. "
            "Use its documented measures, grain and coverage.\n" + block,
        }
        for i, block in enumerate(blocks.values())
    ])
    scores = {table: (answers.get(f"t{i}") or {}).get("probability") for i, table in enumerate(blocks)}
    selected = {table for table, p in scores.items() if p is None or p >= 0.2}
    # Follow the complete reference graph, including dimensions that reference other dimensions.
    pending = list(selected)
    while pending:
        for table in re.findall(r"REFERENCES (core\.\w+)", blocks[pending.pop()]):
            if table not in selected:
                selected.add(table)
                pending.append(table)
    selection = {
        "tables": [table for table in blocks if table in selected],
        "table_probabilities": scores,
        "fallback": any(p is None for p in scores.values()),
    }
    if len(selected) > MAX_ROUTED_TABLES:
        raise RoutingTooBroad(selection)
    return selection
