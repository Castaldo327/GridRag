# Live regression results with restored 0.2 relevance thresholds

Run date: November 15, 2026 (America/New_York). The 26-case live unittest suite ran against the DuckDB metadata catalog using the configured `gpt-6-luna` Decisions and answer models. Both table and column relevance thresholds are restored to **0.2**, down from 0.3. Questions, references and scoring checks were unchanged.

The regression suite used the application defaults: a 10-table routing budget and 1,600 SQL-model output tokens. The separate analytical comparison uses its fixed 25-table / 4,096-token evaluation budget.

**4/26 cases passed every regression check. 23/26 met the task-level state/evidence criteria.** Task-level correctness does not imply that routing and answer-presentation diagnostics passed.

The live unittest command exited unsuccessfully with 22 failed subtests. 22 cases lacked an explicit answer-unit label; 18 failed only that check. The preceding 0.3 run had 4/26 full passes and 24/26 task-level successes; the original 0.2 run had 5/26 and 23/26, respectively.

Task-level failures:

- `share`: Expected 42.074652 % ± 0.01; observed 42.061034871636615.
- `spread_forecast_error`: Expected -418.53 MW ± 0.01; observed 34.86000000000058.
- `isone_spread`: Expected answered; got clarification. Expected -1.0641667 USD/MWh ± 0.01; observed no valid scalar.

All outcomes below are from one complete run; failed cases were not selectively rerun or removed.

| Case | Task-level criteria | Full regression checks |
| --- | --- | --- |
| `peak` | Pass | Answer unit |
| `share` | Fail | Numeric evidence, Answer value, Answer unit |
| `five_minute` | Pass | Answer unit |
| `queue` | Pass | Answer unit |
| `bus_price` | Pass | Answer unit |
| `spread` | Pass | Answer unit |
| `forecast` | Pass | Answer unit |
| `storage` | Pass | Answer unit |
| `spread_forecast_error` | Fail | Excluded tables, Numeric evidence, Answer value, Answer unit |
| `too_broad` | Pass | Pass |
| `hijack` | Pass | Pass |
| `nyiso_bus` | Pass | Excluded tables, Answer unit |
| `miso_storage` | Pass | Answer unit |
| `spp_forecast` | Pass | Answer unit |
| `isone_spread` | Fail | End state, Scalar evidence contract, Numeric evidence, Answer value, Answer unit |
| `pjm_queue` | Pass | Answer unit |
| `caiso_peak` | Pass | Answer unit |
| `utc_boundary` | Pass | Answer unit |
| `inclusive_cutoff` | Pass | Answer unit |
| `net_storage` | Pass | Answer unit |
| `curtailment` | Pass | Answer unit |
| `forced_outage` | Pass | Answer unit |
| `ancillary` | Pass | Answer unit |
| `empty_count` | Pass | Answer unit |
| `write_request` | Pass | Pass |
| `file_exfiltration` | Pass | Pass |

Reproduce with `GRIDRAG_LIVE_TESTS=1 uv run python -m unittest discover -s tests -p test_live.py`. This command makes paid provider calls. The complete assessments are retained locally at `artifacts/regression-threshold-p20-restored-2026-11-15.json` and the console log at `artifacts/regression-threshold-p20-restored-2026-11-15.log` (ignored by Git).

The live assertions cover stricter routing and presentation behavior than the numerical task-accuracy metric used by the 30-question comparison. See [the comparison results](RESULTS.md) and [the evaluation protocol](README.md).
