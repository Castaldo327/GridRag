"""Schema-driven hybrid retrieval: dense + BM25, then question-level reranking.

The live reranker is a Decisions call over a bounded shortlist, so its token cost
is included. Retrieval-only runs stop at deterministic fusion and make no model calls.
Retrieval never receives benchmark labels, required tables or reference SQL.
"""

import math
import re
from collections import Counter

from gridrag.catalog import Catalog
from gridrag.llm import probability
from gridrag.records import Stage
from gridrag.route import TABLE_QUESTION, _check_scores

DENSE_POOL = 48
KEYWORD_POOL = 12
# Preserve the entire union for question-level reranking; fusion only orders it.
RERANK_POOL = DENSE_POOL + KEYWORD_POOL
FINAL_K = 25
# Preserve the semantic:keyword ratio after removing demo-specific metadata rules.
WEIGHTS = {"semantic": 55 / 80, "keyword": 25 / 80}
FUSION_VERSION = "semantic-bm25-v1"
STOP = frozenset("a an the of in on at to for and or what was were is how much many give use local time".split())


def tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP]


class KeywordIndex:
    """Reusable BM25 postings over one immutable catalog, without query expansion."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        documents = {name: Counter(tokens(table.ddl)) for name, table in catalog.tables.items()}
        lengths = {name: sum(document.values()) for name, document in documents.items()}
        average = sum(lengths.values()) / len(documents)
        self.normalizers = {name: 1.2 * (0.25 + 0.75 * length / average) for name, length in lengths.items()}
        self.postings: dict[str, list[tuple[str, int]]] = {}
        for name, document in documents.items():
            for term, count in document.items():
                self.postings.setdefault(term, []).append((name, count))

    def scores(self, question: str) -> dict[str, float]:
        scores = dict.fromkeys(self.catalog.tables, 0.0)
        for term in sorted(set(tokens(question))):
            matches = self.postings.get(term, ())
            frequency = len(matches)
            idf = math.log(1 + (len(scores) - frequency + 0.5) / (frequency + 0.5))
            for name, count in matches:
                scores[name] += idf * count * 2.2 / (count + self.normalizers[name])
        maximum = max(scores.values(), default=0.0)
        return {name: score / maximum if maximum else 0.0 for name, score in scores.items()}


def keyword_scores(question: str, catalog: Catalog) -> dict[str, float]:
    """Score a standalone question; retrievers reuse KeywordIndex across questions."""
    return KeywordIndex(catalog).scores(question)


def shortlist(question, catalog, dense, *, index: KeywordIndex | None = None):
    if index is not None and index.catalog is not catalog:
        raise ValueError("Keyword index must use the supplied catalog")
    lexical = keyword_scores(question, catalog) if index is None else index.scores(question)
    keyword_names = sorted(lexical, key=lambda name: (-lexical[name], name))[:KEYWORD_POOL]
    candidates = set(dense) | {name for name in keyword_names if lexical[name] > 0}
    fused = {
        name: WEIGHTS["semantic"] * max(0.0, dense.get(name, 0.0)) + WEIGHTS["keyword"] * lexical[name]
        for name in sorted(candidates)
    }
    ranked = sorted(fused, key=lambda name: (-fused[name], name))[:RERANK_POOL]
    return ranked, fused


def rerank(question, llm, catalog, names, fused):
    answers = llm.decide(
        Stage.ROUTE,
        question,
        [
            {"type": "predicate", "name": f"h{i}", "instructions": TABLE_QUESTION + catalog.tables[name].ddl}
            for i, name in enumerate(names)
        ],
    )
    scores = {name: probability(answers, f"h{i}") for i, name in enumerate(names)}
    fallback = _check_scores(scores, "hybrid reranker")
    ranked = sorted(names, key=lambda name: (-(scores[name] if scores[name] is not None else 1.0), -fused[name], name))
    return ranked, scores, fallback
