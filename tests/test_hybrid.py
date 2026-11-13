"""Hybrid retrieval preserves question context without benchmark labels or live services."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from benchmarks import hybrid
from benchmarks.vector import VectorRetriever
from gridrag.catalog import demo_catalog
from gridrag import config
from gridrag.answer import answer
from gridrag.route import RoutingFailed


class HybridTests(unittest.TestCase):
    def test_lexical_pool_can_recover_a_table_missing_from_dense_hits(self):
        catalog = demo_catalog()
        names, _ = hybrid.shortlist("California maximum hourly demand on August 8, 2025", catalog,
                                   {"core.caiso_lmp_rt_bus_5min": .9})
        self.assertIn("core.fact_balance_hourly", names)
        self.assertLessEqual(len(names), hybrid.RERANK_POOL)

    def test_metadata_rewards_matching_region_cadence_measure_and_coverage(self):
        catalog = demo_catalog()
        question = "Texas five-minute storage discharge on October 19, 2026"
        score = lambda name: hybrid.metadata_score(question, catalog.tables[name])
        self.assertGreater(score("core.ercot_storage_dispatch_5min"), score("core.caiso_storage_dispatch_5min"))
        self.assertGreater(score("core.ercot_storage_dispatch_5min"), score("core.ercot_lmp_da_hub_hourly"))
        self.assertGreater(score("core.ercot_storage_dispatch_5min"), hybrid.metadata_score(
            "Texas five-minute storage discharge on August 8, 2025", catalog.tables["core.ercot_storage_dispatch_5min"]))

    def test_live_rerank_uses_complete_question_and_fails_on_unusable_scores(self):
        catalog = demo_catalog()
        names = ["core.fact_balance_hourly", "core.queue_project"]
        llm = Mock()
        llm.decide.return_value = {"h0": {"probability": .9}, "h1": {"probability": .1}}
        question = "Compare Texas hourly demand with California on August 8, 2025"
        ranked, scores, fallback = hybrid.rerank(question, llm, catalog, names, dict.fromkeys(names, .5))
        self.assertEqual(ranked, names)
        self.assertFalse(fallback)
        self.assertEqual(llm.decide.call_args.args[1], question)
        llm.decide.return_value = {}
        with self.assertRaises(RoutingFailed):
            hybrid.rerank(question, llm, catalog, names, dict.fromkeys(names, .5))

    def test_forecast_publication_dates_do_not_restrict_delivery_coverage(self):
        table = demo_catalog().tables["core.ercot_load_forecast_hourly"]
        request = "Texas hourly load forecast for delivery on october 15, 2026 published by october {}, 2026"
        self.assertEqual(hybrid.metadata_score(request.format(14), table),
                         hybrid.metadata_score(request.format(16), table))

    def test_hybrid_expands_references_after_reranking_and_keeps_all_columns(self):
        catalog = demo_catalog()
        vector = VectorRetriever.__new__(VectorRetriever)
        vector.catalog, vector.collection = catalog, "owned"
        vector.encoder, vector.client = Mock(), Mock()
        embedding = Mock()
        embedding.tolist.return_value = [0.]
        vector.encoder.query_embed.return_value = [embedding]
        vector.client.query_points.return_value.points = [SimpleNamespace(
            payload={"table": "core.fact_balance_hourly"}, score=.9)]
        with patch.object(config, "settings", replace(config.settings, max_routed_tables=25)):
            selection = vector.retrieve_hybrid("California hourly demand", None, catalog)
        self.assertEqual(vector.client.query_points.call_args.kwargs["limit"], hybrid.DENSE_POOL)
        self.assertIn("core.fact_balance_hourly", selection["tables"])
        self.assertIn("core.dim_iso", selection["tables"])
        self.assertEqual(selection["columns"]["core.fact_balance_hourly"], list(catalog.tables["core.fact_balance_hourly"].columns))
        self.assertEqual(selection["retrieval"]["reranker"], "fusion-only")

    def test_larger_pool_does_not_drop_dense_candidates_before_reranking(self):
        catalog = demo_catalog()
        dense = {name: .5 for name in list(catalog.tables)[:hybrid.DENSE_POOL]}
        names, _ = hybrid.shortlist("Compare hourly demand and prices across the regions", catalog, dense)
        self.assertTrue(set(dense) <= set(names))
        self.assertEqual(hybrid.FINAL_K, 25)

    def test_qdrant_candidates_are_reranked_by_one_decisions_call_before_sql(self):
        catalog = demo_catalog()
        vector = VectorRetriever.__new__(VectorRetriever)
        vector.catalog, vector.collection = catalog, "owned"
        vector.encoder, vector.client = Mock(), Mock()
        embedding = Mock()
        embedding.tolist.return_value = [0.]
        vector.encoder.query_embed.return_value = [embedding]
        order = []

        def retrieve(*args, **kwargs):
            order.append("qdrant")
            return SimpleNamespace(points=[SimpleNamespace(
                payload={"table": "core.fact_balance_hourly"}, score=.9)])

        def decide(stage, question, questions):
            order.append("decisions")
            self.assertEqual(stage, "route")
            self.assertEqual(question, "California hourly demand")
            self.assertTrue(all(item["type"] == "predicate" for item in questions))
            return {item["name"]: {"probability": .9 if catalog.tables["core.fact_balance_hourly"].ddl
                                   in item["instructions"] else .01} for item in questions}

        vector.client.query_points.side_effect = retrieve
        llm = Mock()
        llm.decide.side_effect = decide
        llm.totals.return_value = {"calls": 0, "failed_calls": 0, "input_tokens": 0, "cached_tokens": 0,
                                   "output_tokens": 0, "cost_usd": 0., "per_call": []}

        def sql(*args, **kwargs):
            order.append("sql")
            self.assertEqual(set(kwargs["allowed_tables"]), {"core.fact_balance_hourly", "core.dim_iso"})
            return {"state": "answered", "answer": "Verified answer", "tool_calls": []}

        with (patch.object(config, "settings", replace(config.settings, max_routed_tables=25)),
              patch("gridrag.answer.gate", return_value={"allowed": True, "reason": "Relevant",
                                                         "relevance": 1., "malicious": 0.}),
              patch("gridrag.answer.agent.run", side_effect=sql)):
            result = answer("California hourly demand", llm=llm, catalog=catalog,
                            retriever=vector.retrieve_hybrid)
        self.assertEqual(order, ["qdrant", "decisions", "sql"])
        llm.decide.assert_called_once()
        llm.respond.assert_not_called()
        selected = result["route"]
        self.assertEqual([item["instructions"] for item in llm.decide.call_args.args[2]],
                         [hybrid.TABLE_QUESTION + catalog.tables[name].ddl
                          for name in selected["retrieval"]["shortlist"]])
        self.assertEqual(set(selected["tables"]), {"core.fact_balance_hourly", "core.dim_iso"})
        self.assertEqual(selected["retrieval"]["reranker_endpoint"], "/v1/decisions")
        self.assertEqual(selected["retrieval"]["reranker_model"], config.settings.decisions_model)
