"""Build explicit public JSON artifacts from fictional data; no settings or credentials."""
import json
import re
from pathlib import Path

from gridrag import db
from gridrag.catalog import demo_catalog
from gridrag.warehouse.evals import CASES, reference_value

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def build():
    catalog = demo_catalog()
    cases = [case for case in CASES if case.label]
    answers = {
        "peak": "ERCOT’s highest hourly demand on October 19, 2026 (local time) was **{value} MW**. The query takes the maximum hourly demand for that region and date.",
        "share": "Natural gas supplied **{value}%** of PJM’s net generation in September 2026. The query divides gas generation by net generation over the same period and multiplies by 100.",
        "queue": "ERCOT’s interconnection queue contains **{value} active solar projects** in this snapshot. The query filters by region, fuel, and active status before counting projects.",
        "spread": "CAISO_HUB’s average real-time minus day-ahead price spread from 5–6 pm local on October 21, 2026 was **{value} USD/MWh**. The query averages the five-minute real-time prices before subtracting the matching hourly day-ahead price.",
        "forecast": "The latest eligible ERCOT load forecast for October 21, 2026 at 5 pm local was **{value} MW**. The query uses only forecasts published at or before October 20 at 18:00 UTC, then selects the latest publication.",
        "storage": "CAISO’s gross battery discharge energy on October 21, 2026 was **{value} MWh**. The query sums five-minute discharge readings in MW and divides by 12 to convert them to energy. This is gross discharge, not net discharge after charging.",
        "spread_forecast_error": "For CAISO’s hour with the highest signed price spread, the eligible load forecast minus actual demand was **{value} MW**. The selected hour was 08:00 local (15:00 UTC). The latest eligible forecast was 34,708.94 MW, compared with 35,127.47 MW actual demand.",
    }
    demos = [{"id": c.id, "label": c.label, "question": c.question, "value": reference_value(c),
              "unit": c.unit, "sql": c.sql, "concept": c.concept,
              "tables": [name for name in catalog.tables if re.search(rf"\b{re.escape(name)}\b", c.sql)],
              "evidence": db.run_model_sql(c.sql, 1)["csv"]} for c in cases]
    for demo in demos:
        value = f"{demo['value']:,.0f}" if demo["unit"] == "projects" else f"{demo['value']:,.2f}"
        demo["answer"] = answers[demo["id"]].format(value=value) + " All measurements are from the fictional dataset."
    payload = {"catalog_tables": len(catalog.tables), "isos": list(catalog.isos),
               "max_question_chars": 2000, "model_ready": False, "requires_api_key": True,
               "presets": [{"id": c.id, "label": c.label, "concept": c.concept, "question": c.question}
                           for c in CASES if c.label], "evaluation_cases": [], "demos": demos,
               "catalog": [{"name": t.name, "ddl": t.ddl} for t in catalog.tables.values()]}
    (STATIC / "demo.json").write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    build()
