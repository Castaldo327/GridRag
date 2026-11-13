"""Schema-driven hybrid retrieval: dense + BM25, then question-level reranking.

The live reranker is a Decisions call over a bounded shortlist, so its token cost
is included. Retrieval-only runs stop at deterministic fusion and make no model calls.
Retrieval never receives benchmark labels, required tables or reference SQL.
"""

import math
import re
from collections import Counter

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


def tokens(text):
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP]


def keyword_scores(question, catalog):
    """BM25 over supplied catalog documents, without domain-specific query expansion."""
    query = set(tokens(question))
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


def shortlist(question, catalog, dense):
    lexical = keyword_scores(question, catalog)
    keyword_names = sorted(lexical, key=lambda name: (-lexical[name], name))[:KEYWORD_POOL]
    candidates = set(dense) | {name for name in keyword_names if lexical[name] > 0}
    fused = {name: WEIGHTS["semantic"] * max(0., dense.get(name, 0.))
             + WEIGHTS["keyword"] * lexical[name] for name in sorted(candidates)}
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
