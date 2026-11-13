"""Deterministic scoring shared by browser evaluations, tests, and benchmarks."""

import csv
import io
import math
import re

from gridrag.records import State
from gridrag.warehouse.evals import Case, reference_result, reference_value

NUMBER = re.compile(r"[-−]?\$?\d[\d,]*(?:\.(\d+))?")
UNIT_PATTERNS = {
    "MW": r"\bMW\b",
    "MWh": r"\bMWh\b",
    "%": r"%|\bpercent(?:age)?\b",
    "projects": r"\bprojects?\b",
    "readings": r"\breadings?\b",
    "USD/MWh": r"(?:USD|\$)\s*(?:/|per)\s*MWh\b|\bUSD/MWh\b",
    "USD/MW-hour": r"(?:USD|\$)\s*(?:/|per)\s*MW[ -]hour\b",
}


def evaluation_question(case: Case) -> str:
    """State the scalar formatting contract without exposing reference evidence."""
    if case.result_kind == "table":
        return (
            case.question
            + " Return the complete comparison in the final SQL result, with columns iso_code, product, average_energy_price."
        )
    return case.question + (
        " Return the final SQL result as one row and one numeric answer column." if case.sql else ""
    )


def states_value(text: str, expected: float, tolerance: float) -> bool:
    """Accept rounding at the stated precision, while preserving nonzero signs."""
    for number in NUMBER.finditer(text):
        value = float(number.group().replace(",", "").replace("−", "-").replace("$", ""))
        if value * expected < 0:
            continue
        shown = 0.5 * 10 ** -len(number.group(1) or "")
        if math.isfinite(value) and abs(value - expected) <= max(tolerance, shown) + 1e-9:
            return True
    return False


def scalar_evidence(result: dict) -> dict:
    """Inspect the final attempted query; never fall back to stale earlier evidence."""
    calls = result.get("tool_calls") or []
    if not calls:
        return {"valid": False, "value": None, "reason": "No SQL query was executed."}
    final = calls[-1]
    if final.get("error"):
        return {"valid": False, "value": None, "reason": "The final SQL query failed."}
    if final.get("truncated"):
        return {"valid": False, "value": None, "reason": "The final result was truncated."}
    if not isinstance(final.get("csv"), str) or not final["csv"].strip():
        return {"valid": False, "value": None, "reason": "The final query has no CSV evidence."}
    try:
        rows = list(csv.reader(io.StringIO(final["csv"]), strict=True))
        if len(rows) != 2 or len(rows[0]) != 1 or len(rows[1]) != 1 or final.get("rows", 1) not in (None, 1):
            return {"valid": False, "value": None, "reason": "Expected exactly one result row and one answer column."}
        value = float(rows[1][0])
        if not math.isfinite(value):
            raise ValueError()
    except (ValueError, csv.Error, OverflowError):
        return {"valid": False, "value": None, "reason": "The scalar is missing, nonnumeric, or nonfinite."}
    return {"valid": True, "value": value, "reason": "One finite numeric result in the complete final query."}


def evidence_matches(result: dict, expected: float, tolerance: float) -> bool:
    evidence = scalar_evidence(result)
    return evidence["valid"] and math.isclose(evidence["value"], expected, rel_tol=0, abs_tol=tolerance + 1e-9)


def _keyed_rows(csv_text: str) -> tuple[list[str], dict[tuple[str, ...], float]]:
    """Read unique dimension keys plus one finite measure; reject missing or duplicate rows."""
    rows = list(csv.reader(io.StringIO(csv_text), strict=True))
    if len(rows) < 2 or len(rows[0]) < 2:
        raise ValueError("Expected a complete table")
    values = {}
    for row in rows[1:]:
        if len(row) != len(rows[0]) or not all(row[:-1]):
            raise ValueError("Invalid result row")
        key, value = tuple(row[:-1]), float(row[-1])
        if key in values or not math.isfinite(value):
            raise ValueError("Duplicate key or nonfinite measure")
        values[key] = value
    return rows[0], values


def table_evidence_matches(result: dict, expected: dict, tolerance: float) -> bool:
    """Require every reference key and value in the complete final SQL result, in any row order."""
    calls = result.get("tool_calls") or []
    if not calls:
        return False
    final = calls[-1]
    if final.get("error") or final.get("truncated") or not isinstance(final.get("csv"), str):
        return False
    try:
        headers, actual = _keyed_rows(final["csv"])
        expected_headers, reference = _keyed_rows(expected["csv"])
    except (ValueError, csv.Error, TypeError):
        return False
    return (
        headers == expected_headers
        and actual.keys() == reference.keys()
        and final.get("rows", len(actual)) == len(actual)
        and all(
            math.isclose(actual[key], value, rel_tol=0, abs_tol=tolerance + 1e-9) for key, value in reference.items()
        )
    )


def case_info(case: Case) -> dict:
    """Public expectations; reference SQL is never passed to the live model."""
    return {
        "id": case.id,
        "label": case.label or case.id.replace("_", " ").title(),
        "question": case.question,
        "expected_state": case.state,
        "expected": reference_value(case) if case.sql and case.result_kind == "scalar" else None,
        "unit": case.unit,
        "verification": case.verification,
        "category": case.category,
        "difficulty": case.difficulty,
        "tolerance": case.tolerance,
        "required_tables": list(case.tables),
        "excluded_tables": list(case.excluded),
        "forbidden_sql": list(case.avoid),
        "result_contract": (
            "Complete keyed comparison table"
            if case.result_kind == "table"
            else "One row, one numeric column; complete final query"
            if case.sql
            else "No SQL calls"
        ),
    }


def assess(case: Case, result: dict) -> dict:
    """Separate task correctness from stricter routing and answer presentation checks."""
    checks = []

    def check(name, passed, detail, category):
        checks.append({"name": name, "passed": bool(passed), "detail": detail, "category": category})

    state_ok = result.get("state") == case.state
    check("End state", state_ok, f"Expected {case.state}; got {result.get('state', 'unknown')}.", "behavior")
    check(
        "Answer present",
        bool((result.get("answer") or "").strip()),
        "The response must include an explanation or answer.",
        "answer",
    )
    route = result.get("route") or {}
    tables = set(route.get("tables") or [])
    missing, unexpected = set(case.tables) - tables, set(case.excluded) & tables
    if case.tables:
        check(
            "Required tables",
            not missing,
            "Missing: " + ", ".join(sorted(missing)) if missing else "All required tables selected.",
            "routing",
        )
    if case.excluded:
        check(
            "Excluded tables",
            not unexpected,
            "Unexpected: " + ", ".join(sorted(unexpected)) if unexpected else "Excluded tables absent.",
            "routing",
        )
    calls = result.get("tool_calls") or []
    queries = " ".join(call.get("query") or "" for call in calls).casefold()
    found = [text for text in case.avoid if text.casefold() in queries]
    if case.avoid:
        check(
            "Forbidden SQL", not found, "Found: " + ", ".join(found) if found else "Forbidden SQL absent.", "evidence"
        )
    table_result = case.result_kind == "table"
    expected = reference_result(case) if table_result else reference_value(case) if case.sql else None
    evidence = scalar_evidence(result)
    numeric_ok = (
        table_evidence_matches(result, expected, case.tolerance)
        if table_result
        else evidence_matches(result, expected, case.tolerance)
        if expected is not None
        else None
    )
    if case.state != State.ANSWERED:
        check(
            "No SQL executed",
            not calls,
            f"{len(calls)} SQL calls; none are allowed for this behavior case.",
            "behavior",
        )
    if table_result:
        check(
            "Complete table evidence",
            numeric_ok,
            "Every region/product key and numeric value must match the independent reference, with no missing or extra rows.",
            "evidence",
        )
    elif expected is not None:
        check("Scalar evidence contract", evidence["valid"], evidence["reason"], "evidence")
        check(
            "Numeric evidence",
            numeric_ok,
            f"Expected {expected:.8g} {case.unit} ± {case.tolerance:g}; observed {evidence['value'] if evidence['valid'] else 'no valid scalar'}.",
            "evidence",
        )
        check(
            "Answer value",
            states_value(result.get("answer") or "", expected, case.tolerance),
            f"Answer must state {expected:.8g} {case.unit}, allowing rounding at the displayed precision.",
            "answer",
        )
        pattern = UNIT_PATTERNS.get(case.unit, re.escape(case.unit))
        check(
            "Answer unit",
            bool(re.search(pattern, result.get("answer") or "", re.IGNORECASE)),
            f"Answer must include the unit {case.unit}; this checks the label, not prose semantics.",
            "answer",
        )
    correct = state_ok and (numeric_ok if expected is not None else not calls)
    return {
        "id": case.id,
        "passed": all(item["passed"] for item in checks),
        "correct": bool(correct),
        "expected": expected,
        "observed": evidence["value"],
        "unit": case.unit,
        "checks": checks,
        "result": result,
        "diagnostics": {
            "selected_tables": len(tables),
            "required_table_recall": (len(set(case.tables) & tables) / len(case.tables)) if case.tables else None,
            "sql_calls": len(calls),
            "sql_errors": sum(bool(c.get("error")) for c in calls),
            "failed_checks": [item["name"] for item in checks if not item["passed"]],
        },
    }
