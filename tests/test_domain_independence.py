"""Exercise the query pipeline with a non-grid catalog and real guarded SQL execution."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import duckdb

from gridrag import config, db
from gridrag.answer import answer
from gridrag.catalog import Catalog, Table


class DomainIndependenceTests(unittest.TestCase):
    def test_retail_catalog_uses_generic_gate_declared_keys_and_schema_only_sql(self):
        catalog = Catalog.of([
            Table.parse("CREATE TABLE retail.item (sku VARCHAR PRIMARY KEY, "
                        "category VARCHAR CHECK (category IN ('Apparel', 'Home')));"),
            Table.parse("CREATE TABLE retail.sale (item VARCHAR REFERENCES retail.item (sku), "
                        "amount DOUBLE, optional_code VARCHAR);"),
        ])
        calls = []

        def decide(stage, question, predicates):
            calls.append((stage, question, predicates))
            if stage == "gate":
                return {"relevant": {"probability": 1.}, "malicious": {"probability": 0.}}
            return {p["name"]: {"probability": .01 if p["name"].startswith("c")
                    and not any(term in p["instructions"] for term in ("category VARCHAR", "amount DOUBLE"))
                    else .99} for p in predicates}

        query = ("SELECT sum(amount) AS revenue FROM retail.sale s JOIN retail.item i ON s.item=i.sku "
                 "WHERE category='Apparel'")
        llm = Mock()
        llm.decide.side_effect = decide
        llm.respond.side_effect = [
            {"id": "query", "status": "completed", "output": [{"type": "function_call", "name": "run_sql",
             "call_id": "call", "arguments": json.dumps({"query": query})}]},
            {"id": "answer", "status": "completed", "output": [{"type": "message", "content": [
             {"type": "output_text", "text": "Apparel revenue was 80."}]}]},
        ]
        llm.totals.return_value = {"calls": 0, "failed_calls": 0, "input_tokens": 0, "cached_tokens": 0,
                                   "output_tokens": 0, "cost_usd": 0., "per_call": []}
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "warehouse.duckdb"
            with duckdb.connect(str(database)) as connection:
                connection.execute("CREATE SCHEMA retail")
                for table in catalog.tables.values():
                    connection.execute(table.ddl)
                connection.execute("INSERT INTO retail.item VALUES ('shirt', 'Apparel'), ('lamp', 'Home')")
                connection.execute("INSERT INTO retail.sale VALUES ('shirt', 30, 'x'), ('shirt', 50, 'y'), "
                                   "('lamp', 10, 'z')")
            with (patch.object(config, "settings", replace(config.settings, db_path=database)),
                  patch.object(db, "_db", None)):
                try:
                    result = answer("What is total Apparel revenue?", llm=llm, catalog=catalog)
                finally:
                    if db._db is not None:
                        db._db.close()
        self.assertEqual(result["state"], "answered")
        self.assertEqual(result["tool_calls"][-1]["csv"], "revenue\n80.0\n")
        self.assertIn("item", result["route"]["columns"]["retail.sale"])
        self.assertNotIn("optional_code", result["route"]["columns"]["retail.sale"])
        self.assertEqual(calls[0][0], "gate")
        self.assertEqual(calls[0][1], "What is total Apparel revenue?")
        self.assertNotIn("electric", calls[0][2][0]["instructions"])
        instructions = llm.respond.call_args_list[0].args[1]
        self.assertIn("retail.sale", instructions)
        self.assertNotIn("CAISO", instructions)
        self.assertNotIn("Approved dimension/entity vocabulary", instructions)
