"""Hybrid candidate retrieval and Decisions reranking over a real Qdrant collection."""

import hashlib
import time
import uuid
from contextlib import ExitStack
from functools import cached_property
from pathlib import Path

from benchmarks import hybrid
from gridrag import config
from gridrag.catalog import Catalog
from gridrag.records import Selection
from gridrag.route import RoutingTooBroad, _with_references

MODEL = "BAAI/bge-small-en-v1.5"


class VectorRetriever:
    """Index documented tables once. Query embeddings never contain reference answers.

    Full table schemas are supplied after candidate reranking and foreign-key closure.
    The reranked baseline supplies every selected column. The experiment compares
    these complete pipelines, including GridRag's additional column-selection calls.
    """

    def __init__(self, catalog: Catalog, url: str):
        from fastembed import TextEmbedding
        from qdrant_client import QdrantClient, models

        self.catalog = catalog
        self.collection = "gridrag_benchmark_" + uuid.uuid4().hex
        started = time.perf_counter()
        with ExitStack() as resources:
            self.client = QdrantClient(url=url, timeout=30)
            resources.callback(self.client.close)
            self.encoder = TextEmbedding(MODEL, cache_dir=str(Path(".cache/embeddings")), threads=2)
            tables = list(catalog.tables.values())
            vectors = list(self.encoder.passage_embed([table.ddl for table in tables]))
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE),
            )
            # Register deletion only after creation succeeds; never touch another run's collection.
            resources.callback(self.client.delete_collection, self.collection)
            self.client.upsert(
                self.collection,
                wait=True,
                points=[
                    models.PointStruct(id=i, vector=vector.tolist(), payload={"table": table.name})
                    for i, (table, vector) in enumerate(zip(tables, vectors, strict=True))
                ],
            )
            self._resources = resources.pop_all()
        self.index_seconds = time.perf_counter() - started
        self.schema_sha256 = hashlib.sha256("\n".join(t.ddl for t in tables).encode()).hexdigest()

    @cached_property
    def keyword_index(self) -> hybrid.KeywordIndex:
        """Tokenize schema documents once for all hybrid questions in this run."""
        return hybrid.KeywordIndex(self.catalog)

    def retrieve_hybrid(
        self, question: str, llm, catalog: Catalog, *, candidate_percent: int = hybrid.DEFAULT_CANDIDATE_PERCENT
    ) -> Selection:
        if catalog is not self.catalog:
            raise ValueError("Retriever must use the indexed catalog")
        vector = next(iter(self.encoder.query_embed(question)))
        policy = hybrid.candidate_policy(len(catalog.tables), candidate_percent)
        limit = policy["candidate_top_k"]
        hits = self.client.query_points(self.collection, query=vector.tolist(), limit=limit).points
        scores = {hit.payload["table"]: float(hit.score) for hit in hits}
        names, fused = hybrid.shortlist(question, catalog, scores, index=self.keyword_index, top_k=limit)
        diagnostics = {
            "candidate_policy": policy,
            "dense_candidates": list(scores),
            "shortlist": names,
            "fusion_scores": fused,
            "reranker": "decisions" if llm is not None else "fusion-only",
            "reranker_endpoint": "/v1/decisions" if llm is not None else None,
            "reranker_model": config.settings.decisions_model if llm is not None else None,
        }
        fallback = False
        if llm is not None:
            names, scores, fallback = hybrid.rerank(question, llm, catalog, names, fused)
            names = [
                name for name in names if scores[name] is None or scores[name] >= config.settings.route_min_probability
            ]
        else:
            scores = fused
        chosen_names = set(names[: policy["final_k"]])
        chosen = _with_references(catalog, chosen_names)
        ordered = [name for name in catalog.tables if name in chosen]
        selection: Selection = {
            "tables": ordered,
            "scores": scores,
            "column_scores": {},
            "columns": {name: list(catalog.tables[name].columns) for name in ordered},
            "fallback": fallback,
        }
        selection["retrieval"] = diagnostics
        if len(ordered) > config.settings.max_routed_tables:
            raise RoutingTooBroad(selection)
        return selection

    def close(self):
        """Release this run's collection and client once, even if deletion fails."""
        self._resources.close()
