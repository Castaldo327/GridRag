"""Scorer regressions and suite contracts; no providers or network calls."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from gridrag.catalog import demo_catalog
from gridrag.warehouse.evaluation import assess, evidence_matches, scalar_evidence, states_value, evaluation_question
from gridrag.warehouse.evals import CASES, reference_value
from gridrag.warehouse.suite import EVALUATION_CASES, GROUPS, suite_info
from benchmarks.cases import BENCHMARK_CASES


class EvaluationSuiteTests(unittest.TestCase):
    def result(self, csv="value\n12.5\n", **changes):
        return {"tool_calls": [{"query": "SELECT 12.5", "csv": csv, **changes}]}

    def test_full_final_result_contract_rejects_incidental_values(self):
        self.assertTrue(evidence_matches(self.result(), 12.5, .01))
        for csv in ("a,b\n0,12.5\n", "a\n12.5\n0\n", "a\nnan\n", "a\ninf\n", "a\n\n", "a\nno result\n"):
            with self.subTest(csv=csv):
                self.assertFalse(evidence_matches(self.result(csv), 12.5, .01))
        for kwargs in ({"truncated": "row cap"}, {"rows": 2}, {"error": "failed"}):
            self.assertFalse(evidence_matches(self.result(**kwargs), 12.5, .01))

    def test_failed_final_query_cannot_reuse_previous_success(self):
        result=self.result()
        result["tool_calls"].append({"query":"SELECT invalid", "error":"rejected"})
        self.assertFalse(evidence_matches(result, 12.5, .01))
        self.assertIn("final SQL query failed", scalar_evidence(result)["reason"])

    def test_repaired_query_passes_but_failures_stay_in_diagnostics(self):
        case=replace(CASES[0], sql="SELECT 12.5", tables=(), excluded=())
        result={**self.result(), "state":"answered", "answer":"12.5 MW"}
        result["tool_calls"].insert(0,{"query":"SELECT invalid", "error":"rejected"})
        report=assess(case,result)
        self.assertTrue(report["passed"])
        self.assertEqual(report["diagnostics"]["sql_errors"],1)
        self.assertEqual(report["diagnostics"]["sql_calls"],2)

    def test_correct_scalar_does_not_hide_wrong_answer_units_or_route(self):
        case=replace(CASES[0], sql="SELECT 12.5")
        result={**self.result(), "state":"answered", "answer":"12.5 MWh", "route":{"tables":[]}}
        report=assess(case,result)
        self.assertTrue(report["correct"])
        self.assertFalse(report["passed"])
        self.assertIn("Answer unit",report["diagnostics"]["failed_checks"])
        self.assertIn("Required tables",report["diagnostics"]["failed_checks"])

    def test_forbidden_sql_is_case_insensitive(self):
        case=replace(CASES[0], sql="SELECT 12.5", avoid=("demand_forecast_mw",))
        result={**self.result(), "state":"answered", "answer":"12.5 MW", "route":{"tables":case.tables}}
        result["tool_calls"][0]["query"]="SELECT DEMAND_FORECAST_MW"
        self.assertIn("Forbidden SQL",assess(case,result)["diagnostics"]["failed_checks"])

    def test_rounded_negative_prose_keeps_the_sign(self):
        self.assertFalse(states_value("0.2 MW", -.2, .01))
        self.assertTrue(states_value("−0.2 MW", -.201, .01))

    def test_suite_is_versioned_and_does_not_change_recorded_benchmark_cases(self):
        info=suite_info()
        self.assertEqual(len(EVALUATION_CASES),28)
        self.assertEqual(len(BENCHMARK_CASES),18)
        self.assertEqual(len({case.id for case in EVALUATION_CASES}),28)
        self.assertEqual(sum(group["cases"] for group in info["groups"]),28)
        self.assertEqual(info["numeric"]+info["behavior"],28)
        self.assertEqual(len(info["sha256"]),64)
        self.assertEqual(info,suite_info())
        tables=demo_catalog().tables
        for case in EVALUATION_CASES:
            with self.subTest(case=case.id):
                self.assertIn(case.category,GROUPS)
                self.assertLessEqual(set(case.tables)|set(case.excluded),tables.keys())
                if case.sql:
                    value=reference_value(case)
                    answer=f"{value:.8f} {case.unit}"
                    result={"state":"answered","answer":answer,"route":{"tables":case.tables},"tool_calls":[{"query":case.sql,"csv":f"value\n{value}\n","rows":1}]}
                    self.assertTrue(assess(case,result)["passed"])

    def test_reference_rejects_invalid_contract(self):
        for csv in ("a,b\n1,2\n", "value\nnan\n", "value\n1\n2\n"):
            with patch("gridrag.warehouse.evals.db.run_model_sql",return_value={"csv":csv}):
                with self.assertRaises(RuntimeError): reference_value(CASES[0])

    def test_live_prompt_supplies_only_question_and_format_contract(self):
        self.assertEqual(evaluation_question(CASES[0]), CASES[0].question + " Return the final SQL result as one row and one numeric answer column.")
        self.assertNotIn(CASES[0].sql, evaluation_question(CASES[0]))
        self.assertEqual(evaluation_question(EVALUATION_CASES[-1]), EVALUATION_CASES[-1].question)
