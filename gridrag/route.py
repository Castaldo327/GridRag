"""Select tables from the catalog, then include the tables they reference.

One Decisions call scores each core table and each family of per-ISO tables, and which ISOs the request needs;
a selected family contributes the requested ISOs' tables. Uncertain decisions retain context rather than
silently removing it, but mostly unusable scores are a classifier failure, not uncertainty. The table budget
still bounds the SQL model's context.
"""

from gridrag import config
from gridrag.catalog import Catalog, demo_catalog
from gridrag.llm import probability
from gridrag.records import Selection, Stage

TABLE_QUESTION = (
    "Could this table contribute to answering any part of the request, including a comparison or a denominator? "
    "Judge each table independently; multiple tables may be needed. Use its documented measures, grain and coverage.\n"
)
ISO_QUESTION = (
    "Does answering the request need data for the ISO {iso}? Yes if the request names {iso}, one of its locations "
    "or its region, or does not limit which ISOs to use; no if it concerns only other ISOs."
)


class RoutingTooBroad(RuntimeError):
    """The selection exceeds the schema budget; retain it for diagnostics."""

    def __init__(self, selection: Selection):
        super().__init__("Which region or data product should I focus on? That question needs more tables than "
                         f"I can query at once ({len(selection['tables'])} of at most "
                         f"{config.settings.max_routed_tables}).")
        self.selection = selection


class RoutingFailed(RuntimeError):
    """Most routing scores were unusable, so a selection would reflect the classifier rather than the question."""


def route(question: str, llm, catalog: Catalog | None = None) -> Selection:
    catalog = demo_catalog() if catalog is None else catalog
    settings = config.settings
    units, isos = catalog.units(), catalog.isos
    answers = llm.decide(Stage.ROUTE, question, [
        *({"type": "predicate", "name": f"t{i}", "instructions": TABLE_QUESTION + ddl}
          for i, ddl in enumerate(units.values())),
        *({"type": "predicate", "name": f"iso{i}", "instructions": ISO_QUESTION.format(iso=iso)}
          for i, iso in enumerate(isos)),
    ])
    scores = {unit: probability(answers, f"t{i}") for i, unit in enumerate(units)}
    iso_scores = {iso: probability(answers, f"iso{i}") for i, iso in enumerate(isos)}
    every = [*scores.values(), *iso_scores.values()]
    if (unusable := sum(p is None for p in every)) > settings.route_max_unscored * len(every):
        raise RoutingFailed(f"{unusable} of {len(every)} routing scores were unusable")

    def needed(p: float | None) -> bool:
        return p is None or p >= settings.route_min_probability

    requested = [iso for iso, p in iso_scores.items() if needed(p)] or list(isos)  # no ISO stood out: keep them all
    selected = set()
    for unit, p in scores.items():
        if needed(p):
            family = catalog.families.get(unit)
            selected |= {family.tables[iso] for iso in requested if iso in family.tables} if family else {unit}
    # Follow the complete reference graph, including dimensions that reference other dimensions.
    pending = list(selected)
    while pending:
        for table in catalog.tables[pending.pop()].references - selected:
            selected.add(table)
            pending.append(table)
    selection: Selection = {
        "tables": [table for table in catalog.tables if table in selected],
        "scores": scores,
        "iso_scores": iso_scores,
        "fallback": any(p is None for p in every),
    }
    if len(selected) > settings.max_routed_tables:
        raise RoutingTooBroad(selection)
    return selection
