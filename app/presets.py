"""Demo questions and independent reference queries. Never supplied to the model."""

import csv
import io
import math

from gridrag import db

PRESETS = [
    {
        "id": "peak", "label": "Peak demand", "concept": "Aggregate a time series", "unit": "MW",
        "question": "What was ERCOT's highest hourly demand in MW on October 19, 2026 (local time)?",
        "sql": "SELECT max(demand_mw) AS peak_mw FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id) "
               "WHERE iso_code = 'ERCOT' AND interval_start_local::DATE = DATE '2026-10-19'",
    },
    {
        "id": "share", "label": "Fuel share", "concept": "Combine measures across tables", "unit": "%",
        "question": "What percentage of PJM's generation came from natural gas in September 2026?",
        "sql": """SELECT 100 *
    (SELECT sum(generation_mw) FROM core.fact_generation_hourly
     JOIN core.dim_iso USING (iso_id) JOIN core.dim_fuel USING (fuel_id)
     WHERE iso_code = 'PJM' AND fuel_code = 'natural_gas'
       AND interval_start_local >= DATE '2026-09-01' AND interval_start_local < DATE '2026-10-01') /
    (SELECT sum(net_generation_mw) FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id)
     WHERE iso_code = 'PJM'
       AND interval_start_local >= DATE '2026-09-01' AND interval_start_local < DATE '2026-10-01') AS share_percent""",
    },
    {
        "id": "queue", "label": "Project queue", "concept": "Filter through shared dimensions", "unit": "projects",
        "question": "How many active solar projects are in ERCOT's interconnection queue?",
        "sql": "SELECT count(*) AS projects FROM core.queue_project JOIN core.dim_iso USING (iso_id) "
               "JOIN core.dim_fuel USING (fuel_id) WHERE iso_code = 'ERCOT' AND fuel_code = 'solar' "
               "AND status_code = 'active'",
    },
    {
        "id": "spread", "label": "Price spread", "concept": "Align five-minute and hourly data", "unit": "USD/MWh",
        "question": "For CAISO_HUB on October 21, 2026 from 5 pm to 6 pm local, what was average real-time "
                    "hub LMP minus day-ahead hourly hub LMP? Report the signed spread in USD/MWh.",
        "sql": """SELECT
    (SELECT avg(lmp) FROM core.caiso_lmp_rt_hub_5min
     WHERE interval_start_local >= TIMESTAMP '2026-10-21 17:00'
       AND interval_start_local < TIMESTAMP '2026-10-21 18:00') -
    (SELECT lmp FROM core.caiso_lmp_da_hub_hourly
     WHERE interval_start_local = TIMESTAMP '2026-10-21 17:00') AS spread""",
    },
    {
        "id": "forecast", "label": "Forecast cutoff", "concept": "Use only information known at the time", "unit": "MW",
        "question": "What was ERCOT's latest hourly load forecast available at or before October 20, 2026 "
                    "18:00 UTC for delivery on October 21 at 5 pm local? Report forecast MW.",
        "sql": "SELECT forecast_mw FROM core.ercot_load_forecast_hourly "
               "WHERE interval_start_local = TIMESTAMP '2026-10-21 17:00' "
               "AND publish_time_utc <= TIMESTAMP '2026-10-20 18:00' ORDER BY publish_time_utc DESC LIMIT 1",
    },
    {
        "id": "storage", "label": "Battery energy", "concept": "Convert interval power to energy", "unit": "MWh",
        "question": "How much gross battery discharge energy in MWh was observed in CAISO on October 21, 2026, "
                    "using five-minute storage dispatch?",
        "sql": "SELECT sum(discharge_mw) / 12 AS discharge_mwh FROM core.caiso_storage_dispatch_5min "
               "WHERE interval_start_local::DATE = DATE '2026-10-21'",
    },
]


def reference(preset):
    result = db.run_model_sql(preset["sql"], 1)
    if "error" in result:
        raise RuntimeError("Reference query failed; rebuild the demo warehouse.")
    value = float(list(csv.reader(io.StringIO(result["csv"])))[1][0])
    return {**preset, "expected": value, "tolerance": 0 if preset["id"] == "queue" else 0.01}


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
        matched = result["state"] == "answered" and math.isclose(
            value, preset["expected"], rel_tol=0, abs_tol=preset["tolerance"] + 1e-9,
        )
        return {"status": "match" if matched else "review", "actual": value,
                "expected": preset["expected"], "unit": preset["unit"], "tolerance": preset["tolerance"]}
    return {"status": "review", "actual": None, "expected": preset["expected"],
            "unit": preset["unit"], "tolerance": preset["tolerance"]}
