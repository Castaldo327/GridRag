"""One real question through the provider (about two model calls). Skipped without OPEN_AI_KEY."""

import re
import unittest

from gridrag import answer, config, db


@unittest.skipUnless(config.load_env().get("OPEN_AI_KEY"), "OPEN_AI_KEY not set")
class LiveTests(unittest.TestCase):
    def test_real_model_answers_from_a_successful_query(self):
        res = answer.answer("What was ERCOT's highest hourly demand in MW on October 19, 2026 (local time)?")
        expected = db.run_model_sql(
            "SELECT max(demand_mw) FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id) "
            "WHERE iso_code = 'ERCOT' AND interval_start_local::DATE = DATE '2026-10-19'", 1
        )["csv"].splitlines()[1]
        print(f"\n{res['answer']}\n{res['tool_calls']}\nexpected {expected} MW")
        self.assertEqual(res["state"], "answered")
        self.assertTrue(any(c["error"] is None for c in res["tool_calls"]))
        stated = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", res["answer"])]
        self.assertTrue(any(abs(n - float(expected)) <= 1 for n in stated), stated)


if __name__ == "__main__":
    unittest.main()
