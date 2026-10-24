"""Select whole tables from the schema, then include their referenced tables.

The schema is the routing catalog. Uncertain decisions retain context rather than
silently removing it. The table budget still bounds the SQL model's context.
"""

import re

from gridrag.config import MAX_ROUTED_TABLES, ROUTE_MIN_PROBABILITY
from gridrag.llm import probability
from gridrag.catalog import schema_blocks


class RoutingTooBroad(RuntimeError):
    """The selection exceeds the schema budget; retain it for diagnostics."""

    def __init__(self, selection: dict):
        super().__init__("Which region or data product should I focus on? That question needs more tables than "
                         f"I can query at once ({len(selection['tables'])} of at most {MAX_ROUTED_TABLES}).")
        self.selection = selection


def route(question: str, llm, blocks: dict[str, str] | None = None) -> dict:
    blocks = schema_blocks() if blocks is None else blocks
    if not blocks:
        raise ValueError("The schema catalog is empty")
    answers = llm.decide("route", question, [
        {
            "type": "predicate", "name": f"t{i}",
            "instructions": "Could this table contribute to answering any part of the request, including "
            "a comparison or a denominator? Judge each table independently; multiple tables may be needed. "
            "Use its documented measures, grain and coverage.\n" + block,
        }
        for i, block in enumerate(blocks.values())
    ])
    scores = {table: probability(answers, f"t{i}") for i, table in enumerate(blocks)}
    selected = {table for table, p in scores.items() if p is None or p >= ROUTE_MIN_PROBABILITY}
    # Follow the complete reference graph, including dimensions that reference other dimensions.
    pending = list(selected)
    while pending:
        for table in re.findall(r"REFERENCES (core\.\w+)", blocks[pending.pop()]):
            if table not in blocks:
                raise ValueError(f"Catalog is missing referenced table {table}")
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
