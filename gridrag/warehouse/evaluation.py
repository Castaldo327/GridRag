"""Checks shared by the live test suite and the browser evaluation run."""

import csv
import io
import math
import re

from gridrag.records import State
from gridrag.warehouse.evals import Case, reference_value

NUMBER = re.compile(r"[-−]?\$?\d[\d,]*(?:\.(\d+))?")


def states_value(text: str, expected: float, tolerance: float) -> bool:
    """Accept a reference number at the precision stated in answer prose."""
    for number in NUMBER.finditer(text):
        value = float(number.group().replace(",", "").replace("−", "-").replace("$", ""))
        shown = 0.5 * 10 ** -len(number.group(1) or "")
        if abs(value - expected) <= max(tolerance, shown) + 1e-9:
            return True
    return False


def evidence_matches(result: dict, expected: float, tolerance: float) -> bool:
    """Check unrounded numeric evidence in the last successful query result."""
    for call in reversed(result.get("tool_calls", [])):
        if call.get("error") or not call.get("csv"):
            continue
        rows = iter(csv.reader(io.StringIO(call["csv"])))
        next(rows, None)
        for row in rows:
            for cell in row:
                try:
                    value = float(cell)
                except ValueError:
                    continue
                if math.isclose(value, expected, rel_tol=0, abs_tol=tolerance + 1e-9):
                    return True
        return False
    return False


def case_info(case: Case) -> dict:
    """Public case description and reference value, independent of model output."""
    return {"id": case.id, "label": case.label or case.id.replace("_", " ").title(),
            "question": case.question, "expected_state": case.state,
            "expected": reference_value(case) if case.sql else None, "unit": case.unit}


def assess(case: Case, result: dict) -> dict:
    """Evaluate state, routing, SQL, numeric evidence, and answer for one case."""
    checks = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    check("End state", result.get("state") == case.state,
          f"Expected {case.state}; got {result.get('state', 'unknown')}.")
    route = result.get("route") or {}
    tables = set(route.get("tables") or [])
    missing = set(case.tables) - tables
    if case.tables:
        check("Required tables", not missing,
              "Missing: " + ", ".join(sorted(missing)) if missing else "All required tables selected.")
    unexpected = set(case.excluded) & tables
    if case.excluded:
        check("Excluded tables", not unexpected,
              "Unexpected: " + ", ".join(sorted(unexpected)) if unexpected else "Excluded tables absent.")
    calls = result.get("tool_calls") or []
    queries = " ".join(call.get("query") or "" for call in calls)
    found = [text for text in case.avoid if text in queries]
    if case.avoid:
        check("Forbidden SQL", not found,
              "Found: " + ", ".join(found) if found else "Forbidden SQL absent.")
    if case.state is not State.ANSWERED:
        check("No SQL executed", not calls, f"{len(calls)} SQL calls.")
    expected = reference_value(case) if case.sql else None
    if expected is not None:
        check("Numeric evidence", evidence_matches(result, expected, case.tolerance),
              f"Expected {expected:.6g} {case.unit} in the last successful query.")
        check("Answer value", states_value(result.get("answer") or "", expected, case.tolerance),
              f"Expected {expected:.6g} {case.unit} in the answer.")
    return {"id": case.id, "passed": all(item["passed"] for item in checks),
            "expected": expected, "unit": case.unit, "checks": checks, "result": result}
