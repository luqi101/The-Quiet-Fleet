"""Reproduce offline threshold measurements and the P01 threshold register."""

import argparse
import hashlib
import json
from pathlib import Path

if __package__:
    from .audit_data import open_dataset
    from .battery_analysis import (
        COLD_CANDIDATES, COLD_GRACE_CANDIDATES, DAILY_CANDIDATES, HOLDOUT, HOUR,
        LOW_CANDIDATES, RECOVERY_CANDIDATES, measure_daily,
    )
    from .outage_analysis import measure_outages
    from .timing_analysis import measure_timing
else:
    from audit_data import open_dataset
    from battery_analysis import (
        COLD_CANDIDATES, COLD_GRACE_CANDIDATES, DAILY_CANDIDATES, HOLDOUT, HOUR,
        LOW_CANDIDATES, RECOVERY_CANDIDATES, measure_daily,
    )
    from outage_analysis import measure_outages
    from timing_analysis import measure_timing

SPLIT = {"development_utc": "[2026-10-04, 2026-10-25)", "validation_utc": "[2026-10-25, 2026-11-01)"}
LAG_CANDIDATES = (5, 8, 10, 20, 30, 60)


def canonical_json(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def classify_lag(conn):
    result = {}
    for split, restriction in (("development", "<"), ("validation", ">=")):
        bins = list(conn.execute(f"""
            SELECT received - observed AS lag, COUNT(*) AS n
            FROM events
            WHERE kind NOT IN ('command', 'plan_change') AND observed <= received
              AND received {restriction} ?
            GROUP BY lag ORDER BY lag
        """, (HOLDOUT,)))
        n = sum(row["n"] for row in bins)
        routine_n = sum(row["n"] for row in bins if row["lag"] <= max(LAG_CANDIDATES))
        result[split] = {
            "n": n,
            "lag_over_60_seconds": n - routine_n,
            "max_seconds": bins[-1]["lag"] if bins else None,
            "candidates": {
                str(limit): {
                    "at_or_below": sum(row["n"] for row in bins if row["lag"] <= limit),
                    "routine_cohort_n": routine_n,
                } for limit in LAG_CANDIDATES
            },
        }
    return result


def entry(value, unit, comparator, provenance, rationale, test, sensitivity=(), sample_size=None):
    return {
        "value": value,
        "unit": unit,
        "comparator": comparator,
        "provenance": provenance,
        "rationale": rationale,
        "sample_size": sample_size,
        "sensitivity_candidates": list(sensitivity),
        "test": test,
    }


def first_candidate(sweep, minimum):
    candidates = sorted(int(key) for key in sweep)
    return next((candidate for candidate in candidates if candidate >= minimum), candidates[-1])


def build_rules(report):
    timing = report["timing"]["development"]
    daily = report["daily"]
    outage = report["outage"]
    lag = report["receipt_lag"]["development"]
    selected_outage = outage["selected"]["thresholds"]
    given = {
        "tracker_position_interval": entry(120, "seconds", "target cadence", "Candidate brief §1", "Ignition-on T position cadence.", "C01"),
        "tracker_parked_heartbeat_interval": entry(14_400, "seconds", "target cadence", "Candidate brief §1", "Ignition-off T heartbeat cadence.", "C03"),
        "tracker_parked_overdue": entry(16_200, "seconds", "elapsed > value", "Candidate brief §1", "Four hours 30 minutes with no valid report.", "C04"),
        "camera_sleep_delay": entry(900, "seconds", "elapsed >= value", "Candidate brief §1", "Expected sleep after asset ignition off.", "C07–C09"),
        "a_checkin_interval": entry(86_400, "seconds", "target cadence", "Candidate brief §1", "A tags normally check in daily.", "C11–C13"),
        "shift_start_local": entry("06:00", "depot-local HH:MM", "daily instant", "Candidate brief §1", "Join operational deadlines in the asset's depot zone.", "F05–F06"),
        "ingest_batch_max": entry(5_000, "events", "count <= value", "Vendor contract", "Largest supported HTTP batch.", "A11"),
        "ingest_response_limit": entry(10, "seconds", "elapsed <= value", "Vendor contract", "Full-size request deadline. Release verification targets strictly under ten seconds.", "H07"),
    }
    wire = {
        "a_legacy_timestamp_scale": entry(1, "seconds per epoch unit", "multiply", "Legacy A numeric observations", "Decode numeric device times as epoch seconds.", "test_timestamp_offsets_and_epoch_units"),
        "bx_epoch_radix": entry(16, "base", "parse in radix", "Three vendor portal anchors", "Hexadecimal Unix epoch seconds.", "test_bx_anchor_and_unknown_bits", sample_size=3),
        "bx_battery_full_scale": entry(4095, "raw units", "100 × raw / value", "Three rounded vendor portal anchors", "12-bit full-scale inference.", "G01–G02", sample_size=3),
        "bx_coordinate_scale": entry(100_000, "raw units per degree", "raw / value", "Three vendor portal anchors", "Decode the two signed coordinate integers.", "G01", sample_size=3),
        "bx_moving_mask": entry(1, "bit mask", "(flags & value) != 0", "Vendor portal anchors and frame combinations", "Moving flag.", "G01–G03", sample_size=3),
        "bx_battery_low_mask": entry(2, "bit mask", "(flags & value) != 0", "Vendor portal anchors and frame combinations", "Low battery flag includes the 14% portal example.", "G01, G09", sample_size=3),
        "bx_gps_fix_mask": entry(8, "bit mask", "(flags & value) != 0", "Vendor portal anchors and frame combinations", "A no-fix frame retains contact without a new position.", "G01, G07", sample_size=3),
    }
    drive = timing["tracker_driving_gap_seconds"]
    drive_sweep = timing["tracker_driving_lateness_sweep"]
    record = timing["camera_recording_gap_seconds"]
    record_sweep = timing["camera_recording_lateness_sweep"]
    recording_late = first_candidate(record_sweep, (record["p50"] or 300) + (record["p95"] or 300))
    wake = timing["camera_first_recording_available_delay_seconds"]
    wake_sweep = timing["camera_wake_sweep"]
    wake_grace = first_candidate(wake_sweep, (wake["p95"] or 120) + 10)
    lag_limit = next((limit for limit in LAG_CANDIDATES
                      if lag["candidates"][str(limit)]["at_or_below"] >=
                      0.99 * lag["candidates"][str(limit)]["routine_cohort_n"]), 60)
    calibrated = {
        "tracker_driving_overdue": entry(
            selected_outage["tracker_due_seconds"], "seconds", "elapsed > value",
            "Development driving cadence and outage sweep", "The observed within-drive maximum is 123 seconds. The grid ties retain the kit's three-position allowance. Use the same deadline for status and cohort analysis.",
            "C05, E01–E03", sorted(map(int, drive_sweep)), drive["n"],
        ),
        "camera_recording_overdue": entry(
            recording_late, "seconds", "elapsed > value", "Development awake-camera cadence",
            "First tested value covering a median recording interval plus the p95 interval.",
            "D06", sorted(map(int, record_sweep)), record["n"],
        ),
        "normal_receipt_lag": entry(
            lag_limit, "seconds", "receipt minus observation <= value", "Development first-receipt lag sweep",
            "Smallest tested bound covering 99% of the routine cohort with lag at most 60 seconds. Larger lag remains recorded.",
            "B13, D30", LAG_CANDIDATES, lag["candidates"][str(lag_limit)]["routine_cohort_n"],
        ),
    }
    for family, name in (("A", "a_daily_overdue"), ("BX", "bx_daily_overdue")):
        daily_family = daily["families"][family]
        cohort = daily_family["split"]["development"]["healthy_gap_seconds"]
        calibrated[name] = entry(
            daily_family["selected_deadline_seconds"], "seconds", "elapsed > value", f"Development {family} healthy daily intervals",
            "Minimum tested deadline with zero eligible cohort crossings and at least one hour beyond p99.",
            "C11–C14, G11", (h * HOUR for h in DAILY_CANDIDATES), cohort["n"],
        )
    low = daily["case_and_opportunity_evaluation"]["development"]
    low_case_sweep = low["battery_low_case_threshold_sweep"]
    low_cutoff = next((t for t in LOW_CANDIDATES if low["battery_low_case_n"]
                       and low_case_sweep[str(t)]["at_or_below"] == low["battery_low_case_n"]), 10)
    provisional = {
        "camera_wake_grace": entry(wake_grace, "seconds", "elapsed <= value", "Development first-recording timings",
                                   "First tested grace at or above first-recording p95 plus receipt margin. Runtime should retest its boundary.", "C09–C10", sorted(map(int, wake_sweep)), wake["n"]),
        "camera_reboot_response_grace": entry(600, "seconds", "elapsed >= value", "Awake reboot response sweep and camera cadence",
                                             "Allow two ordinary recording opportunities to avoid premature escalation. The shorter tested window caught the same observed responses in a small selected sample.", "D07–D12",
                                             sorted(map(int, timing["camera_reboot"]["response_sweep"])),
                                             timing["camera_reboot"]["response_sweep"]["600"]["within"] +
                                             timing["camera_reboot"]["response_sweep"]["600"]["absent"]),
        "camera_failed_reboots_before_visit": entry(2, "distinct failed awake attempts", "count >= value", "Support history and remote-first policy", "Two failures in one episode justify a physical check. Wear and case selection limit the evidence.", "D07–D10", (1, 2, 3)),
        "a_low_battery": entry(low_cutoff, "percent", "reading <= value", "Latest eligible telemetry at development battery case opening",
                               "Smallest inclusive tested cutoff covering the available selected case readings. Validation has no labelled battery cases.", "D20–D22", LOW_CANDIDATES, low["battery_low_case_n"]),
        "a_battery_recovery": entry(20, "percent", "reading >= value", "A recovery transition sweep", "A hysteresis margin above the low threshold. The observed replacements do not identify a unique boundary.", "D21–D22", RECOVERY_CANDIDATES),
        "bx_battery_recovery": entry(20, "percent", "reading >= value and low flag clear", "BX recovery transition sweep", "Conservative clear with hysteresis. No labelled recovery identifies an exact cutoff.", "G14", RECOVERY_CANDIDATES),
        "bx_percentage_only_low_enabled": entry(False, "boolean", "low flag governs", "BX portal and stream flag comparison", "The supplied readouts support the flag. Percentage-only decisions have no independent outcome labels.", "G09", (False, True)),
        "cold_temperature": entry(-10, "degrees Celsius", "depot local-day low <= value", "Development and held-out cold opportunity sweep",
                                  "Apply only to a healthy recent A battery context. This is bounded suppression of an unconfirmed symptom.", "D23–D26", COLD_CANDIDATES, low["cold_case_n"]),
        "cold_healthy_battery_minimum": entry(25, "percent", "latest eligible reading >= value", "Restricted healthy daily cohort", "Require positive battery margin before cold can explain a missed report.", "D23–D24", (20, 25, 30)),
        "cold_silence_limit": entry(52 * HOUR, "seconds", "elapsed <= value", "Cold recovery and first-overdue sweep", "Allow roughly one extra daily opportunity. Surface uncertainty when the grace expires.", "D23–D26",
                                   (h * HOUR for h in COLD_GRACE_CANDIDATES), low["first_overdue_opportunities"]),
        "urgent_operational_horizon": entry(2 * HOUR, "seconds", "deadline - at <= value", "P00 working assumption, awaiting Larchmont policy", "Budget preparation time before scheduled use. Allow a pending remote check to finish when its response deadline precedes the work deadline.", "E16–E18, F01–F07", (HOUR, 2 * HOUR, 4 * HOUR)),
        "uncertain_fast_reporting_windows": entry(2, "calibrated reporting windows", "elapsed > value times the family allowance", "P07 provisional false-alarm policy",
                                                   "Require prolonged fast-report silence and near-term scheduled use before opening an uncertain support follow-up.", "E14–E18, E20", (2, 3)),
        "incident_close_below_remaining_devices": entry(2, "serials", "remaining < value", "Contract incident cardinality and P00 episode policy",
                                                      "A group requires several devices. Reevaluate remaining serials individually.", "E08–E10", (2, 3)),
        "seasonal_downtime_suppression_enabled": entry(False, "boolean", "requires approved scope and effective dates", "Ops confirmation pending", "Observed seasonal silence supports an investigation without approval for suppression.", "D27–D29", (False, True)),
    }
    probe_seconds = outage["methodology"]["snapshot_seconds"]
    provisional["outage_probe_interval"] = entry(
        probe_seconds, "seconds", "opening probes on UTC multiples of value", "P01 carrier sensitivity grid",
        "Use the calibrated sampling grid to reconstruct openings with a stable identity. Member recovery uses the exact receipt cutoff.",
        "E01–E11, H04", (probe_seconds,),
        sum(outage["selected"][split]["background_samples"] for split in ("development", "validation")),
    )
    outage_units = {
        "minimum_affected_devices": ("serials", "count >= value"),
        "minimum_affected_share": ("ratio", "share >= value"),
        "maximum_onset_spread_seconds": ("seconds", "spread <= value"),
        "minimum_healthy_comparison_devices": ("serials", "count >= value"),
        "minimum_healthy_comparison_share": ("ratio", "share >= value"),
    }
    for name, (unit, comparator) in outage_units.items():
        provisional[f"outage_{name}"] = entry(
            selected_outage[name], unit, comparator, "Development outage anchor and background snapshot grid",
            "Requires carrier-specific contrast and distinct due reporters. One labelled incident per split limits inference.",
            "E01–E11, H04",
            sorted({candidate["thresholds"][name] for candidate in (
                outage["candidates"] + outage["comparison_sensitivity"]
            )}),
            outage["selected"]["development"]["background_samples"],
        )
    return {
        "schema_version": 1,
        "given_rules": given,
        "wire_format_constants": wire,
        "calibrated_parameters": calibrated,
        "operational_assumptions": provisional,
        "defensive_limits": {
            "query_timestamp_requires_offset": entry(True, "boolean", "explicit UTC offset required", "Contract UTC and P00 clock policy",
                                                     "Timezone-aware input avoids host-local interpretation.", "A09, test_timestamp_offsets_and_epoch_units"),
            "clock_ahead_tolerance": entry(0, "seconds", "observation - receipt > value means clock quality uncertain",
                                           "P00 clock policy and supplied first-receipt distribution", "Keep the receipt for contact and withhold future-dated state.", "B14–B16", (0, 5, 30)),
        },
    }


def render_docs(report, rules):
    daily = report["daily"]
    timing = report["timing"]
    printed = [
        "# Offline calibration",
        "",
        "P01 uses unique observations and receipt cutoffs from the local pack. Measurements and candidate sweeps are in the aggregate report. The rule register identifies chosen and provisional values. [Aggregate report](../reports/calibration.json) · [Rules](../config/rules.json) · [Data quality](data-quality.md)",
        "",
        "## Method",
        "",
        "- Development covers October 4–24 UTC. Validation covers October 25–31 UTC and remains separate from fitting. Cadence splits use the latest required receipt. Outcome windows are censored as described in each cohort.",
        "- Source hashes cover all six CSVs and telemetry files. SQLite holds unique observations on disk while the tools process the corpus. No service or network connection participates.",
        "- Support labels are selected retrospective examples. They score observed causes and outcomes offline. Current features use receipts through the checkpoint. Case closures and later recovery are never available predictors. Background windows measure alert volume because ordinary windows have no complete outcome labels.",
        "",
        "## Cadence and camera transitions",
        "",
        "| Observation seconds | Development n | Median | p99 | Validation n | Median | p99 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    timing_rows = (
        ("Ignition-on T positions", "tracker_driving_gap_seconds"),
        ("Parked T heartbeats", "tracker_parked_heartbeat_gap_seconds"),
        ("Awake C recordings", "camera_recording_gap_seconds"),
        ("Ignition-off to C sleep", "camera_sleep_delay_seconds"),
        ("Ignition-on to C boot", "camera_boot_delay_seconds"),
        ("Ignition-on to first C recording observation", "camera_first_recording_delay_seconds"),
        ("Ignition-on to usable C recording receipt", "camera_first_recording_available_delay_seconds"),
    )
    rows = [(label, timing["development"][key], timing["validation"][key]) for label, key in timing_rows]
    rows += [(f"Healthy {family} daily", summary["split"]["development"]["healthy_gap_seconds"],
              summary["split"]["validation"]["healthy_gap_seconds"]) for family, summary in daily["families"].items()]
    for label, development, validation in rows:
        columns = (development[key] for key in ("n", "p50", "p99"))
        held_out = (validation[key] for key in ("n", "p50", "p99"))
        printed.append(f"| {label} | " + " | ".join("—" if x is None else f"{x:,}" for x in (*columns, *held_out)) + " |")
    printed.extend([
        "",
        "Parked cadence and the 4 h 30 min late boundary come from the brief. The camera transition sample uses conservative same-asset ignition joins. Recording after a reboot describes a later observation and does not establish the reboot as its cause. The report includes deadline sweeps and distinct pending competing or censored outcomes where observable. Firmware-specific visit routing remains unsupported, including the three supplied 4.3.0 cases.",
        "",
        "## Battery, cold, and carrier sensitivity",
        "",
    ])
    case_eval = daily["case_and_opportunity_evaluation"]
    a_cutoff = rules["operational_assumptions"]["a_low_battery"]["value"]
    cold_limit = rules["operational_assumptions"]["cold_silence_limit"]["value"]
    cold_temp = rules["operational_assumptions"]["cold_temperature"]["value"]
    for split, result in case_eval.items():
        low = result["battery_low_case_threshold_sweep"][str(a_cutoff)]
        cold = next(row for row in result["cold_sweep"] if row["temp_c"] == cold_temp and row["grace_seconds"] == cold_limit)
        printed.append(
            f"- **{split.capitalize()} battery and cold.** A ≤{a_cutoff}% flags {low['at_or_below']}/{result['battery_low_case_n']} selected case-opening readings. "
            f"A strict comparator flags {low['below']}. The cold rule covers {cold['cold_cases_eligible']}/{cold['cold_cases']} labelled cold cases and "
            f"{cold['ordinary_opportunities_eligible']}/{result['first_overdue_opportunities']} first-overdue probes. "
            f"{cold['ordinary_recovered_within_grace']} of the covered probes next report within grace. These outcome counts are conditional on the cohort."
        )
    for split in ("development", "validation"):
        outcome = report["outage"]["selected"][split]
        detections = outcome["labelled_case_results"]
        snapshots = sum(row["detected_snapshots"] for row in detections)
        fragments = sum(row["fragments"] for row in detections)
        printed.append(
            f"- **{split.capitalize()} outages.** The chosen grid point detects {outcome['labelled_cases_detected']}/"
            f"{len(detections)} labelled cases for {snapshots} labelled minute snapshots in {fragments} fragment(s). Background probes include "
            f"{outcome['background_incident_snapshots']}/{outcome['background_samples']} alarming snapshots "
            f"across {outcome['background_incident_episodes']} grouped episodes. The report includes grid sensitivity and fragmentation."
        )
    contrast = report["outage"]["comparison_sensitivity"]
    holdout_detections = {
        row["thresholds"]["minimum_healthy_comparison_devices"]: sum(
            case["detected_snapshots"] for case in row["validation"]["labelled_case_results"]
        )
        for row in contrast if row["thresholds"]["minimum_healthy_comparison_share"] == 0.50
    }
    contrast_text = ", ".join(f"{peers} peers → {minutes} minutes" for peers, minutes in sorted(holdout_detections.items()))
    printed.extend([
        "",
        f"At a 50% comparison share, the healthy-peer count sweep changes held-out detection duration ({contrast_text}). "
        "The development-selected values remain fixed. Runtime continuation uses evidence from the opening and follows member recovery separately. [Runtime policy](decisions.md#p06-carrier-incidents)",
        "",
        "## Chosen thresholds",
        "",
        "| Parameter | Value | Unit | Basis |",
        "| --- | --- | --- | --- |",
    ])
    for group in ("calibrated_parameters", "operational_assumptions", "defensive_limits"):
        for key, item in rules[group].items():
            printed.append(f"| `{key}` | {json.dumps(item['value'])} | {item['unit']} | {item['provenance']} |")
    printed.extend([
        "",
        "Track approval of seasonal downtime, high-priority deadlines and the remaining Form 2 allowance separately. No threshold here proves the hidden scenarios pass. Camera escalation, cold grace, physical battery recovery, and carrier grouping need adversarial tests during implementation.",
        "",
        "## Reproduce from the checkout root",
        "",
        "```bash",
        "python3.12 scripts/audit_data.py --data data",
        "python3.12 scripts/calibrate.py --data data",
        "```",
        "",
    ])
    return "\n".join(printed)


def compact_evidence(report, rules):
    measured = rules["calibrated_parameters"]
    provisional = rules["operational_assumptions"]
    cadence_sweeps = {
        "tracker_driving_overdue": "tracker_driving_lateness_sweep",
        "camera_recording_overdue": "camera_recording_lateness_sweep",
    }
    evidence = {}
    for split in ("development", "validation"):
        timing = report["timing"][split]
        daily = report["daily"]["families"]
        evaluation = report["daily"]["case_and_opportunity_evaluation"][split]
        held_out_battery_low = evaluation["battery_low_case_threshold_sweep"][str(provisional["a_low_battery"]["value"])]
        cutoff = str(provisional["camera_reboot_response_grace"]["value"])
        evidence[split] = {
            "cadence_deadline_crossings": {
                name: timing[sweep][str(measured[name]["value"])] for name, sweep in cadence_sweeps.items()
            },
            "daily_deadline_crossings": {
                family: daily[family]["split"][split]["healthy_lateness_sweep"][str(measured[name]["value"])]
                for family, name in (("A", "a_daily_overdue"), ("BX", "bx_daily_overdue"))
            },
            "awake_reboot_outcomes": timing["camera_reboot"]["response_sweep"][cutoff],
            "battery_low_case_readings": {"cases": evaluation["battery_low_case_n"], **held_out_battery_low},
            "carrier_outage": report["outage"]["selected"][split],
        }
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Directory with reference CSVs and telemetry/")
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    args = parser.parse_args()
    if args.reports_dir.resolve() == args.config_dir.resolve():
        parser.error("--reports-dir and --config-dir must differ")
    with open_dataset(args.data) as (conn, refs, audit):
        report = {
            "split": SPLIT,
            "sources_sha256": audit["sources_sha256"],
            "timing": measure_timing(conn, refs),
            "daily": measure_daily(conn, refs),
            "outage": measure_outages(conn, refs),
            "receipt_lag": classify_lag(conn),
        }
    rules = build_rules(report)
    report_bytes = canonical_json(report)
    calibration = {
        "schema_version": 1,
        "split": SPLIT,
        "report_path": "reports/calibration.json",
        "report_sha256": hashlib.sha256(report_bytes.encode("utf-8")).hexdigest(),
        "selection": "Development cohorts select fitted settings. Validation is reported separately. Assumptions carry provenance and planned acceptance checks in rules.json.",
        "evidence": compact_evidence(report, rules),
    }
    outputs = {
        args.reports_dir / "calibration.json": report_bytes,
        args.config_dir / "rules.json": canonical_json(rules),
        args.config_dir / "calibration.json": canonical_json(calibration),
        args.docs_dir / "calibration.md": render_docs(report, rules),
    }
    for path, body in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        print(path)


if __name__ == "__main__":
    main()
