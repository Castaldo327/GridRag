# Warehouse Schema Reference

A small, **fictional** DuckDB warehouse of US grid data, rebuilt from scratch by `uv run python -m gridrag.warehouse.build`. Everything lives in the `core` schema.

| Source | What it defines |
|---|---|
| [schema.sql](schema.sql) | Hand-written dimensions, hourly/5-minute facts, and the queue table |
| [products.py](products.py) | Generated per-ISO "product" tables (prices, forecasts, ancillary, storage, outages, curtailment), each with the generator that fills it |
| [build.py](build.py) | Synthetic data generation and load (seeded, so every rebuild is identical) |

`build.schema_text()` concatenates `schema.sql` with the generated product DDL, so the full DDL is the union of both.

## At a glance

- **7 ISOs:** CAISO, ERCOT, ISONE, MISO, NYISO, PJM, SPP (`iso_id` 1–7). Each `Iso` in build.py sets its id explicitly, so adding an ISO never renumbers the others' rows, locations or `CHECK`s.
- **13 fuels**, **5 queue statuses**, **28 locations** (3 buses + 1 hub per ISO).
- **Core tables:** 4 dimensions + 4 facts + 1 queue table = 9 (65 tables in total).
- **Product tables:** 8 products × 7 ISOs = 56 tables, named `core.<iso>_<product>`.

### Time coverage

| Data | Local dates covered |
|---|---|
| Hourly balance and generation (all ISOs) | 2025-01-01 → 2026-10-21 |
| 5-minute load and generation (**CAISO and ERCOT only**) | 2026-10-15 → 2026-10-21 |
| All per-ISO product tables (all 7 ISOs) | 2026-10-15 → 2026-10-21 |
| Interconnection queue | Snapshot as of 2026-10-21 |

## Entity relationships

```
                        ┌──────────────┐
                        │   dim_iso    │
                        └──────┬───────┘
      ┌────────────┬───────────┼─────────────┬──────────────────┐
      │            │           │             │                  │
dim_location  fact_balance_  fact_generation_  fact_load_5min   queue_project ─── dim_queue_status
      │         hourly         hourly / _5min                     │
      │                           │                               │
      │                           └────────── dim_fuel ───────────┘
      │                                          │
      └──── <iso>_lmp_* (location_id)            └── <iso>_resource_outage_daily,
                                                     <iso>_renewable_curtailment_5min (fuel_id)
```

Fact and product tables carry `iso_id`; shared fuel and status dimensions do not.
Interval time series are keyed on `(iso_id, interval_start_utc, …)`; daily outages use `market_date`.

## Time conventions

- **`interval_start_utc`** is the primary key component and the join key between time series. Use it to join.
- **`interval_start_local`** is the same instant on the ISO's own clock. Use it for calendar filters ("on Tuesday", "hour 17"). It repeats during the fall-back hour, which is why it can't be a key.
- Intervals are labeled by their **start**.
- `dim_iso.timezone` gives the clock. MISO is `EST` (a fixed offset with no daylight saving); the others use IANA zones.

---

## Dimensions

### `core.dim_iso`
One row per grid operator.

| Column | Type | Notes |
|---|---|---|
| `iso_id` | SMALLINT PK | 1 CAISO, 2 ERCOT, 3 ISONE, 4 MISO, 5 NYISO, 6 PJM, 7 SPP |
| `iso_code` | VARCHAR, unique | e.g. `CAISO` |
| `timezone` | VARCHAR | Clock behind `interval_start_local` |

Example (`select * from core.dim_iso where iso_id <= 3`):

| iso_id | iso_code | timezone |
|---|---|---|
| 1 | CAISO | America/Los_Angeles |
| 2 | ERCOT | America/Chicago |
| 3 | ISONE | America/New_York |

### `core.dim_fuel`
Fuels and technologies, shared by generation facts, outages, curtailment and queue projects.

| Column | Type | Notes |
|---|---|---|
| `fuel_id` | SMALLINT PK | Order of definition (see below) |
| `fuel_code` | VARCHAR, unique | |
| `name` | VARCHAR | Display name |
| `category` | VARCHAR | `fossil`, `nuclear`, `renewable`, `storage`, `other` |
| `is_renewable` | BOOLEAN | True when category is `renewable` |
| `is_carbon_free` | BOOLEAN | True when category is `renewable` or `nuclear` |

Example rows:

| fuel_id | fuel_code | name | category | is_renewable | is_carbon_free |
|---|---|---|---|---|---|
| 1 | natural_gas | Natural gas | fossil | false | false |
| 4 | nuclear | Nuclear | nuclear | false | true |
| 7 | solar | Solar | renewable | true | true |
| 10 | battery | Battery storage | storage | false | false |

### `core.dim_location`
Fictional price points: **three buses and one hub per ISO** (28 rows).

| Column | Type | Notes |
|---|---|---|
| `location_id` | INTEGER PK | `iso_id * 10 + position`: 1=BUS_A, 2=BUS_B, 3=BUS_C, 4=HUB (e.g. PJM hub = 64) |
| `iso_id` | SMALLINT FK → dim_iso | |
| `location_code` | VARCHAR, unique | `<ISO>_BUS_A`, `_BUS_B`, `_BUS_C`, `<ISO>_HUB` |
| `location_type` | VARCHAR | `bus` or `hub`. Bus and hub IDs are not interchangeable, and there are no implied bus-to-hub weights |

Example (PJM, `iso_id` 6):

| location_id | iso_id | location_code | location_type |
|---|---|---|---|
| 61 | 6 | PJM_BUS_A | bus |
| 62 | 6 | PJM_BUS_B | bus |
| 63 | 6 | PJM_BUS_C | bus |
| 64 | 6 | PJM_HUB | hub |

### `core.dim_queue_status`

| `status_code` | Meaning |
|---|---|
| `active` | In study, agreement or construction |
| `withdrawn` | Withdrawn, cancelled, terminated or retracted |
| `completed` | Completed / in service |
| `suspended` | Suspended |
| `unknown` | Status not reported (defined but not used by the generator) |

---

## Facts (observed, hourly and 5-minute)

### `core.fact_balance_hourly`
PK `(iso_id, interval_start_utc)`. One row per ISO per hour.

| Column | Type | Notes |
|---|---|---|
| `iso_id` | SMALLINT FK | |
| `interval_start_utc`, `interval_start_local` | TIMESTAMP | |
| `demand_mw` | DOUBLE | Actual demand (load) |
| `demand_forecast_mw` | DOUBLE | One simple day-ahead estimate (about demand × 1.015). Has **no publication time**, so it is not valid for "forecast known at a cutoff" questions. Use `<iso>_load_forecast_hourly` for that |
| `net_generation_mw` | DOUBLE | Sum across all fuels; the **denominator for fuel shares** |

Example (CAISO, three consecutive hours; local time is UTC−7 in October):

| iso_id | interval_start_utc | interval_start_local | demand_mw | demand_forecast_mw | net_generation_mw |
|---|---|---|---|---|---|
| 1 | 2026-10-20 00:00 | 2026-10-19 17:00 | 37556.14 | 38119.48 | 31684.04 |
| 1 | 2026-10-20 01:00 | 2026-10-19 18:00 | 36773.14 | 37324.73 | 27442.26 |
| 1 | 2026-10-20 02:00 | 2026-10-19 19:00 | 35861.31 | 36399.23 | 26858.03 |

Demand and net generation are generated independently, so they do **not** balance (net generation is lower here).

### `core.fact_generation_hourly`
PK `(iso_id, interval_start_utc, fuel_id)`. MW averaged over the hour.

| Column | Type | Notes |
|---|---|---|
| `iso_id`, `fuel_id` | FK | |
| `interval_start_utc`, `interval_start_local` | TIMESTAMP | |
| `generation_mw` | DOUBLE NOT NULL | **Battery is net output: negative while charging** |

The generator emits only 7 of the 13 fuels: `natural_gas`, `coal`, `nuclear`, `hydro`, `wind`, `solar`, `battery`.

Example (CAISO, one hour, all fuels; `fuel_code` shown via a join to `dim_fuel`):

| iso_id | interval_start_utc | interval_start_local | fuel_code | generation_mw |
|---|---|---|---|---|
| 1 | 2026-10-20 20:00 | 2026-10-20 13:00 | natural_gas | 12388.46 |
| 1 | 2026-10-20 20:00 | 2026-10-20 13:00 | coal | 3097.11 |
| 1 | 2026-10-20 20:00 | 2026-10-20 13:00 | nuclear | 5032.81 |
| 1 | 2026-10-20 20:00 | 2026-10-20 13:00 | hydro | 3484.25 |
| 1 | 2026-10-20 20:00 | 2026-10-20 13:00 | wind | 4630.88 |
| 1 | 2026-10-20 20:00 | 2026-10-20 13:00 | solar | 14105.09 |
| 1 | 2026-10-20 20:00 | 2026-10-20 13:00 | battery | **−663.56** (charging) |

Fuel share example: solar share = 14105.09 / `net_generation_mw` for that same hour.

### `core.fact_load_5min`
PK `(iso_id, interval_start_utc)`. CAISO and ERCOT only, 2026-10-15 → 2026-10-21.

| Column | Type | Notes |
|---|---|---|
| `load_mw` | DOUBLE | Load (demand). Wobbles about ±0.6% around the demand shape, so it differs slightly from `fact_balance_hourly.demand_mw` |

Example (ERCOT; local time is UTC−5 in October):

| iso_id | interval_start_utc | interval_start_local | load_mw |
|---|---|---|---|
| 2 | 2026-10-20 18:00 | 2026-10-20 13:00 | 70673.33 |
| 2 | 2026-10-20 18:05 | 2026-10-20 13:05 | 70902.23 |
| 2 | 2026-10-20 18:10 | 2026-10-20 13:10 | 71225.61 |

### `core.fact_generation_5min`
PK `(iso_id, interval_start_utc, fuel_id)`. Same coverage and fuels as `fact_load_5min`. `generation_mw` is MW over the five minutes; battery is net (negative while charging).

Example (ERCOT, one interval, two of the fuels):

| iso_id | interval_start_utc | interval_start_local | fuel_code | generation_mw |
|---|---|---|---|---|
| 2 | 2026-10-20 18:00 | 2026-10-20 13:00 | solar | 12159.56 |
| 2 | 2026-10-20 18:00 | 2026-10-20 13:00 | battery | 84.36 |

---

## Interconnection queue

### `core.queue_project`
One row per project, current state as of 2026-10-21 (1,134 projects total; 106 to 220 per ISO). **No historical snapshots**, so entry dates can't reconstruct what the queue looked like earlier.

| Column | Type | Notes |
|---|---|---|
| `project_id` | INTEGER PK | |
| `iso_id` | SMALLINT FK | |
| `queue_id` | VARCHAR | ISO-prefixed, e.g. `PJM-0042` |
| `project_name`, `developer`, `county` | VARCHAR | Fictional |
| `state` | VARCHAR | Two-letter state |
| `fuel_id` | SMALLINT FK → dim_fuel | Queue fuels used: solar, battery, wind, natural_gas, hydro, nuclear, other |
| `technology` | VARCHAR | Fictional label (e.g. Photovoltaic, Combined Cycle) |
| `status_code` | VARCHAR FK → dim_queue_status | |
| `status_raw` | VARCHAR | Raw label behind the code (e.g. "FIS In Progress", "Canceled") |
| `capacity_mw` | DOUBLE | **Proposed** capacity, not built capacity or output |
| `is_hybrid` | BOOLEAN | Non-storage project paired with storage |
| `queue_date` | DATE | Entered the queue |
| `proposed_cod` | DATE | Proposed commercial operation date |
| `withdrawn_date` | DATE | Only set when status is `withdrawn` |
| `completed_date` | DATE | Only set when status is `completed` |

Examples (three CAISO projects, one per status; some columns omitted for width):

| project_id | queue_id | project_name | fuel | technology | status_code | status_raw | capacity_mw | is_hybrid | queue_date | proposed_cod | withdrawn_date | completed_date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | CAISO-0001 | CAISO Battery 1 | battery | Battery Storage | active | Active | 38.0 | false | 2026-08-02 | 2028-08-01 | null | null |
| 4 | CAISO-0004 | CAISO Natural Gas 4 | natural_gas | Combined Cycle | completed | In Service | 149.0 | false | 2026-05-01 | 2028-05-03 | null | 2027-12-22 |
| 5 | CAISO-0005 | CAISO Other 5 | other | Other | withdrawn | Withdrawn | 186.0 | false | 2026-03-31 | 2028-04-03 | 2027-01-25 | null |

Synthetic-data quirk: `completed_date` and `withdrawn_date` are computed as offsets from `queue_date` (+600 and +300 days), so they can fall **after** the 2026-10-21 snapshot date, as the completed and withdrawn rows above do. Don't treat them as reliable real dates.

---

## Per-ISO product tables

Generated in [products.py](products.py): each product below exists once per ISO, as `core.<iso>_<suffix>` (lowercase ISO, e.g. `core.caiso_lmp_rt_hub_5min`). Each table's `iso_id` has a `CHECK` pinning it to that ISO. All cover 2026-10-15 → 2026-10-21 and all columns are `NOT NULL`. A product defines its columns, comments and a `generate` function, so its DDL and rows come from one definition.

The products are **deliberately similar** (bus vs hub, real-time vs day-ahead, forecast vs actual, reserve vs energy, observed storage vs queue capacity). Pick the one that matches the question's market, grain and time semantics.

Routing treats each product's seven tables as one **family**: the decision model reads a single definition with the ISO left open (`core.<iso>_<suffix>`) and separately scores which ISOs the question needs, and the router keeps those ISOs' tables. The SQL model still receives each kept table's own DDL.

| Kind | Suffix | Grain | Primary key (after `iso_id`) |
|---|---|---|---|
| prices | `lmp_rt_bus_5min` | 5 min × 3 buses | `interval_start_utc, location_id` |
| prices | `lmp_rt_hub_5min` | 5 min × hub | `interval_start_utc, location_id` |
| prices | `lmp_da_hub_hourly` | hourly × hub | `interval_start_utc, location_id` |
| forecasts | `load_forecast_hourly` | hourly × 4 vintages | `interval_start_utc, publish_time_utc` |
| ancillary | `ancillary_prices_hourly` | hourly × 3 services | `interval_start_utc, service_code` |
| storage | `storage_dispatch_5min` | 5 min | `interval_start_utc` |
| outages | `resource_outage_daily` | daily × fuel × type | `market_date, fuel_id, outage_type` |
| curtailment | `renewable_curtailment_5min` | 5 min × fuel | `interval_start_utc, fuel_id` |

### Prices: `lmp_rt_bus_5min`, `lmp_rt_hub_5min`, `lmp_da_hub_hourly`
Columns: `interval_start_utc`, `interval_start_local`, `location_id` (FK → dim_location), then:

| Column | Notes |
|---|---|
| `lmp` | Total price, USD/MWh. **Equals `energy + congestion + loss`** |
| `energy`, `congestion`, `loss` | Components, USD/MWh |

- **Bus** tables use locations 1–3 (BUS_A–C); **hub** tables use location 4.
- Real-time is not day-ahead. To compare, average the 5-minute real-time hub price to the hour first.

Example (PJM, one instant, 2026-10-20 18:00 local = 22:00 UTC). Note `lmp = energy + congestion + loss`, e.g. 40.46 + 15.84 + 0.98 = 57.28:

`pjm_lmp_rt_bus_5min` (three buses, same energy price, different congestion and loss):

| iso_id | interval_start_utc | interval_start_local | location_id | lmp | energy | congestion | loss |
|---|---|---|---|---|---|---|---|
| 6 | 2026-10-20 22:00 | 2026-10-20 18:00 | 61 | 51.58 | 40.46 | 10.74 | 0.38 |
| 6 | 2026-10-20 22:00 | 2026-10-20 18:00 | 62 | 53.48 | 40.46 | 12.44 | 0.58 |
| 6 | 2026-10-20 22:00 | 2026-10-20 18:00 | 63 | 55.38 | 40.46 | 14.14 | 0.78 |

`pjm_lmp_rt_hub_5min` (the hub, location 64):

| iso_id | interval_start_utc | interval_start_local | location_id | lmp | energy | congestion | loss |
|---|---|---|---|---|---|---|---|
| 6 | 2026-10-20 22:00 | 2026-10-20 18:00 | 64 | 57.28 | 40.46 | 15.84 | 0.98 |

`pjm_lmp_da_hub_hourly` (same hub, day-ahead market, so a different price):

| iso_id | interval_start_utc | interval_start_local | location_id | lmp | energy | congestion | loss |
|---|---|---|---|---|---|---|---|
| 6 | 2026-10-20 22:00 | 2026-10-20 18:00 | 64 | 59.04 | 40.46 | 17.60 | 0.98 |

### `load_forecast_hourly`
Columns: `interval_start_utc`, `interval_start_local`, `publish_time_utc`, `forecast_mw`.

- Four vintages per delivery hour, published **30, 18 and 6 hours before** delivery and **1 hour after** (hindsight; it must be excluded by any cutoff before delivery).
- To answer "what was forecast as of time T": keep rows with `publish_time_utc <= T`, then take the latest per delivery hour.
- Forecast, never actual demand.

Example (PJM, delivery hour 2026-10-20 22:00 UTC, four vintages):

| interval_start_utc | publish_time_utc | forecast_mw | Known at cutoff 2026-10-20 12:00 UTC? |
|---|---|---|---|
| 2026-10-20 22:00 | 2026-10-19 16:00 | 92945.60 | yes (older) |
| 2026-10-20 22:00 | 2026-10-20 04:00 | 90979.83 | **yes, the latest at or before cutoff** |
| 2026-10-20 22:00 | 2026-10-20 16:00 | 88299.22 | no (after cutoff) |
| 2026-10-20 22:00 | 2026-10-20 23:00 | 89460.82 | no (published after delivery) |

### `ancillary_prices_hourly`
Columns: `interval_start_utc`, `interval_start_local`, `service_code` (`regulation_up`, `regulation_down`, `spinning_reserve`), `clearing_price` (USD/**MW-hour**). Not energy LMPs.

Example (PJM, 2026-10-20 22:00 UTC):

| interval_start_utc | service_code | clearing_price |
|---|---|---|
| 2026-10-20 22:00 | regulation_down | 10.40 |
| 2026-10-20 22:00 | regulation_up | 23.39 |
| 2026-10-20 22:00 | spinning_reserve | 15.59 |

### `storage_dispatch_5min`
Observed battery behavior (not queue capacity, not fuel generation).

| Column | Notes |
|---|---|
| `charge_mw` | Power into batteries, positive |
| `discharge_mw` | Power out of batteries, positive |
| `net_output_mw` | `discharge_mw - charge_mw`; negative while charging |
| `state_of_charge_mwh` | Stored energy at interval start, MWh (energy, not power) |

Example (`caiso_storage_dispatch_5min`; charging at midday solar, discharging in the evening):

| interval_start_utc | interval_start_local | charge_mw | discharge_mw | net_output_mw | state_of_charge_mwh |
|---|---|---|---|---|---|
| 2026-10-20 20:00 | 2026-10-20 13:00 | 652.5 | 0.0 | −652.5 | 2367.87 |
| 2026-10-21 02:00 | 2026-10-20 19:00 | 0.0 | 1015.0 | 1015.0 | 2102.50 |

### `resource_outage_daily`
Columns: `market_date` (ISO-local day), `fuel_id`, `outage_type` (`planned` or `forced`), `unavailable_mw`. Covers `natural_gas`, `nuclear` and `battery`. MW of capacity unavailable that day, not lost energy.

Example (`pjm_resource_outage_daily`, 2026-10-20; fuel shown via join to `dim_fuel`):

| market_date | fuel_code | outage_type | unavailable_mw |
|---|---|---|---|
| 2026-10-20 | natural_gas | planned | 250.0 |
| 2026-10-20 | natural_gas | forced | 293.0 |
| 2026-10-20 | nuclear | planned | 267.0 |
| 2026-10-20 | nuclear | forced | 310.0 |
| 2026-10-20 | battery | planned | 284.0 |
| 2026-10-20 | battery | forced | 327.0 |

### `renewable_curtailment_5min`
Columns: `interval_start_utc`, `interval_start_local`, `fuel_id` (solar or wind), `curtailed_mw`. This is power; **MWh = MW / 12** per 5-minute interval. It is curtailed output, not generation.

Example (`caiso_renewable_curtailment_5min`, one interval): solar 282.10 MW is about 23.5 MWh over those five minutes (282.10 / 12).

| interval_start_utc | interval_start_local | fuel_code | curtailed_mw |
|---|---|---|---|
| 2026-10-20 20:00 | 2026-10-20 13:00 | solar | 282.10 |
| 2026-10-20 20:00 | 2026-10-20 13:00 | wind | 92.62 |

---

## Easy-to-miss gotchas

1. **Join on UTC**, filter on local.
2. 5-minute facts exist for **CAISO and ERCOT only**, while product tables exist for all seven ISOs.
3. `fact_balance_hourly.demand_forecast_mw` is not a point-in-time forecast. Use `load_forecast_hourly` with a cutoff.
4. Battery generation is signed (negative = charging); `storage_dispatch_5min` uses positive magnitudes.
5. Queue `capacity_mw` is proposed, not operating capacity; the queue has no history.
6. `lmp` already includes the three components; don't add them again.
7. Hub and bus `location_id`s are different grains. Don't mix them in an average.
8. Fuel shares: divide `fact_generation_*` by `net_generation_mw` (hourly), not `demand_mw`.
