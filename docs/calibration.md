# Offline calibration

P01 uses unique observations and receipt cutoffs from the local pack. Measurements and candidate sweeps are in the aggregate report. The rule register identifies chosen and provisional values. [Aggregate report](../reports/calibration.json) · [Rules](../config/rules.json) · [Data quality](data-quality.md)

## Method

- Development covers October 4–24 UTC. Validation covers October 25–31 UTC and remains separate from fitting. Cadence splits use the latest required receipt. Outcome windows are censored as described in each cohort.
- Source hashes cover all six CSVs and telemetry files. SQLite holds unique observations on disk while the tools process the corpus. No service or network connection participates.
- Support labels are selected retrospective examples. They score observed causes and outcomes offline. Current features use receipts through the checkpoint. Case closures and later recovery are never available predictors. Background windows measure alert volume because ordinary windows have no complete outcome labels.

## Cadence and camera transitions

| Observation seconds | Development n | Median | p99 | Validation n | Median | p99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ignition-on T positions | 354,813 | 120.0 | 123.0 | 123,175 | 120.0 | 123.0 |
| Parked T heartbeats | 11,001 | 14,400.0 | 14,400.0 | 4,086 | 14,400.0 | 14,400.0 |
| Awake C recordings | 76,125 | 300.0 | 300.0 | 26,190 | 300.0 | 300.0 |
| Ignition-off to C sleep | 1,987 | 900.0 | 900.0 | 690 | 900.0 | 1,560.0 |
| Ignition-on to C boot | 2,003 | 5.0 | 665.0 | 694 | 5.0 | 665.0 |
| Ignition-on to first C recording observation | 2,009 | 35.0 | 695.0 | 697 | 35.0 | 695.0 |
| Ignition-on to usable C recording receipt | 2,009 | 38.0 | 699.0 | 697 | 38.0 | 699.0 |
| Healthy A daily | 1,358 | 86,400.0 | 88,500.0 | 376 | 86,340.0 | 88,680.0 |
| Healthy BX daily | 148 | 86,340.0 | 89,460.0 | 133 | 86,400.0 | 89,460.0 |

Parked cadence and the 4 h 30 min late boundary come from the brief. The camera transition sample uses conservative same-asset ignition joins. Recording after a reboot describes a later observation and does not establish the reboot as its cause. The report includes deadline sweeps and distinct pending competing or censored outcomes where observable. Firmware-specific visit routing remains unsupported, including the three supplied 4.3.0 cases.

## Battery, cold, and carrier sensitivity

- **Development battery and cold.** A ≤10% flags 11/11 selected case-opening readings. A strict comparator flags 7. The cold rule covers 6/12 labelled cold cases and 15/41 first-overdue probes. 11 of the covered probes next report within grace. These outcome counts are conditional on the cohort.
- **Validation battery and cold.** A ≤10% flags 0/0 selected case-opening readings. A strict comparator flags 0. The cold rule covers 7/11 labelled cold cases and 17/21 first-overdue probes. 11 of the covered probes next report within grace. These outcome counts are conditional on the cohort.
- **Development outages.** The chosen grid point detects 1/1 labelled cases for 48 labelled minute snapshots in 1 fragment(s). Background probes include 0/30152 alarming snapshots across 0 grouped episodes. The report includes grid sensitivity and fragmentation.
- **Validation outages.** The chosen grid point detects 1/1 labelled cases for 4 labelled minute snapshots in 1 fragment(s). Background probes include 0/10017 alarming snapshots across 0 grouped episodes. The report includes grid sensitivity and fragmentation.

At a 50% comparison share, the healthy-peer count sweep changes held-out detection duration (2 peers → 23 minutes, 3 peers → 4 minutes, 5 peers → 0 minutes). The development-selected values remain fixed. Runtime continuation uses evidence from the opening and follows member recovery separately. [Runtime policy](decisions.md#p06-carrier-incidents)

## Chosen thresholds

| Parameter | Value | Unit | Basis |
| --- | --- | --- | --- |
| `tracker_position_interval` | 120 | seconds | Candidate brief §1 |
| `tracker_parked_heartbeat_interval` | 14400 | seconds | Candidate brief §1 |
| `tracker_parked_overdue` | 16200 | seconds | Candidate brief §1 |
| `camera_sleep_delay` | 900 | seconds | Candidate brief §1 |
| `a_checkin_interval` | 86400 | seconds | Candidate brief §1 |
| `shift_start_local` | "06:00" | depot-local HH:MM | Candidate brief §1 |
| `ingest_batch_max` | 5000 | events | Vendor contract |
| `ingest_response_limit` | 10 | seconds | Vendor contract |
| `tracker_driving_overdue` | 360 | seconds | Development driving cadence and outage sweep |
| `camera_recording_overdue` | 600 | seconds | Development awake-camera cadence |
| `normal_receipt_lag` | 8 | seconds | Development first-receipt lag sweep |
| `a_daily_overdue` | 93600 | seconds | Development A healthy daily intervals |
| `bx_daily_overdue` | 93600 | seconds | Development BX healthy daily intervals |
| `bx_checkin_interval` | 86400 | seconds | Development BX healthy daily intervals |
| `a_legacy_timestamp_scale` | 1 | seconds per epoch unit | Legacy A numeric observations |
| `packet_epoch_start_seconds` | 946684800 | Unix seconds (2000-01-01T00:00:00Z) | P03 defensive packet clock policy |
| `packet_epoch_end_seconds_exclusive` | 4102444800 | Unix seconds (2100-01-01T00:00:00Z) | P03 defensive packet clock policy |
| `bx_epoch_radix` | 16 | base | Three vendor portal anchors |
| `bx_battery_full_scale` | 4095 | raw units | Three rounded vendor portal anchors |
| `bx_coordinate_scale` | 100000 | raw units per degree | Three vendor portal anchors |
| `bx_moving_mask` | 1 | bit mask | Vendor portal anchors and frame combinations |
| `bx_battery_low_mask` | 2 | bit mask | Vendor portal anchors and frame combinations |
| `bx_gps_fix_mask` | 8 | bit mask | Vendor portal anchors and frame combinations |
| `camera_wake_grace` | 60 | seconds | Development first-recording timings |
| `camera_reboot_response_grace` | 600 | seconds | Awake reboot response sweep and camera cadence |
| `camera_failed_reboots_before_visit` | 2 | distinct failed awake attempts | Support history and remote-first policy |
| `a_low_battery` | 10 | percent | Latest eligible telemetry at development battery case opening |
| `a_battery_recovery` | 20 | percent | A recovery transition sweep |
| `bx_battery_recovery` | 20 | percent | BX recovery transition sweep |
| `bx_percentage_only_low_enabled` | false | boolean | BX portal and stream flag comparison |
| `cold_temperature` | -10 | degrees Celsius | Development and held-out cold opportunity sweep |
| `cold_healthy_battery_minimum` | 25 | percent | Restricted healthy daily cohort |
| `cold_silence_limit` | 187200 | seconds | Cold recovery and first-overdue sweep |
| `urgent_operational_horizon` | 7200 | seconds | P00 working assumption, awaiting Larchmont policy |
| `uncertain_fast_reporting_windows` | 2 | calibrated reporting windows | P07 provisional false-alarm policy |
| `incident_close_below_remaining_devices` | 2 | serials | Contract incident cardinality and P00 episode policy |
| `seasonal_downtime_suppression_enabled` | false | boolean | Ops confirmation pending |
| `outage_probe_interval` | 60 | seconds | P01 carrier sensitivity grid |
| `outage_minimum_affected_devices` | 5 | serials | Development outage anchor and background snapshot grid |
| `outage_minimum_affected_share` | 0.5 | ratio | Development outage anchor and background snapshot grid |
| `outage_maximum_onset_spread_seconds` | 600 | seconds | Development outage anchor and background snapshot grid |
| `outage_minimum_healthy_comparison_devices` | 3 | serials | Development outage anchor and background snapshot grid |
| `outage_minimum_healthy_comparison_share` | 0.5 | ratio | Development outage anchor and background snapshot grid |
| `query_timestamp_requires_offset` | true | boolean | Contract UTC and P00 clock policy |
| `clock_ahead_tolerance` | 0 | seconds | P00 clock policy and supplied first-receipt distribution |
| `json_integer_max_digits` | 640 | decimal digits excluding sign | P13 malformed-batch regression and CPython's minimum integer conversion limit |
| `weak_signal_max` | 1 | modem signal level on the supplied 0–5 scale | Vendor heartbeat scale and P05 conservative engineering policy |
| `coverage_monitor_limit` | 5400 | seconds | P01 observed maximum T delivery lag of 5,396 seconds, rounded to 90 minutes |

Approval of seasonal downtime, the high-priority horizon, and the remaining Form 2 allowance are open. The acceptance suite covers camera escalation, cold grace, battery recovery, and carrier grouping. Hidden scenarios have separate coverage.

## Reproduce from the checkout root

```bash
python3.12 scripts/audit_data.py --data data
python3.12 scripts/calibrate.py --data data
```
