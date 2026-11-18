# Data quality audit

Regenerate locally with `python3.12 scripts/audit_data.py --data data`. The [JSON report](../reports/data-audit.json) includes all file hashes, headers, blank counts, references, cohort sizes, and the supporting aggregates.

## Reference and stream checks

| Reference table | Rows | Duplicate primary key excess |
|---|---:|---:|
| `assets.csv` | 251 | 0 |
| `devices.csv` | 360 | 0 |
| `schedule.csv` | 8,957 | 0 |
| `weather.csv` | 62 | 0 |
| `plan_changes.csv` | 22 | 0 |
| `support_cases.csv` | 179 | 0 |

Device families are A (76), BX (20), C (93), T (171). Roster statuses are active (341), removed (6), stock (13). Blank VINs and assignments occur in different cohorts. An empty roster assignment cannot rule out observed operation.

The audit scanned 28 daily files and 640,419 nonblank envelopes. It found 0 malformed envelopes, 0 ignored unknown types and 0 distinct unresolved serials. The audit found 0 observations ahead of receipt, 0 receipt inversions, and 0 receipt-day mismatches.

The stream and CSV contain 22 and 22 plan event IDs respectively. The report records 0 reference-only, 0 stream-only, and 0 matched-ID field disagreements. The reference has no independent receipt timestamp.

## Identity, clocks and buffering

Known and decodable envelopes yield 635,066 distinct IDs and 632,810 logical observations. There are 5,353 repeated IDs, 7,609 semantic retries across 7,608 groups, and 2,256 new-ID aliases. There are 0 conflicting-ID envelopes.

The semantic key uses serial, kind, normalized observation instant and sorted canonical payload. The audit retains the lowest receipt for the logical observation, breaking ties by event ID. The first valid content wins a conflicting ID. The audit counts aliases after validating relevant envelopes and ignores unused kinds. Latency is first receipt minus observation, excluding ahead-of-receipt clocks. Quantiles are nearest rank.

| Family / firmware | Observations | Median lag (s) | P99 lag (s) | Max lag (s) |
|---|---:|---:|---:|---:|
| A/1.9.0 | 247 | 3 | 5 | 5 |
| A/2.0.4 | 1,705 | 3 | 5 | 5 |
| BX/unknown | 308 | 5 | 8 | 8 |
| C/4.2.1 | 56,723 | 3 | 5 | 6 |
| C/4.3.0 | 59,724 | 3 | 5 | 6 |
| T/7.1.2 | 323,243 | 4 | 665 | 5384 |
| T/7.2.0 | 190,860 | 3 | 218 | 5396 |

For T/7.2.0, the lower order statistic used by the kit gives p99 213 s on the same 190,860 observations. The table uses nearest rank at 218 s.

Across 7,609 retry receipts, receipt-to-first-receipt lag has a median of 301 s and a maximum of 599 s. Long tracker delivery tails are compatible with buffering. Receipt lag measures delivery, and calibration uses a separate observation cadence calculation.

The stream contains 252 legacy A numeric-clock envelopes. There are 313 BX envelopes without outer serial or device time and 308 logical BX observations. BX timestamps are hex epoch seconds.

## VIN and seasonal patterns

The audit found 155 distinct known asset VINs, 7 shared VIN timelines. Flagged serial/VIN associations number 1. Flagged associations disagree with the roster or need a unique reference VIN. The JSON preserves the observed time bounds. Historical assignment requires evidence available at the query cutoff.

- Stock serial `T-58830` has 1,084 envelopes and first reports the known VIN of `V-214` at 2026-10-24T00:26:00Z.

Landscaping trailers number 12. Their last local observation dates are 2026-10-23 (12). This pattern leaves approved downtime scope and dates unresolved.

## Selected support cases

Case counts by cause are battery_low (11), camera_fault (40), carrier_outage (2), cold_weather (23), coverage_gap (14), device_swapped (6), parked_normal (26), plan_paused (11), power_loss (14), sleeping_by_design (32). The case rows represent selected reports and fixes. Their mix can support a prior or case-aligned evaluation. It provides no fleet-wide error denominator.

| Camera fault firmware | Cases | Actions |
|---|---:|---|
| 4.2.1 | 37 | remote_reboot (27), technician_visit (10) |
| 4.3.0 | 3 | remote_reboot (1), technician_visit (2) |

The duration analysis excludes 1 flagged case rows. Flagged case IDs are CS-0016.

## BX reference comparison

Decoded 300 separate sample frames from 20 serials and matched 3 of 3 supplied portal rows across every displayed field. Battery full-scale conversion is an inference from rounded examples. Unknown flag values and counts are 0 (294), 4 (6).
