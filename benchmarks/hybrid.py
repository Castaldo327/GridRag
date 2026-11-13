"""Fixed hybrid retrieval experiment: dense + BM25 + metadata, then question-level reranking.

The live reranker is a Decisions call over a bounded shortlist, so its token cost
is included. Retrieval-only runs stop at deterministic fusion and make no model calls.
Retrieval never receives benchmark labels, required tables or reference SQL.
"""

import math
import re
from collections import Counter
from datetime import datetime

from gridrag.grounding import ISO_ALIASES, mentioned_regions
from gridrag.llm import probability
from gridrag.records import Stage
from gridrag.route import TABLE_QUESTION, _check_scores

DENSE_POOL = 48
KEYWORD_POOL = 12
# Preserve the entire union for question-level reranking; fusion only orders it.
RERANK_POOL = DENSE_POOL + KEYWORD_POOL
FINAL_K = 25
WEIGHTS = {"semantic": .55, "keyword": .25, "metadata": .20}
STOP = frozenset("a an the of in on at to for and or what was were is how much many give use local time".split())


def tokens(text):
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP]


def keyword_scores(question, catalog):
    """BM25 over catalog documents; expand only approved region terminology."""
    query = set(tokens(question))
    for region in mentioned_regions(question):
        query.update(tokens(region))
    documents = {name: Counter(tokens(table.ddl)) for name, table in catalog.tables.items()}
    average = sum(sum(doc.values()) for doc in documents.values()) / len(documents)
    scores = dict.fromkeys(documents, 0.)
    for term in sorted(query):
        frequency = sum(term in doc for doc in documents.values())
        idf = math.log(1 + (len(documents) - frequency + .5) / (frequency + .5))
        for name, doc in documents.items():
            count = doc[term]
            scores[name] += idf * count * 2.2 / (count + 1.2 * (.25 + .75 * sum(doc.values()) / average))
    maximum = max(scores.values(), default=0.)
    return {name: score / maximum if maximum else 0. for name, score in scores.items()}


def question_dates(question):
    dates = []
    for raw in re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b[A-Z][a-z]+ \d{1,2},? \d{4}\b", question, re.I):
        for fmt in ("%Y-%m-%d", "%B %d %Y", "%b %d %Y"):
            try:
                dates.append(datetime.strptime(raw.replace(",", ""), fmt).date())
                break
            except ValueError:
                continue
    return dates


def metadata_score(question, table):
    """Soft region, measure, cadence and coverage signals; never exclude a candidate."""
    regions = mentioned_regions(question)
    name, ddl = table.name, table.ddl.lower()
    signals = []
    scope = {iso for iso in ISO_ALIASES if name.startswith(f"core.{iso.lower()}_")}
    if name in {"core.fact_load_5min", "core.fact_generation_5min"}:
        scope = {"CAISO", "ERCOT"}
    if regions and scope:
        signals.append(1. if regions & scope else -1.)
    question_lower = question.lower()
    if re.search(r"five.minute|5.minute|5min", question_lower):
        signals.append(1. if "5min" in name else -.5 if "hourly" in name else 0.)
    elif "hourly" in question_lower:
        signals.append(1. if "hourly" in name else -.5 if "5min" in name else 0.)
    # Positive measure signals come from physical columns, avoiding negated prose.
    measures = ((r"demand|load", ("demand_mw", "load_mw", "forecast_mw")),
                (r"forecast", ("forecast_mw", "publish_time_utc")),
                (r"lmp|price|spread", ("lmp", "clearing_price")),
                (r"discharge|dispatch|state of charge", ("discharge_mw", "state_of_charge_mwh")),
                (r"queue|projects|proposed", ("capacity_mw", "project_id")),
                (r"generation|output", ("generation_mw", "net_generation_mw")),
                (r"curtail", ("curtailed_mw",)), (r"outage|unavailable", ("unavailable_mw",)))
    for pattern, columns in measures:
        if re.search(pattern, question_lower):
            signals.append(1. if set(columns) & table.columns.keys() else 0.)
    coverage = re.search(r"(\d{4}-\d{2}-\d{2}) through (\d{4}-\d{2}-\d{2})", ddl)
    if coverage and (dates := question_dates(question)):
        # Coverage describes delivery dates, not when a forecast became known.
        ambiguous_dates = "publish_time_utc" in table.columns and len(set(dates)) > 1
        if not ambiguous_dates:
            first, last = (datetime.strptime(raw, "%Y-%m-%d").date() for raw in coverage.groups())
            signals.append(1. if all(first <= day <= last for day in dates) else -1.)
    return sum(signals) / len(signals) if signals else 0.


def shortlist(question, catalog, dense):
    lexical = keyword_scores(question, catalog)
    keyword_names = sorted(lexical, key=lambda name: (-lexical[name], name))[:KEYWORD_POOL]
    candidates = set(dense) | {name for name in keyword_names if lexical[name] > 0}
    fused = {name: WEIGHTS["semantic"] * max(0., dense.get(name, 0.))
             + WEIGHTS["keyword"] * lexical[name]
             + WEIGHTS["metadata"] * metadata_score(question, catalog.tables[name]) for name in sorted(candidates)}
    ranked = sorted(fused, key=lambda name: (-fused[name], name))[:RERANK_POOL]
    return ranked, fused


def rerank(question, llm, catalog, names, fused):
    answers = llm.decide(Stage.ROUTE, question, [
        {"type": "predicate", "name": f"h{i}", "instructions": TABLE_QUESTION + catalog.tables[name].ddl}
        for i, name in enumerate(names)
    ])
    scores = {name: probability(answers, f"h{i}") for i, name in enumerate(names)}
    fallback = _check_scores(scores, "hybrid reranker")
    ranked = sorted(names, key=lambda name: (-(scores[name] if scores[name] is not None else 1.),
                                            -fused[name], name))
    return ranked, scores, fallback
