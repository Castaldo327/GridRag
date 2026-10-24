# Live verification — October 23, 2026

Kept `gpt-6-luna` with reasoning `none`. Compared the existing detailed prompt with shorter alternatives using live provider calls. Reference SQL and expected answers were never sent to the model.

## Result

The selected prompt produced correct answers on review across 15 runs: the 11 existing cases, a fuel-share paraphrase and repeat, and different-region/month probes. Fourteen passed automated checks. The remaining answer correctly divided two returned operands; the checker expects the reference value directly in the CSV, so that case was verified manually. This is a small development evaluation, not a statistical accuracy guarantee.

| Metric, same 10 answerable runs | Existing prompt | Selected prompt |
| --- | ---: | ---: |
| Mean end-to-end latency | 6.39 s | 5.44 s |
| Median latency | 5.41 s | 4.68 s |
| Maximum observed latency | 13.19 s | 8.66 s |
| Mean estimated token cost | $0.001277 | $0.001143 |
| Total SQL attempts | 11 | 13 |

Mean latency was 15% lower and estimated cost 10% lower in this sample. The selected prompt still sometimes explores or repairs SQL; it did not reduce query count. Provider timing and cache state vary. The baseline and first candidate were interleaved; the selected candidate was evaluated afterward, so the latency difference cannot be attributed solely to the prompt. Costs use the configured illustrative rates, not billing records.

## What changed

The prompt now specifies evidence, correct grains, coverage, local dates and units, and an objective of minimizing unnecessary queries. It does not prescribe CTEs, joins, a single-query limit, product-specific branches, expected values, or fixed SQL templates. Repair rounds remain available.

Two shorter candidates were rejected: one used UTC month boundaries, another dropped five-minute observations when joining hourly prices. Rounded prose concealed the first error. Live checks now inspect numeric query evidence as well as prose, and correctly parse signed currency such as −$1.09. The evidence checker is conservative and still requires semantic review.

## Selected-prompt runs

| Case | Seconds | SQL attempts | Automatic check |
| --- | ---: | ---: | --- |
| peak | 4.05 | 1 | Pass |
| share | 8.66 | 3 | Pass |
| five_minute | 7.19 | 1 | Pass |
| queue | 3.83 | 1 | Pass |
| bus_price | 4.26 | 1 | Pass |
| spread | 7.12 | 1 | Pass |
| forecast | 4.60 | 1 | Pass |
| storage | 3.74 | 1 | Pass |
| too_broad | 0.41 | 0 | Pass |
| off_topic | 0.14 | 0 | Pass |
| hijack | 0.33 | 0 | Pass |
| share_paraphrase | 4.77 | 1 | Pass |
| share_repeat | 6.23 | 2 | Pass |
| share_other_region | 5.47 | 1 | Manual review: correct operands and percentage |
| share_other_month | 6.55 | 1 | Pass |

[Full selected-prompt traces and review notes](live-verification-results.json) include SQL, CSV, routing, timing and cost estimates.

Re-run the checked-in cases with:

```sh
GRIDRAG_LIVE_TESTS=1 uv run python -m unittest discover -s tests -p 'test_live.py'
```

The extra probes reword the PJM September share question, repeat it, and substitute ERCOT or August in both question and independent reference SQL. Different valid routes are allowed for those probes. Broader unseen-schema, missing-data, adversarial and repeated-seed evaluation remains future work.
