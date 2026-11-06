"""Route a question through table scores, then column scores for the selected tables.

The table decision is one call. Independent column decisions run concurrently after table selection;
foreign-key dependencies and structural columns remain available for valid joins and time filters.
"""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed

from gridrag import config
from gridrag.catalog import Catalog, Table, demo_catalog
from gridrag.llm import Model, probability
from gridrag.records import Selection, Stage

TABLE_QUESTION = (
    "Could this exact table contribute to answering any part of the request, including a comparison "
    "or denominator? Judge tables independently; multiple tables may be needed. Consider the table's "
    "ISO, measures, grain, and coverage.\n"
)
COLUMN_QUESTION = (
    "Could this column contribute to answering the request, including filtering, grouping, measuring, "
    "or joining? Judge columns independently. Column definition: "
)


class RoutingTooBroad(RuntimeError):
    """The selection exceeds the table budget; retain it for diagnostics."""

    def __init__(self, selection: Selection):
        super().__init__("Which region or data product should I focus on? That question needs more tables than "
                         f"I can query at once ({len(selection['tables'])} of at most "
                         f"{config.settings.max_routed_tables}).")
        self.selection = selection


class RoutingFailed(RuntimeError):
    """Most scores were unusable, so selection would reflect the classifier rather than the question."""


def _needed(score: float | None, threshold: float) -> bool:
    """An unscored candidate is retained rather than silently removed."""
    return score is None or score >= threshold


def _check_scores(scores: Mapping[str, float | None], label: str) -> bool:
    """Reject mostly unusable decisions. Return whether any score was unusable."""
    unusable = sum(value is None for value in scores.values())
    if unusable > config.settings.route_max_unscored * len(scores):
        raise RoutingFailed(f"{unusable} of {len(scores)} {label} scores were unusable")
    return unusable > 0


def _score_tables(question: str, llm: Model, catalog: Catalog) -> dict[str, float | None]:
    tables = list(catalog.tables.values())
    answers = llm.decide(Stage.ROUTE, question, [
        {"type": "predicate", "name": f"t{i}", "instructions": TABLE_QUESTION + table.ddl}
        for i, table in enumerate(tables)
    ])
    return {table.name: probability(answers, f"t{i}") for i, table in enumerate(tables)}


def _with_references(catalog: Catalog, selected: set[str]) -> set[str]:
    """Include every referenced table, including transitive dimension references."""
    closed, pending = set(selected), list(selected)
    while pending:
        for table in catalog.tables[pending.pop()].references - closed:
            closed.add(table)
            pending.append(table)
    return closed


def _score_columns(question: str, llm: Model, table: Table) -> dict[str, float | None]:
    columns = table.columns
    context = f"Request: {question}\n\nTable definition:\n{table.ddl}"
    answers = llm.decide(Stage.ROUTE, context, [
        {"type": "predicate", "name": f"c{i}", "instructions": COLUMN_QUESTION + description}
        for i, description in enumerate(columns.values())
    ])
    return {name: probability(answers, f"c{i}") for i, name in enumerate(columns)}


def _select_columns(table: Table, scores: Mapping[str, float | None]) -> list[str]:
    selected = set(table.structural_columns) | {
        name for name, score in scores.items() if _needed(score, config.settings.route_min_column_probability)
    }
    if not selected:
        selected.add(max(scores, key=lambda name: scores[name] if scores[name] is not None else -1))
    return [name for name in table.columns if name in selected]


def _score_selected_columns(
    question: str, llm: Model, tables: list[Table],
) -> tuple[dict[str, dict[str, float | None]], bool]:
    """Score independent tables with bounded workers; fail the batch on unusable output."""
    scored: dict[str, dict[str, float | None]] = {}
    fallback = False
    with ThreadPoolExecutor(max_workers=min(config.settings.route_column_workers, len(tables))) as pool:
        futures = {pool.submit(_score_columns, question, llm, table): table.name for table in tables}
        try:
            for future in as_completed(futures):
                name = futures[future]
                scores = future.result()
                fallback |= _check_scores(scores, f"{name} column")
                scored[name] = scores
        except Exception:
            # Running HTTP requests finish under their own timeout; queued work need not start.
            for future in futures:
                future.cancel()
            raise
    return scored, fallback


def route(question: str, llm: Model, catalog: Catalog | None = None) -> Selection:
    """Score all tables, expand dependencies, then score selected tables' columns in parallel."""
    catalog = demo_catalog() if catalog is None else catalog
    table_scores = _score_tables(question, llm, catalog)
    fallback = _check_scores(table_scores, "table")
    chosen = {name for name, score in table_scores.items()
              if _needed(score, config.settings.route_min_probability)}
    tables = _with_references(catalog, chosen)
    ordered = [name for name in catalog.tables if name in tables]
    selection: Selection = {"tables": ordered, "scores": table_scores,
                            "column_scores": {}, "columns": {}, "fallback": fallback}
    if len(ordered) > config.settings.max_routed_tables:
        raise RoutingTooBroad(selection)
    if not ordered:
        return selection

    scored, column_fallback = _score_selected_columns(question, llm, [catalog.tables[name] for name in ordered])
    # Preserve catalog order even when provider calls finish out of order.
    for name in ordered:
        selection["column_scores"][name] = scored[name]
        selection["columns"][name] = _select_columns(catalog.tables[name], scored[name])
    selection["fallback"] = fallback or column_fallback
    return selection
