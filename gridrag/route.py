"""Route a question through table scores, then column scores for the selected tables.

The table decision is one call. Independent column decisions run concurrently after table selection;
foreign-key dependencies and structural columns remain available for valid joins and time filters.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from gridrag import config
from gridrag.catalog import Catalog, Table, demo_catalog
from gridrag.llm import Model, probability
from gridrag.records import Selection, Stage

TABLE_QUESTION = (
    "Could this exact table contribute to answering any part of the request, including a comparison "
    "or denominator? Judge tables independently; multiple tables may be needed. Consider the table's "
    "documented scope, fields, grain, and coverage.\n"
)
COLUMN_QUESTION = (
    "Could this column contribute to answering the request, including filtering, grouping, measuring, "
    "or joining? Judge columns independently. Column definition: "
)


class RoutingTooBroad(RuntimeError):
    """The selection exceeds the table budget; retain it for diagnostics."""

    def __init__(self, selection: Selection) -> None:
        super().__init__(
            "Which subset of the data should I focus on? That question needs more tables than "
            f"I can query at once ({len(selection['tables'])} of at most "
            f"{config.settings.max_routed_tables})."
        )
        self.selection = selection


def _needed(score: float, threshold: float) -> bool:
    return score >= threshold


def _score_tables(question: str, llm: Model, catalog: Catalog) -> dict[str, float]:
    tables = list(catalog.tables.values())
    answers = llm.decide(
        Stage.ROUTE,
        question,
        [
            {"type": "predicate", "name": f"t{i}", "instructions": TABLE_QUESTION + table.ddl}
            for i, table in enumerate(tables)
        ],
    )
    return {table.name: probability(answers, f"t{i}") for i, table in enumerate(tables)}


def _with_references(catalog: Catalog, selected: set[str]) -> set[str]:
    """Include every referenced table, including transitive dimension references."""
    expanded = set(selected)
    pending = list(selected)
    while pending:
        for table in catalog.tables[pending.pop()].references - expanded:
            expanded.add(table)
            pending.append(table)
    return expanded


def _score_columns(question: str, llm: Model, table: Table) -> dict[str, float]:
    columns = table.columns
    context = f"Request: {question}\n\nTable definition:\n{table.ddl}"
    answers = llm.decide(
        Stage.ROUTE,
        context,
        [
            {"type": "predicate", "name": f"c{i}", "instructions": COLUMN_QUESTION + description}
            for i, description in enumerate(columns.values())
        ],
    )
    return {name: probability(answers, f"c{i}") for i, name in enumerate(columns)}


def _select_columns(table: Table, scores: dict[str, float]) -> list[str]:
    selected = set(table.structural_columns) | {
        name for name, score in scores.items() if _needed(score, config.settings.route_min_column_probability)
    }
    if not selected:
        selected.add(max(scores, key=scores.__getitem__))
    return [name for name in table.columns if name in selected]


def _score_selected_columns(
    question: str,
    llm: Model,
    tables: list[Table],
) -> dict[str, dict[str, float]]:
    """Score independent tables with bounded workers."""
    scored: dict[str, dict[str, float]] = {}
    with ThreadPoolExecutor(max_workers=min(config.settings.route_column_workers, len(tables))) as pool:
        futures = {pool.submit(_score_columns, question, llm, table): table.name for table in tables}
        try:
            for future in as_completed(futures):
                name = futures[future]
                scores = future.result()
                scored[name] = scores
        except Exception:
            # Running HTTP requests finish under their own timeout; queued work need not start.
            for future in futures:
                future.cancel()
            raise
    return scored


def route(question: str, llm: Model, catalog: Catalog | None = None) -> Selection:
    """Score all tables, expand dependencies, then score selected tables' columns in parallel."""
    catalog = demo_catalog() if catalog is None else catalog
    table_scores = _score_tables(question, llm, catalog)
    chosen = {name for name, score in table_scores.items() if _needed(score, config.settings.route_min_probability)}
    tables = _with_references(catalog, chosen)
    ordered = [name for name in catalog.tables if name in tables]
    selection: Selection = {
        "tables": ordered,
        "scores": table_scores,
        "column_scores": {},
        "columns": {},
    }
    if len(ordered) > config.settings.max_routed_tables:
        raise RoutingTooBroad(selection)
    if not ordered:
        return selection

    scored = _score_selected_columns(question, llm, [catalog.tables[name] for name in ordered])
    # Preserve catalog order even when provider calls finish out of order.
    for name in ordered:
        selection["column_scores"][name] = scored[name]
        selection["columns"][name] = _select_columns(catalog.tables[name], scored[name])
    return selection
