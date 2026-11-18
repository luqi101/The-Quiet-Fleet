"""Offline daily-report and battery calibration for A and BX devices."""

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DAY = 86_400
HOUR = 3_600
HOLDOUT = int(datetime(2026, 10, 25, tzinfo=UTC).timestamp())
DEPOT_ZONES = {"MSS": ZoneInfo("America/Toronto"), "REG": ZoneInfo("America/Regina")}
DAILY_CANDIDATES = (24, 25, 26, 28, 30)
LOW_CANDIDATES = (5, 8, 10, 12, 15, 20, 25)
RECOVERY_CANDIDATES = (10, 15, 20, 25, 30)
COLD_CANDIDATES = (-8, -10, -12, -15)
COLD_GRACE_CANDIDATES = (48, 50, 52, 54)
HEALTHY_BATTERY = 25


@dataclass(frozen=True)
class Reading:
    observed: float
    received: float
    percent: float
    low_flag: bool = False


def time_slice(received):
    return "development" if received < HOLDOUT else "validation"


def summarize(values):
    """Nearest-rank percentiles, conserving the smallest cohorts."""
    values = sorted(values)
    if not values:
        return dict.fromkeys(("n", "min", "p50", "p95", "p99", "max")) | {"n": 0}
    return {
        "n": len(values),
        "min": values[0],
        **{f"p{pct}": values[math.ceil(len(values) * pct / 100) - 1] for pct in (50, 95, 99)},
        "max": values[-1],
    }


def latest_available(series, at):
    return next((row for row in reversed(series) if row.observed <= at and row.received <= at), None)


def observation_pairs(series):
    return (
        (previous, current)
        for previous, current in zip(series, series[1:])
        if previous.observed < current.observed
    )


def range_sweep(values, hours=DAILY_CANDIDATES):
    return {str(hours_count * HOUR): {"n": len(values), "over": sum(x > hours_count * HOUR for x in values)}
            for hours_count in hours}


def select_daily(values):
    """The first tested deadline at least one hour above development p99, with zero crossings."""
    distribution = summarize(values)
    if not values:
        return 26 * HOUR, "provisional_no_development_intervals"
    for hours in DAILY_CANDIDATES:
        seconds = hours * HOUR
        if seconds >= distribution["p99"] + HOUR and seconds >= distribution["max"]:
            return seconds, "development_p99_plus_one_hour_with_zero_crossings"
    return DAILY_CANDIDATES[-1] * HOUR, "provisional_no_candidate_met_target"


def daily_readings(conn):
    series = defaultdict(list)
    for event in conn.execute("""
        SELECT serial, observed, received, payload
        FROM events
        WHERE kind IN ('check_in', 'bx_raw') AND observed <= received
        ORDER BY serial, observed, received, event_id
    """):
        payload = json.loads(event["payload"])
        percent = payload.get("battery_pct")
        if type(percent) in (int, float) and 0 <= percent <= 100:
            series[event["serial"]].append(Reading(
                event["observed"], event["received"], percent, payload.get("low_battery", False),
            ))
    return series


def credible_recoveries(series, low, recovery):
    """Return later-observed recoveries and count still-open episodes at the history boundary."""
    opened = None
    crossings = []
    newest_observation = float("-inf")
    for point in sorted(series, key=lambda r: (r.received, r.observed)):
        if point.observed <= newest_observation:
            continue
        newest_observation = point.observed
        if opened and recovery(point):
            crossings.append((opened, point))
            opened = None
        elif opened is None and low(point):
            opened = point
    return crossings, int(opened is not None)


def stale_opportunities(series, deadline, history_end):
    """Measure one first overdue checkpoint for each newly credible observation."""
    fresh = []
    for point in sorted(series, key=lambda r: (r.received, r.observed)):
        if not fresh or point.observed > fresh[-1].observed:
            fresh.append(point)
    for index, anchor in enumerate(fresh):
        evaluation = anchor.observed + deadline
        if not anchor.received <= evaluation <= history_end:
            continue
        subsequent = fresh[index + 1] if index + 1 < len(fresh) else None
        if subsequent is None or evaluation < subsequent.received:
            yield anchor, evaluation, subsequent


def local_day(timestamp, depot):
    zone = DEPOT_ZONES.get(depot)
    return datetime.fromtimestamp(timestamp, tz=zone).date().isoformat() if zone else None


def case_features(cases, series, weather, deadline):
    features = []
    for case in cases:
        if case["root_cause"] not in {"cold_weather", "battery_low"}:
            continue
        opened = datetime.fromisoformat(case["opened_at"]).timestamp()
        # Outcome fields never determine the available reading or the checkpoint.
        earlier = latest_available(series.get(case["serial"], ()), opened)
        if earlier is None:
            features.append((case, opened, None, None, None, False))
            continue
        later = min((row for row in series[case["serial"]]
                     if row.received > opened and row.observed > earlier.observed),
                    key=lambda row: row.received, default=None)
        recovery = later.received - earlier.observed if later else None
        known_temperature = weather.get((case["depot"], local_day(opened, case["depot"])))
        overdue = opened >= earlier.observed + deadline
        features.append((case, opened, earlier, known_temperature, recovery, overdue))
    return features


def cold_sweep(features, opportunities, boundary):
    result = []
    for temp in COLD_CANDIDATES:
        for grace in COLD_GRACE_CANDIDATES:
            grace_seconds = grace * HOUR
            counts = dict.fromkeys((
                "cold_cases", "cold_cases_eligible", "cold_cases_recovered_within_grace",
                "cold_cases_recovery_right_censored", "labeled_low_cases",
                "labeled_low_cases_eligible_for_suppression", "ordinary_opportunities_eligible",
                "ordinary_recovered_within_grace", "ordinary_recovery_right_censored",
            ), 0)
            for case, opened, prior, low, recovery, overdue in features:
                is_cold = case["root_cause"] == "cold_weather"
                counts["cold_cases" if is_cold else "labeled_low_cases"] += 1
                if not (prior and overdue and prior.percent >= HEALTHY_BATTERY and low is not None
                        and low <= temp and opened <= prior.observed + grace_seconds):
                    continue
                if is_cold:
                    counts["cold_cases_eligible"] += 1
                    if recovery is not None and recovery <= grace_seconds and prior.observed + recovery < boundary:
                        counts["cold_cases_recovered_within_grace"] += 1
                    elif prior.observed + grace_seconds >= boundary:
                        counts["cold_cases_recovery_right_censored"] += 1
                else:
                    counts["labeled_low_cases_eligible_for_suppression"] += 1
            for prior, at, subsequent, low in opportunities:
                if low is None or low > temp or prior.percent < HEALTHY_BATTERY:
                    continue
                counts["ordinary_opportunities_eligible"] += 1
                cutoff = prior.observed + grace_seconds
                if subsequent and subsequent.received <= cutoff and subsequent.received < boundary:
                    counts["ordinary_recovered_within_grace"] += 1
                elif cutoff >= boundary:
                    counts["ordinary_recovery_right_censored"] += 1
            result.append({"temp_c": temp, "grace_seconds": grace_seconds, **counts})
    return result


def measure_daily(conn, refs):
    devices = {row["serial"]: row for row in refs["devices"]}
    depots = {row["asset_id"]: row["depot"] for row in refs["assets"]}
    weather = {(row["depot"], row["date"]): float(row["low_c"])
               for row in refs["weather"] if row.get("low_c")}
    history_end = conn.execute("SELECT MAX(received) FROM events").fetchone()[0] or 0
    series = daily_readings(conn)
    family_series = {
        family: {serial: points for serial, points in series.items() if devices.get(serial, {}).get("family") == family}
        for family in ("A", "BX")
    }
    results = {}
    for family, by_serial in family_series.items():
        gaps = defaultdict(list)
        healthy = defaultdict(list)
        differences = defaultdict(list)
        batteries = defaultdict(list)
        for points in by_serial.values():
            for point in points:
                batteries[time_slice(point.received)].append(point)
            for previous, current in observation_pairs(points):
                split = time_slice(max(previous.received, current.received))
                gap = current.observed - previous.observed
                gaps[split].append(gap)
                if (min(previous.percent, current.percent) >= HEALTHY_BATTERY
                        and not (previous.low_flag or current.low_flag) and gap < 30 * HOUR):
                    healthy[split].append(gap)
                if gap < 30 * HOUR:
                    differences[split].append(round(current.percent - previous.percent, 4))
        deadline, reason = select_daily(healthy["development"])
        split_metrics = {}
        for split in ("development", "validation"):
            split_metrics[split] = {
                "all_gap_seconds": summarize(gaps[split]),
                "healthy_gap_seconds": summarize(healthy[split]),
                "healthy_jitter_vs_24h_seconds": summarize(x - DAY for x in healthy[split]),
                "healthy_lateness_sweep": range_sweep(healthy[split]),
                "battery_delta_pct_points_adjacent_under_30h": summarize(differences[split]),
                "battery_percent": summarize(p.percent for p in batteries[split]),
                "low_flag_battery_percent": summarize(p.percent for p in batteries[split] if p.low_flag),
                "percentage_sweep": {
                    str(threshold): {
                        "below": sum(p.percent < threshold for p in batteries[split]),
                        "at_or_below": sum(p.percent <= threshold for p in batteries[split]),
                        "at_or_below_without_flag": sum(p.percent <= threshold and not p.low_flag for p in batteries[split]),
                    } for threshold in LOW_CANDIDATES
                },
            }
        recovery_sweep = {}
        for threshold in RECOVERY_CANDIDATES:
            observed_outcomes = defaultdict(list)
            open_at_end = 0
            for points in by_serial.values():
                transitions, censored = credible_recoveries(
                    points,
                    lambda p: p.percent <= 10 if family == "A" else p.low_flag,
                    lambda p: p.percent >= threshold and not p.low_flag,
                )
                open_at_end += censored
                for event, recovery in transitions:
                    observed_outcomes[time_slice(recovery.received)].append(recovery.received - event.received)
            recovery_sweep[str(threshold)] = {
                "observed_delay_seconds_by_recovery_receipt": {
                    split: summarize(observed_outcomes[split]) for split in ("development", "validation")
                },
                "open_at_history_end": open_at_end,
            }
        results[family] = {
            "devices_with_data": len(by_serial),
            "healthy_gap_seconds_all": summarize(healthy["development"] + healthy["validation"]),
            "all_gap_seconds": summarize(gaps["development"] + gaps["validation"]),
            "selected_deadline_seconds": deadline,
            "selection": reason,
            "split": split_metrics,
            "recovery_sweep": recovery_sweep,
        }

    deadline_a = results["A"]["selected_deadline_seconds"]
    features = case_features(refs["support_cases"], family_series["A"], weather, deadline_a)
    opportunities = defaultdict(list)
    for serial, points in family_series["A"].items():
        depot = depots.get(devices[serial]["asset_id"])
        for anchor, at, later in stale_opportunities(points, deadline_a, history_end):
            opportunities[time_slice(at)].append((anchor, at, later, weather.get((depot, local_day(at, depot)))))
    evaluation = {}
    for split in ("development", "validation"):
        label_features = [feature for feature in features if time_slice(feature[1]) == split]
        low_labels = [f[2] for f in label_features if f[0]["root_cause"] == "battery_low"]
        cold_labels = [f for f in label_features if f[0]["root_cause"] == "cold_weather"]
        boundary = HOLDOUT if split == "development" else history_end + 1
        temperatures_in_notes = [int(match[1]) for f in cold_labels
                                 if (match := re.search(r"Overnight low (-?\d+) C", f[0]["notes"]))]
        evaluation[split] = {
            "battery_low_case_n": len(low_labels),
            "battery_low_case_missing_prior": sum(p is None for p in low_labels),
            "battery_low_case_latest_eligible_percent": summarize(p.percent for p in low_labels if p),
            "battery_low_case_threshold_sweep": {
                str(t): {
                    "below": sum(bool(p and p.percent < t) for p in low_labels),
                    "at_or_below": sum(bool(p and p.percent <= t) for p in low_labels),
                } for t in LOW_CANDIDATES
            },
            "cold_case_n": len(cold_labels),
            "cold_case_temperature_from_notes_c": summarize(temperatures_in_notes),
            "cold_case_local_weather_c": summarize(f[3] for f in cold_labels if f[3] is not None),
            "cold_case_recovery_seconds_since_prior_observation": summarize(
                f[4] for f in cold_labels if f[4] is not None and f[2].observed + f[4] < boundary
            ),
            "first_overdue_opportunities": len(opportunities[split]),
            "cold_sweep": cold_sweep(label_features, opportunities[split], boundary),
        }
    return {
        "method": {
            "healthy_cadence": "Positive adjacent intervals under 30h with both batteries at least 25% and neither BX low flag. Assign by the latest required receipt.",
            "deadline_selection": "On development only, first tested deadline at least one hour above empirical p99 with zero healthy crossings.",
            "case_evaluation": "Use latest observation received by open. Depot weather at local open date is a daily proxy. Later credible receipt is an outcome, censored at the split end.",
            "cold_controls": "First overdue checkpoint per newly credible A observation. Battery and deadline-date depot weather are available predictors. Next receipt is measured only as a later outcome. Controls may overlap selected cases.",
            "recovery": "Later-observed receipts only, by receipt order. Group outcomes by recovery receipt and report episodes still open at history end.",
        },
        "families": results,
        "case_and_opportunity_evaluation": evaluation,
    }
