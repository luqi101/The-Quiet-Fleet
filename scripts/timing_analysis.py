"""Offline tracker and camera cohorts from deduplicated SQLite observations."""

import json
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil, inf, nextafter
from sqlite3 import Connection


HOLDOUT = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp())
SLICES = ("development", "validation")
TRACKER_DEADLINES = (240, 360, 480, 600)
CAMERA_DEADLINES = (600, 720, 900)
WAKE_DEADLINES = (30, 60, 120, 180, 300)
REBOOT_DEADLINES = (120, 300, 600, 900, 1800)
REBOOT_COUNTS = (
    "unique_commands",
    "without_confirmed_awake_context",
    "awake_without_visible_storage_error",
    "awake_with_visible_storage_error",
    "later_recording_observed",
)


@dataclass(frozen=True, slots=True)
class Point:
    observed: float
    received: float


@dataclass(frozen=True, slots=True)
class Mode:
    driving: bool | None
    start: Point


@dataclass(frozen=True, slots=True)
class Trial:
    observation_delay: float | None
    availability_delay: float | None
    followed_seconds: float


def _slice(received):
    return "development" if received < HOLDOUT else "validation"


def _summary(values):
    ordered = sorted(values)
    count = len(ordered)
    return {
        "n": count,
        "p50": ordered[ceil(count * 0.50) - 1] if count else None,
        "p95": ordered[ceil(count * 0.95) - 1] if count else None,
        "p99": ordered[ceil(count * 0.99) - 1] if count else None,
        "max": ordered[-1] if count else None,
    }


def _gap_sweep(values, deadlines):
    n = len(values)
    result = {}
    for deadline in deadlines:
        over = sum(gap > deadline for gap in values)
        result[str(deadline)] = {
            "n": n,
            "over": over,
            "over_fraction": round(over / n, 6) if n else None,
        }
    return result


def _trial_sweep(trials, deadlines):
    result = {}
    for deadline in deadlines:
        counts = {"within": 0, "absent": 0, "right_censored": 0}
        for trial in trials:
            if trial.availability_delay is not None and trial.availability_delay <= deadline:
                counts["within"] += 1
            elif trial.followed_seconds > deadline:
                counts["absent"] += 1
            else:
                counts["right_censored"] += 1
        result[str(deadline)] = counts
    return result


def _rows(conn, serial, kinds, cutoff):
    placeholders = ",".join("?" for _ in kinds)
    return conn.execute(
        f"""SELECT kind, observed, received, payload
            FROM events
            WHERE serial = ? AND kind IN ({placeholders}) AND observed <= received AND received < ?
            ORDER BY observed, received, event_id""",
        (serial, *kinds, cutoff),
    )


def _gap(previous, current, mode_start, part):
    if previous is None or current.observed <= previous.observed:
        return None
    if _slice(max(previous.received, current.received, mode_start.received)) != part:
        return None
    return current.observed - previous.observed


def _tracker(conn, device, assets, part, cutoff, samples):
    modes = []
    previous_position = previous_heartbeat = None
    driving = None
    kinds = ("ignition_on", "ignition_off", "position", "heartbeat", "power_disconnect")
    roster_vin = assets.get(device["asset_id"], {}).get("vin")
    contradicted = False
    for kind, observed, received, raw_payload in _rows(conn, device["serial"], kinds, cutoff):
        point = Point(observed, received)
        if kind in ("ignition_on", "ignition_off", "power_disconnect"):
            driving = None if kind == "power_disconnect" else kind == "ignition_on"
            modes.append(Mode(driving, point))
            previous_position = previous_heartbeat = None
        if kind in ("ignition_on", "heartbeat") and roster_vin:
            reported_vin = json.loads(raw_payload).get("vin")
            contradicted |= bool(reported_vin and reported_vin != roster_vin)
        if kind == "position" and driving is True:
            if json.loads(raw_payload).get("ignition") is True:
                gap = _gap(previous_position, point, modes[-1].start, part)
                if gap is not None:
                    samples["tracker_driving_gap_seconds"].append(gap)
                previous_position = point
            else:
                previous_position = None
        elif kind == "heartbeat" and driving is False:
            gap = _gap(previous_heartbeat, point, modes[-1].start, part)
            if gap is not None:
                samples["tracker_parked_heartbeat_gap_seconds"].append(gap)
            previous_heartbeat = point
    return modes, contradicted


def _trial(start, outcomes, boundary, slice_end, *, allow_same_observation=True):
    # A physical mode exit or a subsequent attempt ends exposure. The next
    # history slice cannot supply verification to the cohort being fitted.
    limit = min(boundary, slice_end)
    available = [
        point for point in outcomes
        if (point.observed > start.observed or (allow_same_observation and point.observed == start.observed))
        and point.received < limit
    ]
    if not available:
        return Trial(None, None, max(0, limit - start.observed))
    return Trial(
        min(point.observed for point in available) - start.observed,
        max(start.received, min(point.received for point in available)) - start.observed,
        limit - start.observed,
    )


def _record_trial(samples, name, trial):
    if trial.observation_delay is not None:
        samples[f"{name}_delay_seconds"].append(trial.observation_delay)
        samples[f"{name}_available_delay_seconds"].append(trial.availability_delay)


def _camera_episodes(camera_rows, modes, part, cutoff, samples, firmware_samples, wake_trials):
    starts = [mode.start.observed for mode in modes]
    groups = defaultdict(lambda: defaultdict(list))
    previous_recording = None
    previous_group = -1
    plan_eligible = True
    for status, point in camera_rows:
        if status in ("plan_active", "plan_paused", "plan_ended"):
            plan_eligible = status == "plan_active"
            previous_recording = None
            continue
        group = bisect_right(starts, point.observed) - 1
        if group < 0:
            continue
        if group != previous_group or status != "recording":
            previous_recording = None
            previous_group = group
        mode = modes[group]
        if mode.driving is None:
            continue
        groups[group][status].append(point)
        if mode.driving and status == "recording" and plan_eligible:
            gap = _gap(previous_recording, point, mode.start, part)
            if gap is not None:
                samples["camera_recording_gap_seconds"].append(gap)
                firmware_samples.append(gap)
            previous_recording = point

    for index, mode in enumerate(modes):
        if mode.driving is None or _slice(mode.start.received) != part:
            continue
        boundary = starts[index + 1] if index + 1 < len(starts) else cutoff
        outcomes = groups[index]
        if mode.driving:
            boot = _trial(mode.start, outcomes["booting"], boundary, cutoff)
            recording = _trial(mode.start, outcomes["recording"], boundary, cutoff)
            _record_trial(samples, "camera_boot", boot)
            _record_trial(samples, "camera_first_recording", recording)
            wake_trials.append(recording)
        else:
            sleep = _trial(mode.start, outcomes["sleeping"], boundary, cutoff)
            _record_trial(samples, "camera_sleep", sleep)
    return starts


def _reboot_trials(camera_rows, commands, modes, starts, part, cutoff, counts, trials):
    recordings = [point for status, point in camera_rows if status == "recording"]
    fault_facts = [
        (status, point) for status, point in camera_rows if status in ("storage_error", "recording")
    ]
    for index, command in enumerate(commands):
        if _slice(command.received) != part:
            continue
        counts["unique_commands"] += 1
        group = bisect_right(starts, command.observed) - 1
        if group < 0 or not modes[group].driving or modes[group].start.received > command.received:
            counts["without_confirmed_awake_context"] += 1
            continue
        prior_state = "unknown"
        for status, point in fault_facts:
            if point.observed >= command.observed:
                break
            if point.received <= command.received:
                prior_state = status
        if prior_state != "storage_error":
            counts["awake_without_visible_storage_error"] += 1
            continue
        counts["awake_with_visible_storage_error"] += 1
        boundary = starts[group + 1] if group + 1 < len(starts) else cutoff
        if index + 1 < len(commands):
            boundary = min(boundary, commands[index + 1].observed)
        trial = _trial(command, recordings, boundary, cutoff, allow_same_observation=False)
        trials.append(trial)
        counts["later_recording_observed"] += int(trial.observation_delay is not None)


def _camera_rows(conn, serial, cutoff):
    camera_rows = []
    commands = []
    kinds = ("camera_status", "command", "plan_change")
    for kind, observed, received, raw_payload in _rows(conn, serial, kinds, cutoff):
        payload = json.loads(raw_payload)
        point = Point(observed, received)
        if kind == "command":
            if payload.get("command") == "reboot":
                commands.append(point)
        elif kind == "plan_change":
            if payload.get("status") in ("active", "paused", "ended"):
                camera_rows.append((f'plan_{payload["status"]}', point))
        elif payload.get("status") in ("booting", "recording", "sleeping", "storage_error"):
            camera_rows.append((payload["status"], point))
    return camera_rows, commands


def _measure_slice(conn, refs, part, cutoff):
    samples = defaultdict(list)
    wake_trials = []
    reboot_trials = []
    reboot_counts = defaultdict(Counter)
    camera_firmware = defaultdict(list)
    assets = {asset["asset_id"]: asset for asset in refs["assets"]}
    trackers_per_asset = Counter(
        device["asset_id"] for device in refs["devices"] if device["family"] == "T" and device["asset_id"]
    )
    camera_trackers = {}
    camera_coverage = Counter()
    for device in refs["devices"]:
        if device["family"] != "T":
            continue
        modes, contradicted = _tracker(conn, device, assets, part, cutoff, samples)
        asset_id = device["asset_id"]
        if trackers_per_asset[asset_id] == 1 and not contradicted and any(mode.driving is not None for mode in modes):
            camera_trackers[asset_id] = modes

    for device in refs["devices"]:
        if device["family"] != "C":
            continue
        rows, commands = _camera_rows(conn, device["serial"], cutoff)
        modes = camera_trackers.get(device["asset_id"], [])
        coverage = "with_unambiguous_tracker_modes" if modes else "excluded_without_unambiguous_tracker_modes"
        camera_coverage[coverage] += 1
        firmware_counts = reboot_counts[device["firmware"]]
        firmware_samples = camera_firmware[device["firmware"]]
        starts = _camera_episodes(rows, modes, part, cutoff, samples, firmware_samples, wake_trials)
        _reboot_trials(rows, commands, modes, starts, part, cutoff, firmware_counts, reboot_trials)

    summary_names = [
        "tracker_driving_gap_seconds", "tracker_parked_heartbeat_gap_seconds", "camera_recording_gap_seconds"
    ]
    for name in ("camera_sleep", "camera_boot", "camera_first_recording"):
        summary_names.extend((f"{name}_delay_seconds", f"{name}_available_delay_seconds"))
    counts = Counter()
    for firmware_counts in reboot_counts.values():
        counts.update(firmware_counts)
    return {
        **{name: _summary(samples[name]) for name in summary_names},
        "camera_coverage": dict(sorted(camera_coverage.items())),
        "tracker_driving_lateness_sweep": _gap_sweep(samples["tracker_driving_gap_seconds"], TRACKER_DEADLINES),
        "camera_recording_lateness_sweep": _gap_sweep(samples["camera_recording_gap_seconds"], CAMERA_DEADLINES),
        "camera_recording_gap_by_firmware": {
            firmware: _summary(values) for firmware, values in sorted(camera_firmware.items())
        },
        "camera_wake_sweep": _trial_sweep(wake_trials, WAKE_DEADLINES),
        "camera_reboot": {
            "counts": {key: counts[key] for key in REBOOT_COUNTS},
            "by_firmware": {
                firmware: {key: values[key] for key in REBOOT_COUNTS}
                for firmware, values in sorted(reboot_counts.items())
            },
            "observation_delay_seconds": _summary(
                [trial.observation_delay for trial in reboot_trials if trial.observation_delay is not None]
            ),
            "availability_delay_seconds": _summary(
                [trial.availability_delay for trial in reboot_trials if trial.availability_delay is not None]
            ),
            "response_sweep": _trial_sweep(reboot_trials, REBOOT_DEADLINES),
        },
    }


def measure_timing(conn: Connection, refs: dict[str, list[dict]]) -> dict:
    """Measure seconds and threshold sensitivity without retaining raw event rows."""
    latest_receipt = conn.execute("SELECT MAX(received) FROM events").fetchone()[0]
    history_end = nextafter(latest_receipt, inf) if latest_receipt is not None else HOLDOUT
    slice_ends = {"development": min(HOLDOUT, history_end), "validation": history_end}
    return {
        "holdout_at": "2026-10-25T00:00:00Z",
        "unit": "seconds",
        "method": {
            "position_and_heartbeat": "Positive gaps within one explicit ignition mode, reset on mode changes or disconnect. Only true-ignition positions enter driving cadence. Gaps are assigned by the latest supporting first receipt.",
            "camera_cohort": "Conservative same-asset pairing uses one rostered tracker with ignition events and no VIN contradiction visible before the slice end. Roster collisions are excluded from camera measurements. Recording gaps stay inside a confirmed drive and reset on non-recording status or plan transitions.",
            "transitions": "Use the first post-ignition recorded observation or first usable receipt, measured from ignition observation time. A transition cohort is assigned by ignition receipt. Observation and receipt summaries can use different reports after out-of-order delivery.",
            "reboot": "Deduplicated commands enter the response cohort only with awake tracker context and an unresolved storage error already visible when the command was received. A later recording is an outcome and does not prove the reboot caused it. No support case outcomes are used.",
            "sensitivity": "Late cadence gaps use >. Transition and reboot thresholds use the availability delay <= and classify insufficient follow-up as right-censored. Follow-up ends at an ignition mode change, another reboot for reboot trials, or the end of the receipt slice. An absent recording can reflect a real break, an outage, or another cause.",
            "limits": "Estimates apply to observed, deduplicated sample gaps and conservative retrospective pairing. Some forecast deadlines include unclassified real interruptions. Camera wake delays with no observation have no point estimate.",
            "quantiles": "Nearest rank, with the sample size for each measure.",
        },
        **{part: _measure_slice(conn, refs, part, slice_ends[part]) for part in SLICES},
    }
