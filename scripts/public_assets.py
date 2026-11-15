"""Build explicit public JSON artifacts from fictional data; no settings or credentials."""

import json
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.metadata import presets
from gridrag import db
from gridrag.catalog import Catalog, demo_catalog
from gridrag.warehouse.evals import CASES, Case, reference_value

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

MAX_QUESTION_CHARS = 2000
DEMO_EVIDENCE_ROWS = 1

ANSWERS = MappingProxyType(
    {
        "peak": "ERCOT’s highest hourly demand on October 19, 2026 (local time) was **{value} MW**. The query takes the maximum hourly demand for that region and date.",
        "share": "Natural gas supplied **{value}%** of PJM’s net generation in September 2026. The query divides gas generation by net generation over the same period and multiplies by 100.",
        "queue": "ERCOT’s interconnection queue contains **{value} active solar projects** in this snapshot. The query filters by region, fuel, and active status before counting projects.",
        "spread": "CAISO_HUB’s average real-time minus day-ahead price spread from 5–6 pm local on October 21, 2026 was **{value} USD/MWh**. The query averages the five-minute real-time prices before subtracting the matching hourly day-ahead price.",
        "forecast": "The latest eligible ERCOT load forecast for October 21, 2026 at 5 pm local was **{value} MW**. The query uses only forecasts published at or before October 20 at 18:00 UTC, then selects the latest publication.",
        "storage": "CAISO’s gross battery discharge energy on October 21, 2026 was **{value} MWh**. The query sums five-minute discharge readings in MW and divides by 12 to convert them to energy. This is gross discharge, not net discharge after charging.",
        "spread_forecast_error": "For CAISO’s hour with the highest signed price spread, the eligible load forecast minus actual demand was **{value} MW**. The selected hour was 08:00 local (15:00 UTC). The latest eligible forecast was 34,708.94 MW, compared with 35,127.47 MW actual demand.",
    }
)


def _demo_record(case: Case, catalog: Catalog) -> dict[str, Any]:
    value = reference_value(case)
    formatted_value = f"{value:,.0f}" if case.unit == "projects" else f"{value:,.2f}"
    return {
        "label": case.label,
        "question": case.question,
        "sql": case.sql,
        "concept": case.concept,
        "tables": [name for name in catalog.tables if re.search(rf"\b{re.escape(name)}\b", case.sql)],
        "evidence": db.run_model_sql(case.sql, DEMO_EVIDENCE_ROWS)["csv"],
        "answer": ANSWERS[case.id].format(value=formatted_value) + " All measurements are from the fictional dataset.",
    }


def build() -> None:
    """Write the frontend demo artifact using the fictional warehouse's reference queries."""
    catalog = demo_catalog()
    demos = [_demo_record(case, catalog) for case in CASES if case.label]
    payload = {
        "catalog_tables": len(catalog.tables),
        "isos": list(catalog.isos),
        "max_question_chars": MAX_QUESTION_CHARS,
        "model_ready": False,
        "requires_api_key": True,
        "presets": presets(),
        "demos": demos,
        "catalog": [{"name": table.name, "ddl": table.ddl} for table in catalog.tables.values()],
    }
    (STATIC / "demo.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
