"""Dense schema retrieval using local FastEmbed inference and a real Qdrant collection."""

import hashlib
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from gridrag import config
from gridrag.catalog import Catalog
from gridrag.records import Selection
from gridrag.route import RoutingTooBroad, _with_references
from benchmarks import hybrid

MODEL = "BAAI/bge-small-en-v1.5"


class VectorRetriever:
    """Index documented tables once. Query embeddings never contain reference answers.

    Full table schemas are supplied after top-k retrieval and foreign-key closure.
    This deliberately gives the embedding baseline all columns, avoiding a second
    model-based column selector that would confound the comparison.
    """

    def __init__(self, catalog: Catalog, url: str, top_k: int = 21):
        from fastembed import TextEmbedding
        from qdrant_client import QdrantClient, models

        if not 1 <= top_k <= len(catalog.tables):
            raise ValueError("top_k must fit the indexed catalog")
        self.top_k = top_k
        self.catalog = catalog
        self.collection = "gridrag_benchmark_" + uuid.uuid4().hex
        started = time.perf_counter()
        with ExitStack() as resources:
            self.client = QdrantClient(url=url, timeout=30)
            resources.callback(self.client.close)
            self.encoder = TextEmbedding(MODEL, cache_dir=str(Path(".cache/embeddings")), threads=2)
            tables = list(catalog.tables.values())
            vectors = list(self.encoder.passage_embed([table.ddl for table in tables]))
            self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                size=len(vectors[0]), distance=models.Distance.COSINE))
            # Register deletion only after creation succeeds; never touch another run's collection.
            resources.callback(self.client.delete_collection, self.collection)
            self.client.upsert(self.collection, wait=True, points=[
                models.PointStruct(id=i, vector=vector.tolist(), payload={"table": table.name})
                for i, (table, vector) in enumerate(zip(tables, vectors, strict=True))
            ])
            self._resources = resources.pop_all()
        self.index_seconds = time.perf_counter() - started
        self.schema_sha256 = hashlib.sha256("\n".join(t.ddl for t in tables).encode()).hexdigest()

    def retrieve(self, question: str, llm, catalog: Catalog) -> Selection:
        return self._retrieve(question, llm, catalog, use_hybrid=False)

    def retrieve_hybrid(self, question: str, llm, catalog: Catalog) -> Selection:
        return self._retrieve(question, llm, catalog, use_hybrid=True)

    def _retrieve(self, question: str, llm, catalog: Catalog, *, use_hybrid: bool) -> Selection:
        if catalog is not self.catalog:
            raise ValueError("Retriever must use the indexed catalog")
        vector = next(iter(self.encoder.query_embed(question)))
        limit = min(hybrid.DENSE_POOL, len(catalog.tables)) if use_hybrid else self.top_k
        hits = self.client.query_points(self.collection, query=vector.tolist(), limit=limit).points
        scores = {hit.payload["table"]: float(hit.score) for hit in hits}
        fallback = False
        diagnostics = None
        if use_hybrid:
            names, fused = hybrid.shortlist(question, catalog, scores)
            diagnostics = {"dense_candidates": list(scores), "shortlist": names, "fusion_scores": fused,
                           "reranker": "decisions" if llm is not None else "fusion-only",
                           "reranker_endpoint": "/v1/decisions" if llm is not None else None,
                           "reranker_model": config.settings.decisions_model if llm is not None else None}
            if llm is not None:
                names, scores, fallback = hybrid.rerank(question, llm, catalog, names, fused)
                names = [name for name in names if scores[name] is None
                         or scores[name] >= config.settings.route_min_probability]
            else:
                scores = fused
            chosen_names = set(names[:hybrid.FINAL_K])
        else:
            chosen_names = set(scores)
        chosen = _with_references(catalog, chosen_names)
        ordered = [name for name in catalog.tables if name in chosen]
        selection: Selection = {
            "tables": ordered, "scores": scores, "column_scores": {},
            "columns": {name: list(catalog.tables[name].columns) for name in ordered}, "fallback": fallback,
        }
        if diagnostics is not None:
            selection["retrieval"] = diagnostics
        if len(ordered) > config.settings.max_routed_tables:
            raise RoutingTooBroad(selection)
        return selection

    def close(self):
        """Release this run's collection and client once, even if deletion fails."""
        self._resources.close()
