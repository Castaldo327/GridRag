"""Hybrid candidate retrieval and Decisions reranking over a real Qdrant collection."""

import hashlib
import time
import uuid
from contextlib import ExitStack
from functools import cached_property
from pathlib import Path
from typing import Any

from benchmarks import hybrid
from gridrag import config
from gridrag.catalog import Catalog
from gridrag.llm import Model
from gridrag.records import Selection
from gridrag.route import RoutingTooBroad, _with_references

MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_CACHE_DIR = Path(".cache/embeddings")
EMBEDDING_THREADS = 2
QDRANT_TIMEOUT_SECONDS = 30


class VectorRetriever:
    """Index documented tables once. Query embeddings never contain reference answers.

    Full table schemas are supplied after candidate reranking and foreign-key closure.
    The reranked baseline supplies every selected column. The experiment compares
    these complete pipelines, including GridRag's additional column-selection calls.
    """

    def __init__(self, catalog: Catalog, url: str) -> None:
        # Evaluation dependencies are optional for the application and offline tests.
        from fastembed import TextEmbedding
        from qdrant_client import QdrantClient, models

        self.catalog = catalog
        self.collection = "gridrag_benchmark_" + uuid.uuid4().hex
        started = time.perf_counter()
        with ExitStack() as resources:
            self.client = QdrantClient(url=url, timeout=QDRANT_TIMEOUT_SECONDS)
            resources.callback(self.client.close)
            self.encoder = TextEmbedding(MODEL, cache_dir=str(EMBEDDING_CACHE_DIR), threads=EMBEDDING_THREADS)
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
        self.schema_sha256 = hashlib.sha256("\n".join(table.ddl for table in tables).encode()).hexdigest()

    @cached_property
    def keyword_index(self) -> hybrid.KeywordIndex:
        """Tokenize schema documents once for all hybrid questions in this run."""
        return hybrid.KeywordIndex(self.catalog)

    def _candidates(self, question: str, candidate_percent: int) -> tuple[list[str], dict[str, float], dict[str, Any]]:
        vector = next(iter(self.encoder.query_embed(question)))
        catalog = self.catalog
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
        }
        return names, fused, diagnostics

    def retrieve_hybrid(
        self,
        question: str,
        llm: Model | None,
        catalog: Catalog,
        *,
        candidate_percent: int = hybrid.DEFAULT_CANDIDATE_PERCENT,
    ) -> Selection:
        """Select complete schemas from fused candidates, optionally using Decisions."""
        if catalog is not self.catalog:
            raise ValueError("Retriever must use the indexed catalog")
        names, fused, diagnostics = self._candidates(question, candidate_percent)
        diagnostics.update(
            reranker="decisions" if llm is not None else "fusion-only",
            reranker_endpoint="/v1/decisions" if llm is not None else None,
            reranker_model=config.settings.decisions_model if llm is not None else None,
        )
        policy = diagnostics["candidate_policy"]
        scores: dict[str, float | None]
        fallback = False
        if llm is not None:
            names, scores, fallback = hybrid.rerank(question, llm, catalog, names, fused)
            names = [
                name for name in names if scores[name] is None or scores[name] >= config.settings.route_min_probability
            ]
        else:
            scores = dict(fused)
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

    def close(self) -> None:
        """Release this run's collection and client once, even if deletion fails."""
        self._resources.close()
