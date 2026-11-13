"""Thirty answerable development questions, from simple lookups to multi-step analytics.

Reference SQL and required-table labels are used only for scoring, never retrieval.
Difficulty labels describe the analytical operations, not measured model outcomes.
"""

from dataclasses import replace

from gridrag.warehouse.evals import CASES, Case
from gridrag.warehouse.suite import ADDITIONAL, BASE_GROUPS

# Reuse established questions and independent references rather than duplicating them.
_EXISTING = {case.id: case for case in (*CASES, *ADDITIONAL)}


def _case(name: str, difficulty: str, category: str | None = None) -> Case:
    case = _EXISTING[name]
    return replace(
        case, difficulty=difficulty, category=category or BASE_GROUPS.get(name, (case.category,))[0], label=""
    )


_NEW_CASES = (
    Case(
        "queue_hybrid_capacity_share",
        difficulty="medium",
        category="analytics",
        unit="%",
        question="In California's current interconnection queue, what percentage of active solar capacity "
        "in MW belongs to solar projects paired with storage? Weight by proposed capacity, not "
        "project count; use the is_hybrid flag and include all active solar capacity in the denominator.",
        sql="""SELECT 100.0 * sum(CASE WHEN is_hybrid THEN capacity_mw ELSE 0 END) / sum(capacity_mw)
FROM core.queue_project
JOIN core.dim_iso USING (iso_id)
JOIN core.dim_fuel USING (fuel_id)
WHERE iso_code = 'CAISO' AND fuel_code = 'solar' AND status_code = 'active'""",
        tables=("core.queue_project", "core.dim_fuel", "core.dim_iso"),
    ),
    Case(
        "demand_ramp",
        difficulty="medium",
        category="time",
        unit="MW",
        question="What was New England's largest positive hour-to-hour change in actual hourly demand "
        "on October 19, 2026 local time, in MW? Compare only consecutive readings whose two "
        "hours are both on that local date; use UTC ordering.",
        sql="""WITH changes AS (
    SELECT demand_mw - lag(demand_mw) OVER (ORDER BY interval_start_utc) AS change_mw
    FROM core.fact_balance_hourly JOIN core.dim_iso USING (iso_id)
    WHERE iso_code = 'ISONE' AND interval_start_local::DATE = DATE '2026-10-19'
)
SELECT max(change_mw) FROM changes WHERE change_mw > 0""",
        tables=("core.fact_balance_hourly", "core.dim_iso"),
    ),
    Case(
        "storage_net_revenue",
        difficulty="very_hard",
        category="operations",
        unit="USD",
        question="For California on October 21, 2026 local time, select the three hours with the "
        "highest actual hourly demand, breaking ties by earliest UTC hour. During those "
        "hours only, what was the battery fleet's net energy revenue in USD at CAISO_HUB "
        "real-time LMPs? Value discharge positively and charging negatively at the matching "
        "five-minute hub price. Rank hourly demand first, then align storage and prices "
        "by ISO and UTC interval and convert interval MW to MWh before summing. "
        "Ignore fees and efficiency losses.",
        sql="""WITH peak_hours AS (
    SELECT b.iso_id, b.interval_start_utc
    FROM core.fact_balance_hourly b JOIN core.dim_iso i USING (iso_id)
    WHERE i.iso_code = 'CAISO' AND b.interval_start_local::DATE = DATE '2026-10-21'
    ORDER BY b.demand_mw DESC, b.interval_start_utc ASC LIMIT 3
)
SELECT sum((s.discharge_mw - s.charge_mw) * p.lmp / 12.0)
FROM core.caiso_storage_dispatch_5min s
JOIN core.caiso_lmp_rt_hub_5min p USING (iso_id, interval_start_utc)
JOIN peak_hours h ON h.iso_id = s.iso_id
    AND s.interval_start_utc >= h.interval_start_utc
    AND s.interval_start_utc < h.interval_start_utc + INTERVAL '1 hour'""",
        tables=("core.fact_balance_hourly", "core.caiso_storage_dispatch_5min", "core.caiso_lmp_rt_hub_5min"),
        excluded=("core.caiso_lmp_rt_bus_5min", "core.queue_project"),
    ),
    Case(
        "forecast_mae",
        difficulty="very_hard",
        category="time",
        unit="MW",
        question="For ERCOT's delivery hours on October 19, 2026 local time, calculate mean absolute "
        "load-forecast error in MW using only information published at or before October 19, "
        "2026 00:00 UTC. For each delivery hour choose the latest eligible forecast, then "
        "compare with actual hourly demand. Exclude any hour without an eligible forecast; "
        "do not average forecast vintages or use the simple demand_forecast_mw field.",
        sql="""WITH eligible AS (
    SELECT iso_id, interval_start_utc, forecast_mw
    FROM core.ercot_load_forecast_hourly
    WHERE interval_start_local::DATE = DATE '2026-10-19'
      AND publish_time_utc <= TIMESTAMP '2026-10-19 00:00'
    QUALIFY row_number() OVER (
        PARTITION BY iso_id, interval_start_utc ORDER BY publish_time_utc DESC
    ) = 1
)
SELECT avg(abs(f.forecast_mw - b.demand_mw))
FROM eligible f JOIN core.fact_balance_hourly b USING (iso_id, interval_start_utc)""",
        tables=("core.ercot_load_forecast_hourly", "core.fact_balance_hourly"),
        avoid=("demand_forecast_mw",),
    ),
    Case(
        "curtailed_available_share",
        difficulty="very_hard",
        category="operations",
        unit="%",
        question="For SPP on October 20, 2026 local time, what percentage of available wind energy "
        "was curtailed? Define available energy as hourly observed wind-generation energy "
        "plus five-minute curtailed wind energy. Convert each series to MWh at its own "
        "cadence, aggregate separately, and report 100 times curtailed divided by available.",
        sql="""WITH generated AS (
    SELECT sum(generation_mw) AS mwh
    FROM core.fact_generation_hourly
    JOIN core.dim_iso USING (iso_id) JOIN core.dim_fuel USING (fuel_id)
    WHERE iso_code = 'SPP' AND fuel_code = 'wind'
      AND interval_start_local::DATE = DATE '2026-10-20'
), curtailed AS (
    SELECT sum(curtailed_mw) / 12.0 AS mwh
    FROM core.spp_renewable_curtailment_5min JOIN core.dim_fuel USING (fuel_id)
    WHERE fuel_code = 'wind' AND interval_start_local::DATE = DATE '2026-10-20'
)
SELECT 100.0 * c.mwh / (g.mwh + c.mwh) FROM generated g CROSS JOIN curtailed c""",
        tables=("core.fact_generation_hourly", "core.spp_renewable_curtailment_5min", "core.dim_fuel"),
    ),
    Case(
        "cross_iso_peak_share",
        difficulty="very_hard",
        category="regional",
        unit="%",
        question="For California and Texas separately, find each region's highest actual hourly demand "
        "on October 19, 2026 local time, breaking ties by earliest UTC hour. At each winning "
        "hour calculate wind plus solar generation as a percentage of total net generation "
        "across all fuels. Aggregate fuel rows before joining the hourly balance. Report "
        "California's percentage minus Texas's percentage in percentage points.",
        sql="""WITH peaks AS (
    SELECT b.iso_id, b.interval_start_utc, b.net_generation_mw, i.iso_code
    FROM core.fact_balance_hourly b JOIN core.dim_iso i USING (iso_id)
    WHERE i.iso_code IN ('CAISO', 'ERCOT') AND b.interval_start_local::DATE = DATE '2026-10-19'
    QUALIFY row_number() OVER (
        PARTITION BY b.iso_id ORDER BY b.demand_mw DESC, b.interval_start_utc ASC
    ) = 1
), renewable AS (
    SELECT iso_id, interval_start_utc, sum(generation_mw) AS renewable_mw
    FROM core.fact_generation_hourly JOIN core.dim_fuel USING (fuel_id)
    WHERE fuel_code IN ('wind', 'solar') AND interval_start_local::DATE = DATE '2026-10-19'
    GROUP BY iso_id, interval_start_utc
)
SELECT sum(CASE WHEN p.iso_code = 'CAISO' THEN 1 ELSE -1 END
           * 100.0 * r.renewable_mw / p.net_generation_mw)
FROM peaks p JOIN renewable r USING (iso_id, interval_start_utc)""",
        tables=("core.fact_balance_hourly", "core.fact_generation_hourly", "core.dim_fuel", "core.dim_iso"),
    ),
    Case(
        "net_load_spread",
        difficulty="very_hard",
        category="time",
        unit="USD/MWh",
        question="For ERCOT on October 18, 2026 local time, find the hour of highest actual hourly "
        "demand minus hourly wind and solar generation. Aggregate the two fuels before "
        "joining demand, and break ties by earliest UTC hour. For that winning hour, "
        "report average five-minute real-time HUB LMP minus matching day-ahead HUB LMP, "
        "in USD/MWh. Use hourly generation and demand, not five-minute load or generation.",
        sql="""WITH renewable AS (
    SELECT iso_id, interval_start_utc, sum(generation_mw) AS output_mw
    FROM core.fact_generation_hourly JOIN core.dim_fuel USING (fuel_id)
    WHERE fuel_code IN ('wind', 'solar') AND interval_start_local::DATE = DATE '2026-10-18'
    GROUP BY iso_id, interval_start_utc
), winning AS (
    SELECT b.iso_id, b.interval_start_utc
    FROM core.fact_balance_hourly b JOIN core.dim_iso i USING (iso_id)
    JOIN renewable r USING (iso_id, interval_start_utc)
    WHERE i.iso_code = 'ERCOT' AND b.interval_start_local::DATE = DATE '2026-10-18'
    ORDER BY b.demand_mw - r.output_mw DESC, b.interval_start_utc ASC LIMIT 1
)
SELECT avg(rt.lmp) - max(da.lmp)
FROM winning w
JOIN core.ercot_lmp_da_hub_hourly da USING (iso_id, interval_start_utc)
JOIN core.ercot_lmp_rt_hub_5min rt ON rt.iso_id = w.iso_id
    AND rt.interval_start_utc >= w.interval_start_utc
    AND rt.interval_start_utc < w.interval_start_utc + INTERVAL '1 hour'""",
        tables=(
            "core.fact_generation_hourly",
            "core.fact_balance_hourly",
            "core.dim_fuel",
            "core.ercot_lmp_rt_hub_5min",
            "core.ercot_lmp_da_hub_hourly",
        ),
        excluded=("core.fact_load_5min", "core.fact_generation_5min", "core.ercot_lmp_rt_bus_5min"),
    ),
)

# A complete comparison is evaluated as a 21-row result, not as a budget refusal.
_PRICE_PRODUCTS = (
    ("real_time_bus", "lmp_rt_bus_5min"),
    ("real_time_hub", "lmp_rt_hub_5min"),
    ("day_ahead_hub", "lmp_da_hub_hourly"),
)
_ISOS = ("CAISO", "ERCOT", "ISONE", "MISO", "NYISO", "PJM", "SPP")
_PRICE_TABLES = tuple(f"core.{iso.lower()}_{suffix}" for iso in _ISOS for _, suffix in _PRICE_PRODUCTS)
_PRICE_COMPARISON = Case(
    "all_iso_prices",
    difficulty="very_hard",
    category="regional",
    unit="USD/MWh",
    result_kind="table",
    question="Compare the mean energy-price component (energy, not total LMP) for real-time bus, "
    "real-time hub and day-ahead hub series across all seven ISOs for October 15–21, 2026, "
    "inclusive in each ISO's local time. Average all native-interval observations for each "
    "ISO/product; for bus series pool the three buses with equal observation weights. "
    "Return all 21 combinations as columns iso_code, product, average_energy_price in "
    "USD/MWh. Use product labels real_time_bus, real_time_hub, and day_ahead_hub; "
    "do not omit a region or product or substitute a missing-series claim.",
    sql="\nUNION ALL\n".join(
        f"SELECT '{iso}' AS iso_code, '{product}' AS product, avg(energy) AS average_energy_price "
        f"FROM core.{iso.lower()}_{suffix} WHERE interval_start_local >= DATE '2026-10-15' "
        "AND interval_start_local < DATE '2026-10-22'"
        for iso in _ISOS
        for product, suffix in _PRICE_PRODUCTS
    ),
    tables=_PRICE_TABLES,
)

_CASES = (
    *(
        _case(name, "easy")
        for name in ("peak", "five_minute", "queue", "nyiso_bus", "pjm_queue", "caiso_peak", "empty_count")
    ),
    *(
        _case(name, "medium")
        for name in ("bus_price", "storage", "miso_storage", "utc_boundary", "forced_outage", "ancillary")
    ),
    *(
        _case(name, "hard")
        for name in (
            "share",
            "spread",
            "forecast",
            "spp_forecast",
            "isone_spread",
            "inclusive_cutoff",
            "net_storage",
            "curtailment",
        )
    ),
    _case("spread_forecast_error", "very_hard", "time"),
    *_NEW_CASES,
    _PRICE_COMPARISON,
)

DIFFICULTIES = ("easy", "medium", "hard", "very_hard")
BENCHMARK_CASES = tuple(sorted(_CASES, key=lambda case: DIFFICULTIES.index(case.difficulty)))
