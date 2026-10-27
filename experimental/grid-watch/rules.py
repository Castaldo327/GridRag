"""Four saved, read-only SQL plans for the tightly scoped demo."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    question: str
    scope: str
    definition: str
    sql: str
    unit: str

RULES = [
Rule('load_drop', 'Sudden load drop', 'Alert me if Dominion zone load drops more than 1,000 MW in 10 minutes.', 'Dominion · PJM',
     'Compare the latest minute with exactly 10 minutes earlier. Alert only if the drop is greater than 1,000 MW.',
'''SELECT now.ts, now.actual_mw AS current_mw,
       before.actual_mw AS previous_mw,
       round(before.actual_mw - now.actual_mw, 1) AS drop_mw,
       before.actual_mw - now.actual_mw > 1000 AS matched
FROM load_readings now
JOIN load_readings before ON before.zone = now.zone
 AND before.ts = now.ts - INTERVAL '10 minutes'
WHERE now.zone = 'Dominion' AND now.ts = ?''','MW'),
Rule('reserves', 'Unusually low reserves', 'Warn me when ERCOT reserves fall below normal for this time of year.', 'ERCOT · seasonal comparison',
     'For this demo, “below normal” means below the 10th percentile of the prior three years, within 14 calendar days of July 22 and the same UTC hour (same local hour in July).',
'''WITH baseline AS (
 SELECT quantile_cont(reserve_mw, 0.10) AS low_normal_mw, count(*) AS sample_count
 FROM reserve_history
 WHERE iso = 'ERCOT' AND year(ts) BETWEEN 2023 AND 2025
   AND month(ts) * 100 + day(ts) BETWEEN 708 AND 805
   AND hour(ts) = hour(CAST(? AS TIMESTAMP))
)
SELECT r.ts, r.reserve_mw, round(b.low_normal_mw, 1) AS low_normal_mw,
       b.sample_count, r.reserve_mw < b.low_normal_mw AS matched
FROM reserve_readings r CROSS JOIN baseline b
WHERE r.iso = 'ERCOT' AND r.ts = ?''','MW'),
Rule('congestion', 'Unusual node congestion', 'Notify me if congestion at my node is in the top 5% of the last 90 days.', 'NVA-DEMO-01 · fictional node',
     '“My node” is NVA-DEMO-01. Compare signed congestion $/MWh with the 95th percentile of available observations in the preceding 90 days, excluding the current reading. History is hourly; replay data is minute-level.',
'''WITH baseline AS (
 SELECT quantile_cont(congestion_per_mwh, 0.95) AS p95, count(*) AS sample_count
 FROM congestion_readings
 WHERE node = 'NVA-DEMO-01'
   AND ts >= CAST(? AS TIMESTAMP) - INTERVAL '90 days' AND ts < ?
)
SELECT c.ts, c.node, c.congestion_per_mwh, round(b.p95, 2) AS p95,
       b.sample_count, c.congestion_per_mwh >= b.p95 AS matched
FROM congestion_readings c CROSS JOIN baseline b
WHERE c.node = 'NVA-DEMO-01' AND c.ts = ?''','$/MWh'),
Rule('forecast_gap', 'Load above forecast', 'Alert me if Dominion load runs more than 5% above forecast.', 'Dominion · PJM',
     'Compare reported Dominion load with its matching forecast. Alert only when actual load exceeds 105% of forecast. This reading does not establish a cause.',
'''SELECT ts, actual_mw, forecast_mw,
       round(100.0 * (actual_mw / forecast_mw - 1), 2) AS above_forecast_pct,
       actual_mw > 1.05 * forecast_mw AS matched
FROM load_readings
WHERE zone = 'Dominion' AND ts = ?''','%'),
]
BY_ID={r.id:r for r in RULES}

def explain(rule_id, row):
    if not row:
        return 'Not enough fresh data to decide.'
    if rule_id == 'load_drop':
        return f"Load fell {row['drop_mw']:,.0f} MW in 10 minutes." if row['drop_mw'] > 0 else f"Load rose {abs(row['drop_mw']):,.0f} MW in 10 minutes."
    if rule_id == 'reserves':
        return f"{row['reserve_mw']:,.0f} MW reserves; seasonal lower bound {row['low_normal_mw']:,.0f} MW."
    if rule_id == 'congestion':
        return f"${row['congestion_per_mwh']:,.2f}/MWh; 90-day top-5% cutoff ${row['p95']:,.2f}."
    return f"Load is {row['above_forecast_pct']:.1f}% above forecast."
