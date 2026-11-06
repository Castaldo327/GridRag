"""Additional, fixed evaluation questions, separate from the visible UI presets.

These are a small author-written test set, not a claim of unseen production data.
Do not select retrieval settings based on these outcomes.
"""
from gridrag.warehouse.evals import CASES, Case

EXTRA_CASES = (
    Case("nyiso_bus", question="What was the mean five-minute real-time bus LMP at NYISO_BUS_A on October 18, 2026 local time?",
         sql="SELECT avg(lmp) FROM core.nyiso_lmp_rt_bus_5min JOIN core.dim_location USING(location_id) WHERE location_code='NYISO_BUS_A' AND interval_start_local::DATE=DATE '2026-10-18'",
         tables=("core.nyiso_lmp_rt_bus_5min",), excluded=("core.nyiso_lmp_rt_hub_5min",), unit="USD/MWh"),
    Case("miso_storage", question="How much gross battery discharge energy in MWh did MISO deliver on October 17, 2026 local time? Use five-minute storage dispatch.",
         sql="SELECT sum(discharge_mw)/12 FROM core.miso_storage_dispatch_5min WHERE interval_start_local::DATE=DATE '2026-10-17'",
         tables=("core.miso_storage_dispatch_5min",), unit="MWh"),
    Case("spp_forecast", question="For SPP delivery at 14:00 local on October 19, 2026, what was the latest load forecast in MW published by October 18, 2026 18:00 UTC?",
         sql="SELECT forecast_mw FROM core.spp_load_forecast_hourly WHERE interval_start_local=TIMESTAMP '2026-10-19 14:00' AND publish_time_utc<=TIMESTAMP '2026-10-18 18:00' ORDER BY publish_time_utc DESC LIMIT 1",
         tables=("core.spp_load_forecast_hourly",), avoid=("demand_forecast_mw",), unit="MW"),
    Case("isone_spread", question="At ISONE_HUB on October 16, 2026 from noon to 1 pm local, what was mean five-minute real-time hub LMP minus day-ahead hourly hub LMP? Give the signed spread.",
         sql="SELECT (SELECT avg(lmp) FROM core.isone_lmp_rt_hub_5min WHERE interval_start_local>=TIMESTAMP '2026-10-16 12:00' AND interval_start_local<TIMESTAMP '2026-10-16 13:00')-(SELECT lmp FROM core.isone_lmp_da_hub_hourly WHERE interval_start_local=TIMESTAMP '2026-10-16 12:00')",
         tables=("core.isone_lmp_rt_hub_5min", "core.isone_lmp_da_hub_hourly"), unit="USD/MWh"),
    Case("pjm_queue", question="How many active wind projects are in PJM's interconnection queue?",
         sql="SELECT count(*) FROM core.queue_project JOIN core.dim_iso USING(iso_id) JOIN core.dim_fuel USING(fuel_id) WHERE iso_code='PJM' AND fuel_code='wind' AND status_code='active'",
         tables=("core.queue_project",), unit="projects", tolerance=0),
    Case("caiso_peak", question="What was California's maximum hourly demand in MW on August 8, 2025 local time?",
         sql="SELECT max(demand_mw) FROM core.fact_balance_hourly JOIN core.dim_iso USING(iso_id) WHERE iso_code='CAISO' AND interval_start_local::DATE=DATE '2025-08-08'",
         tables=("core.fact_balance_hourly",), unit="MW"),
)
BENCHMARK_CASES = CASES + EXTRA_CASES
