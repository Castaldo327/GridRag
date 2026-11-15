"""Thirty frozen analyst tasks for the two-pipeline schema-selection experiment.

Questions are fixed before model runs. Reference SQL and required-table labels are
scoring fixtures and never reach retrieval or SQL generation. Concepts describe
what each task probes; difficulty describes operations, not observed outcomes.
"""

from typing import Any

from gridrag.evals.cases import Case

EXPERIMENT = "decisions-vs-reranker-30-v3"
ISOS = ("CAISO", "ERCOT", "ISONE", "MISO", "NYISO", "PJM", "SPP")


def task(
    id: str,
    difficulty: str,
    category: str,
    concept: str,
    question: str,
    sql: str,
    tables: tuple[str, ...],
    unit: str,
    **kwargs: Any,
) -> Case:
    """Build a frozen task with optional Case scoring fields."""
    return Case(
        id,
        difficulty=difficulty,
        category=category,
        concept=concept,
        question=question,
        sql=sql,
        tables=tables,
        unit=unit,
        **kwargs,
    )


_CASES = (
    task(
        "annual_system_peak",
        "easy",
        "scope",
        "Historical coverage; hourly versus five-minute demand",
        "What was the largest individual hourly demand reading across all seven grid regions in 2025, in MW?",
        "SELECT max(demand_mw) FROM core.fact_balance_hourly "
        "WHERE interval_start_local >= DATE '2025-01-01' AND interval_start_local < DATE '2026-01-01'",
        ("core.fact_balance_hourly",),
        "MW",
    ),
    task(
        "texas_daily_peak",
        "easy",
        "scope",
        "Regional entity and actual demand",
        "What was Texas's peak actual hourly electricity demand on October 20, 2026, local time, in MW?",
        "SELECT max(demand_mw) FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id) "
        "WHERE iso_code = 'ERCOT' AND interval_start_local::DATE = DATE '2026-10-20'",
        ("core.fact_balance_hourly", "core.dim_iso"),
        "MW",
    ),
    task(
        "california_solar_interval",
        "easy",
        "products",
        "Native five-minute generation observation",
        "How much solar power was California generating at 12:05 pm local time on October 18, 2026, in MW?",
        "SELECT generation_mw FROM core.fact_generation_5min JOIN core.dim_iso USING (iso_id) "
        "JOIN core.dim_fuel USING (fuel_id) WHERE iso_code = 'CAISO' AND fuel_code = 'solar' "
        "AND interval_start_local = TIMESTAMP '2026-10-18 12:05'",
        ("core.fact_generation_5min", "core.dim_iso", "core.dim_fuel"),
        "MW",
    ),
    task(
        "new_york_active_queue",
        "easy",
        "joins",
        "Proposed projects versus operational output",
        "How many active solar projects are in New York's current interconnection queue?",
        "SELECT count(*) FROM core.queue_project JOIN core.dim_iso USING (iso_id) "
        "JOIN core.dim_fuel USING (fuel_id) WHERE iso_code = 'NYISO' AND fuel_code = 'solar' AND status_code = 'active'",
        ("core.queue_project", "core.dim_iso", "core.dim_fuel"),
        "projects",
        tolerance=0,
    ),
    task(
        "pjm_day_ahead",
        "easy",
        "products",
        "Day-ahead hub versus real-time bus prices",
        "What was the average day-ahead LMP at PJM_HUB on October 17, 2026 local time, in USD/MWh?",
        "SELECT avg(lmp) FROM core.pjm_lmp_da_hub_hourly WHERE interval_start_local::DATE = DATE '2026-10-17'",
        ("core.pjm_lmp_da_hub_hourly",),
        "USD/MWh",
    ),
    task(
        "new_york_bus_price",
        "easy",
        "products",
        "Individual bus and total LMP",
        "What was the real-time LMP at NYISO_BUS_B at 5:10 pm local time on October 18, 2026, in USD/MWh?",
        "SELECT lmp FROM core.nyiso_lmp_rt_bus_5min JOIN core.dim_location USING (location_id) "
        "WHERE location_code = 'NYISO_BUS_B' AND interval_start_local = TIMESTAMP '2026-10-18 17:10'",
        ("core.nyiso_lmp_rt_bus_5min", "core.dim_location"),
        "USD/MWh",
    ),
    task(
        "miso_unavailable_capacity",
        "easy",
        "operations",
        "Daily unavailable capacity versus energy",
        "How much resource capacity was unavailable in MISO on October 18, 2026, counting both planned and forced outages, in MW?",
        "SELECT sum(unavailable_mw) FROM core.miso_resource_outage_daily WHERE market_date = DATE '2026-10-18'",
        ("core.miso_resource_outage_daily",),
        "MW",
    ),
    task(
        "pjm_solar_share",
        "medium",
        "joins",
        "Implicit denominator and protection against join fanout",
        "What percentage of PJM's total net generation came from solar during August 2026?",
        """WITH solar AS (
    SELECT sum(generation_mw) AS mwh FROM core.fact_generation_hourly
    JOIN core.dim_iso USING (iso_id) JOIN core.dim_fuel USING (fuel_id)
    WHERE iso_code = 'PJM' AND fuel_code = 'solar'
      AND interval_start_local >= DATE '2026-08-01' AND interval_start_local < DATE '2026-09-01'
), total AS (
    SELECT sum(net_generation_mw) AS mwh FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id)
    WHERE iso_code = 'PJM' AND interval_start_local >= DATE '2026-08-01' AND interval_start_local < DATE '2026-09-01'
) SELECT 100.0 * solar.mwh / total.mwh FROM solar CROSS JOIN total""",
        ("core.fact_generation_hourly", "core.fact_balance_hourly", "core.dim_iso", "core.dim_fuel"),
        "%",
    ),
    task(
        "california_hybrid_queue_share",
        "medium",
        "joins",
        "Capacity-weighted share versus project count",
        "Of the active solar capacity in California's current interconnection queue, what percentage is paired with storage? Weight by proposed MW, not project count.",
        "SELECT 100.0 * sum(CASE WHEN is_hybrid THEN capacity_mw ELSE 0 END) / sum(capacity_mw) "
        "FROM core.queue_project JOIN core.dim_iso USING (iso_id) JOIN core.dim_fuel USING (fuel_id) "
        "WHERE iso_code = 'CAISO' AND fuel_code = 'solar' AND status_code = 'active'",
        ("core.queue_project", "core.dim_iso", "core.dim_fuel"),
        "%",
    ),
    task(
        "spp_battery_discharge",
        "medium",
        "operations",
        "Observed dispatch and MW-to-MWh conversion",
        "How much energy did SPP's battery fleet discharge on October 20, 2026 local time, in MWh? Count discharge only, before subtracting charging.",
        "SELECT sum(discharge_mw) / 12.0 FROM core.spp_storage_dispatch_5min "
        "WHERE interval_start_local::DATE = DATE '2026-10-20'",
        ("core.spp_storage_dispatch_5min",),
        "MWh",
    ),
    task(
        "new_england_reserve_price",
        "medium",
        "products",
        "Ancillary reserve product versus energy price",
        "What was New England's average spinning-reserve clearing price on October 16, 2026 local time, in USD/MW-hour?",
        "SELECT avg(clearing_price) FROM core.isone_ancillary_prices_hourly "
        "WHERE service_code = 'spinning_reserve' AND interval_start_local::DATE = DATE '2026-10-16'",
        ("core.isone_ancillary_prices_hourly",),
        "USD/MW-hour",
    ),
    task(
        "miso_forced_gas_outage",
        "medium",
        "operations",
        "Outage type and fuel dimension",
        "How much natural-gas capacity was on forced outage in MISO on October 21, 2026, in MW?",
        "SELECT sum(unavailable_mw) FROM core.miso_resource_outage_daily JOIN core.dim_fuel USING (fuel_id) "
        "WHERE market_date = DATE '2026-10-21' AND outage_type = 'forced' AND fuel_code = 'natural_gas'",
        ("core.miso_resource_outage_daily", "core.dim_fuel"),
        "MW",
    ),
    task(
        "texas_curtailed_wind",
        "medium",
        "products",
        "Curtailed power versus generated energy",
        "How much wind energy was curtailed in Texas on October 17, 2026 local time, in MWh?",
        "SELECT sum(curtailed_mw) / 12.0 FROM core.ercot_renewable_curtailment_5min "
        "JOIN core.dim_fuel USING (fuel_id) WHERE fuel_code = 'wind' "
        "AND interval_start_local::DATE = DATE '2026-10-17'",
        ("core.ercot_renewable_curtailment_5min", "core.dim_fuel"),
        "MWh",
    ),
    task(
        "california_utc_load",
        "medium",
        "temporal",
        "UTC reporting window versus local calendar date",
        "What was California's average five-minute load from October 19, 2026 00:00 UTC up to but excluding October 20 00:00 UTC, in MW?",
        "SELECT avg(load_mw) FROM core.fact_load_5min JOIN core.dim_iso USING (iso_id) "
        "WHERE iso_code = 'CAISO' AND interval_start_utc >= TIMESTAMP '2026-10-19 00:00' "
        "AND interval_start_utc < TIMESTAMP '2026-10-20 00:00'",
        ("core.fact_load_5min", "core.dim_iso"),
        "MW",
    ),
    task(
        "pjm_proposed_batteries",
        "medium",
        "scope",
        "Queue status and proposed operation date",
        "How much active standalone battery capacity is proposed in PJM's current queue with a proposed commercial operation date before January 1, 2029, in MW?",
        "SELECT coalesce(sum(capacity_mw), 0) FROM core.queue_project JOIN core.dim_iso USING (iso_id) "
        "JOIN core.dim_fuel USING (fuel_id) WHERE iso_code = 'PJM' AND fuel_code = 'battery' "
        "AND status_code = 'active' AND NOT is_hybrid AND proposed_cod < DATE '2029-01-01'",
        ("core.queue_project", "core.dim_iso", "core.dim_fuel"),
        "MW",
    ),
    task(
        "california_daily_spread",
        "hard",
        "products",
        "Two price markets at different cadences",
        "For CAISO_HUB on October 20, 2026 local time, what was the daily average real-time LMP minus the daily average day-ahead LMP, in USD/MWh?",
        "SELECT (SELECT avg(lmp) FROM core.caiso_lmp_rt_hub_5min WHERE interval_start_local::DATE = DATE '2026-10-20') "
        "- (SELECT avg(lmp) FROM core.caiso_lmp_da_hub_hourly WHERE interval_start_local::DATE = DATE '2026-10-20')",
        ("core.caiso_lmp_rt_hub_5min", "core.caiso_lmp_da_hub_hourly"),
        "USD/MWh",
    ),
    task(
        "texas_known_forecast",
        "hard",
        "temporal",
        "Publication cutoff excludes hindsight vintages",
        "As of October 19, 2026 at 12:00 UTC, what was the latest available ERCOT load forecast for delivery at 6 pm Texas local time that day, in MW? Include forecasts published exactly at the cutoff.",
        "SELECT forecast_mw FROM core.ercot_load_forecast_hourly "
        "WHERE interval_start_local = TIMESTAMP '2026-10-19 18:00' "
        "AND publish_time_utc <= TIMESTAMP '2026-10-19 12:00' ORDER BY publish_time_utc DESC LIMIT 1",
        ("core.ercot_load_forecast_hourly",),
        "MW",
    ),
    task(
        "pjm_pre_delivery_bias",
        "hard",
        "temporal",
        "Per-delivery vintage selection and actuals join",
        "For PJM's delivery hours on October 20, 2026 local time, what was the mean signed load-forecast error, forecast minus actual demand, in MW? For each hour use the latest forecast published strictly before that delivery hour began.",
        """WITH latest AS (
    SELECT iso_id, interval_start_utc, forecast_mw FROM core.pjm_load_forecast_hourly
    WHERE interval_start_local::DATE = DATE '2026-10-20' AND publish_time_utc < interval_start_utc
    QUALIFY row_number() OVER (PARTITION BY iso_id, interval_start_utc ORDER BY publish_time_utc DESC) = 1
) SELECT avg(f.forecast_mw - b.demand_mw) FROM latest f
JOIN core.fact_balance_hourly b USING (iso_id, interval_start_utc)""",
        ("core.pjm_load_forecast_hourly", "core.fact_balance_hourly"),
        "MW",
    ),
    task(
        "texas_battery_revenue",
        "hard",
        "operations",
        "Aligned interval prices, charging sign and energy units",
        "What was ERCOT's battery fleet net energy revenue at ERCOT_HUB real-time LMPs on October 18, 2026 local time, in USD? Value discharge positively and charging negatively at each matching five-minute price; ignore fees and efficiency losses.",
        "SELECT sum((s.discharge_mw - s.charge_mw) * p.lmp / 12.0) "
        "FROM core.ercot_storage_dispatch_5min s JOIN core.ercot_lmp_rt_hub_5min p USING (iso_id, interval_start_utc) "
        "WHERE s.interval_start_local::DATE = DATE '2026-10-18'",
        ("core.ercot_storage_dispatch_5min", "core.ercot_lmp_rt_hub_5min"),
        "USD",
    ),
    task(
        "spp_available_wind_share",
        "hard",
        "joins",
        "Implicit two-source denominator across cadences",
        "What percentage of SPP's available wind energy was curtailed on October 19, 2026 local time? Define available wind energy as observed wind generation plus curtailed wind energy.",
        """WITH generated AS (
    SELECT sum(generation_mw) AS mwh FROM core.fact_generation_hourly
    JOIN core.dim_iso USING (iso_id) JOIN core.dim_fuel USING (fuel_id)
    WHERE iso_code = 'SPP' AND fuel_code = 'wind' AND interval_start_local::DATE = DATE '2026-10-19'
), curtailed AS (
    SELECT sum(curtailed_mw) / 12.0 AS mwh FROM core.spp_renewable_curtailment_5min
    JOIN core.dim_fuel USING (fuel_id)
    WHERE fuel_code = 'wind' AND interval_start_local::DATE = DATE '2026-10-19'
) SELECT 100.0 * c.mwh / (g.mwh + c.mwh) FROM generated g CROSS JOIN curtailed c""",
        ("core.fact_generation_hourly", "core.spp_renewable_curtailment_5min", "core.dim_iso", "core.dim_fuel"),
        "%",
    ),
    task(
        "new_england_demand_ramp",
        "hard",
        "temporal",
        "Window ordering and within-day boundaries",
        "What was New England's largest positive hour-to-hour increase in actual hourly demand on October 18, 2026 local time, in MW? Both readings must be on that local date; order readings by UTC.",
        "WITH changes AS (SELECT demand_mw - lag(demand_mw) OVER (ORDER BY interval_start_utc) AS change_mw "
        "FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id) "
        "WHERE iso_code = 'ISONE' AND interval_start_local::DATE = DATE '2026-10-18') "
        "SELECT max(change_mw) FROM changes WHERE change_mw > 0",
        ("core.fact_balance_hourly", "core.dim_iso"),
        "MW",
    ),
    task(
        "annual_regional_peak_gap",
        "hard",
        "regional",
        "Multi-region comparison over historical coverage",
        "How much higher was Texas's 2025 peak actual hourly demand than California's 2025 peak, in MW? Find each region's peak independently using local calendar dates.",
        "SELECT max(CASE WHEN iso_code = 'ERCOT' THEN demand_mw END) "
        "- max(CASE WHEN iso_code = 'CAISO' THEN demand_mw END) "
        "FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id) WHERE iso_code IN ('ERCOT', 'CAISO') "
        "AND interval_start_local >= DATE '2025-01-01' AND interval_start_local < DATE '2026-01-01'",
        ("core.fact_balance_hourly", "core.dim_iso"),
        "MW",
    ),
    task(
        "miso_planned_outage_share",
        "hard",
        "joins",
        "Capacity-weighted denominator across fuels and outage types",
        "Across October 15–21, 2026 inclusive, what percentage of MISO's summed daily unavailable capacity was planned rather than forced? Include every fuel and weight by unavailable MW-days.",
        "SELECT 100.0 * sum(CASE WHEN outage_type = 'planned' THEN unavailable_mw ELSE 0 END) / sum(unavailable_mw) "
        "FROM core.miso_resource_outage_daily WHERE market_date >= DATE '2026-10-15' AND market_date < DATE '2026-10-22'",
        ("core.miso_resource_outage_daily",),
        "%",
    ),
    task(
        "new_york_forecast_mae",
        "very_hard",
        "temporal",
        "Fixed information cutoff over a full delivery day",
        "For New York's delivery hours on October 19, 2026 local time, what was the mean absolute load-forecast error in MW using only forecasts known by October 19 at 00:00 UTC? Use the latest eligible publication for each hour and omit hours with no eligible forecast.",
        """WITH eligible AS (
    SELECT iso_id, interval_start_utc, forecast_mw FROM core.nyiso_load_forecast_hourly
    WHERE interval_start_local::DATE = DATE '2026-10-19' AND publish_time_utc <= TIMESTAMP '2026-10-19 00:00'
    QUALIFY row_number() OVER (PARTITION BY iso_id, interval_start_utc ORDER BY publish_time_utc DESC) = 1
) SELECT avg(abs(f.forecast_mw - b.demand_mw)) FROM eligible f
JOIN core.fact_balance_hourly b USING (iso_id, interval_start_utc)""",
        ("core.nyiso_load_forecast_hourly", "core.fact_balance_hourly"),
        "MW",
    ),
    task(
        "texas_load_weighted_price",
        "very_hard",
        "operations",
        "Weighted measure and cadence alignment",
        "What was the load-weighted average real-time ERCOT_HUB LMP on October 21, 2026 local time, in USD/MWh? Weight each five-minute price by actual five-minute load in the same interval.",
        "SELECT sum(p.lmp * b.load_mw) / sum(b.load_mw) FROM core.ercot_lmp_rt_hub_5min p "
        "JOIN core.fact_load_5min b USING (iso_id, interval_start_utc) "
        "WHERE p.interval_start_local::DATE = DATE '2026-10-21'",
        ("core.ercot_lmp_rt_hub_5min", "core.fact_load_5min"),
        "USD/MWh",
    ),
    task(
        "california_net_load_peak_price",
        "very_hard",
        "operations",
        "Rank a derived measure before selecting market prices",
        "On October 20, 2026 local time, which California hour had the highest actual hourly demand minus hourly wind and solar generation? For that hour, report average real-time CAISO_HUB LMP minus day-ahead hub LMP, in USD/MWh. Break net-load ties by earliest UTC hour.",
        """WITH renewable AS (
    SELECT iso_id, interval_start_utc, sum(generation_mw) AS mw FROM core.fact_generation_hourly
    JOIN core.dim_fuel USING (fuel_id) WHERE fuel_code IN ('wind', 'solar')
      AND interval_start_local::DATE = DATE '2026-10-20' GROUP BY iso_id, interval_start_utc
), winning AS (
    SELECT b.iso_id, b.interval_start_utc FROM core.fact_balance_hourly b JOIN core.dim_iso i USING (iso_id)
    JOIN renewable r USING (iso_id, interval_start_utc)
    WHERE i.iso_code = 'CAISO' AND b.interval_start_local::DATE = DATE '2026-10-20'
    ORDER BY b.demand_mw - r.mw DESC, b.interval_start_utc ASC LIMIT 1
) SELECT avg(rt.lmp) - max(da.lmp) FROM winning w
JOIN core.caiso_lmp_da_hub_hourly da USING (iso_id, interval_start_utc)
JOIN core.caiso_lmp_rt_hub_5min rt ON rt.iso_id = w.iso_id
    AND rt.interval_start_utc >= w.interval_start_utc
    AND rt.interval_start_utc < w.interval_start_utc + INTERVAL '1 hour'""",
        (
            "core.fact_balance_hourly",
            "core.fact_generation_hourly",
            "core.dim_fuel",
            "core.dim_iso",
            "core.caiso_lmp_rt_hub_5min",
            "core.caiso_lmp_da_hub_hourly",
        ),
        "USD/MWh",
    ),
    task(
        "regional_peak_renewable_gap",
        "very_hard",
        "regional",
        "Independent regional peaks and fuel-share denominator",
        "For California and Texas separately, find the peak actual hourly demand on October 20, 2026 local time, breaking ties by earliest UTC hour. What was California's wind-plus-solar share of total net generation at its peak minus Texas's share at its peak, in percentage points?",
        """WITH peaks AS (
    SELECT b.iso_id, b.interval_start_utc, b.net_generation_mw, i.iso_code
    FROM core.fact_balance_hourly b JOIN core.dim_iso i USING (iso_id)
    WHERE i.iso_code IN ('CAISO', 'ERCOT') AND b.interval_start_local::DATE = DATE '2026-10-20'
    QUALIFY row_number() OVER (PARTITION BY b.iso_id ORDER BY b.demand_mw DESC, b.interval_start_utc ASC) = 1
), renewable AS (
    SELECT iso_id, interval_start_utc, sum(generation_mw) AS mw FROM core.fact_generation_hourly
    JOIN core.dim_fuel USING (fuel_id) WHERE fuel_code IN ('wind', 'solar')
      AND interval_start_local::DATE = DATE '2026-10-20' GROUP BY iso_id, interval_start_utc
) SELECT sum(CASE WHEN p.iso_code = 'CAISO' THEN 1 ELSE -1 END * 100.0 * r.mw / p.net_generation_mw)
FROM peaks p JOIN renewable r USING (iso_id, interval_start_utc)""",
        ("core.fact_balance_hourly", "core.fact_generation_hourly", "core.dim_iso", "core.dim_fuel"),
        "%",
    ),
    task(
        "all_region_forecast_error",
        "very_hard",
        "regional",
        "Broad candidate coverage across seven similar forecast tables",
        "Across all seven ISOs, what was the mean absolute hourly load-forecast error for delivery on October 18, 2026 in each ISO's local time, in MW? For every ISO and delivery hour use its latest forecast published strictly before delivery. Give every ISO-hour equal weight.",
        "WITH forecasts AS ("
        + " UNION ALL ".join(
            f"SELECT iso_id, interval_start_utc, publish_time_utc, forecast_mw FROM core.{iso.lower()}_load_forecast_hourly "
            "WHERE interval_start_local::DATE = DATE '2026-10-18'"
            for iso in ISOS
        )
        + "), latest AS (SELECT * FROM forecasts WHERE publish_time_utc < interval_start_utc "
        "QUALIFY row_number() OVER (PARTITION BY iso_id, interval_start_utc ORDER BY publish_time_utc DESC) = 1) "
        "SELECT avg(abs(f.forecast_mw - b.demand_mw)) FROM latest f "
        "JOIN core.fact_balance_hourly b USING (iso_id, interval_start_utc)",
        tuple(f"core.{iso.lower()}_load_forecast_hourly" for iso in ISOS) + ("core.fact_balance_hourly",),
        "MW",
    ),
    task(
        "all_region_battery_energy",
        "very_hard",
        "regional",
        "Broad dispatch retrieval and signed integration",
        "Across all seven ISOs on October 19, 2026 in each region's local time, how much net energy did batteries supply, in MWh? Add discharge and subtract charging across every region.",
        "SELECT sum(mwh) FROM ("
        + " UNION ALL ".join(
            f"SELECT sum(discharge_mw - charge_mw) / 12.0 AS mwh FROM core.{iso.lower()}_storage_dispatch_5min "
            "WHERE interval_start_local::DATE = DATE '2026-10-19'"
            for iso in ISOS
        )
        + ") totals",
        tuple(f"core.{iso.lower()}_storage_dispatch_5min" for iso in ISOS),
        "MWh",
    ),
)

PRICE_PRODUCTS = (
    ("real_time_bus", "lmp_rt_bus_5min"),
    ("real_time_hub", "lmp_rt_hub_5min"),
    ("day_ahead_hub", "lmp_da_hub_hourly"),
)
_PRICE_COMPARISON = task(
    "all_iso_prices",
    "very_hard",
    "regional",
    "Wide result completeness and price-component discrimination",
    "Compare average energy-price components, rather than total LMP, across all seven ISOs for "
    "October 16–20, 2026 inclusive in each region's local time. Include real-time bus, real-time hub, "
    "and day-ahead hub products. Average native-interval observations, pooling all buses equally. "
    "Return all 21 combinations as iso_code, product, average_energy_price in USD/MWh, using product "
    "labels real_time_bus, real_time_hub, and day_ahead_hub.",
    "\nUNION ALL\n".join(
        f"SELECT '{iso}' AS iso_code, '{product}' AS product, avg(energy) AS average_energy_price "
        f"FROM core.{iso.lower()}_{suffix} WHERE interval_start_local >= DATE '2026-10-16' "
        "AND interval_start_local < DATE '2026-10-21'"
        for iso in ISOS
        for product, suffix in PRICE_PRODUCTS
    ),
    tuple(f"core.{iso.lower()}_{suffix}" for iso in ISOS for _, suffix in PRICE_PRODUCTS),
    "USD/MWh",
    result_kind="table",
)

BENCHMARK_CASES = (*_CASES, _PRICE_COMPARISON)
