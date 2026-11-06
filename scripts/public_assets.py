"""Build explicit public JSON artifacts from fictional data; no settings or credentials."""
import json
from pathlib import Path

from gridrag import db
from gridrag.catalog import demo_catalog
from gridrag.warehouse.evals import CASES, reference_value

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def build():
    catalog = demo_catalog()
    cases = [case for case in CASES if case.id in {"peak", "storage", "forecast"}]
    demos = [{"id": c.id, "label": c.label, "question": c.question, "value": reference_value(c),
              "unit": c.unit, "sql": c.sql, "tables": list(c.tables),
              "evidence": db.run_model_sql(c.sql, 1)["csv"]} for c in cases]
    payload = {"catalog_tables": len(catalog.tables), "isos": list(catalog.isos),
               "max_question_chars": 2000, "model_ready": False, "requires_api_key": True,
               "presets": [{"id": c.id, "label": c.label, "concept": c.concept, "question": c.question}
                           for c in CASES if c.label], "evaluation_cases": [], "demos": demos,
               "catalog": [{"name": t.name, "ddl": t.ddl} for t in catalog.tables.values()]}
    (STATIC / "demo.json").write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    build()
