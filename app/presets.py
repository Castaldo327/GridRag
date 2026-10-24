"""UI presets: the labelled evaluation cases in gridrag.warehouse.evals, with reference values computed
independently from the warehouse. Never supplied to the model."""

import csv
import io
import math

from gridrag.records import State
from gridrag.warehouse import evals

PRESETS = tuple(case for case in evals.CASES if case.label)


def reference(case: evals.Case) -> dict:
    """The preset as the UI receives it, with the value its reference query computes."""
    return {"id": case.id, "label": case.label, "concept": case.concept, "unit": case.unit,
            "question": case.question, "sql": case.sql, "expected": evals.reference_value(case),
            "tolerance": case.tolerance}


def validate(result, preset):
    """Check scalar query evidence, not prose. Different output shapes require review."""
    for call in reversed(result.get("tool_calls", [])):
        if call.get("error") or not call.get("csv"):
            continue
        rows = list(csv.reader(io.StringIO(call["csv"])))
        if len(rows) != 2 or len(rows[1]) != 1:
            continue
        try:
            value = float(rows[1][0])
        except ValueError:
            continue
        matched = result["state"] == State.ANSWERED and math.isclose(
            value, preset["expected"], rel_tol=0, abs_tol=preset["tolerance"] + 1e-9,
        )
        return {"status": "match" if matched else "review", "actual": value,
                "expected": preset["expected"], "unit": preset["unit"], "tolerance": preset["tolerance"]}
    return {"status": "review", "actual": None, "expected": preset["expected"],
            "unit": preset["unit"], "tolerance": preset["tolerance"]}
