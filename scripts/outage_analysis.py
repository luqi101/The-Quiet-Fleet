"""Replay driving-tracker cohorts at historical snapshots to calibrate outage rules."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import product
import json
import re
import sqlite3


SNAPSHOT_SECONDS = 60
LABEL_GUARD_SECONDS = 900
DRIVING_DUE_SECONDS = (240, 360, 480, 600)
MINIMUM_AFFECTED_COUNTS = (5, 8, 12)
MINIMUM_AFFECTED_SHARES = (0.35, 0.50, 0.65)
MAXIMUM_ONSET_SPREADS = (240, 600, 900)
MINIMUM_HEALTHY_PEERS = 3
MINIMUM_HEALTHY_SHARE = 0.50
COMPARISON_COUNTS = (2, 3, 5)
COMPARISON_SHARES = (0.25, 0.50, 0.75)
TRACKER_KINDS = (
    "position", "ignition_on", "ignition_off", "heartbeat",
    "power_disconnect", "power_restore", "plan_change",
)

Route = tuple[str, str]


def timestamp(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp())


def utc_text(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


HISTORY_START = timestamp("2026-10-04T00:00:00Z")
VALIDATION_START = timestamp("2026-10-25T00:00:00Z")
HISTORY_END = timestamp("2026-11-01T00:00:00Z")


@dataclass(slots=True)
class Tracker:
    carrier: str
    depot: str | None
    ignition_rank: tuple[float, int] = (0, 0)
    driving: bool = False
    last_position: float = 0
    power_at: float = 0
    power_lost: bool = False
    plan_at: float = 0
    plan_inactive: bool = False
    vin_at: float = 0
    onsets: dict[int, float] = field(default_factory=dict)

    def observe(self, event: sqlite3.Row, depot_by_vin: dict[str, str]) -> None:
        kind, observed = event["kind"], event["observed"]
        payload = json.loads(event["payload"])
        if kind in {"position", "ignition_on", "ignition_off"}:
            ignition = payload.get("ignition") if kind == "position" else kind == "ignition_on"
            if isinstance(ignition, bool):
                # For equal clocks use explicit transitions before implicit state,
                # and use the off state when the transition kinds conflict.
                rank = (observed, (kind != "position") * 2 + (not ignition))
                if rank > self.ignition_rank:
                    if ignition != self.driving:
                        self.onsets.clear()
                    self.ignition_rank, self.driving = rank, ignition
                if kind == "position" and ignition:
                    self.last_position = max(self.last_position, observed)
        if kind in {"power_disconnect", "power_restore"} and observed >= self.power_at:
            self.power_at, self.power_lost = observed, kind == "power_disconnect"
            if self.power_lost:
                self.onsets.clear()
        if kind == "plan_change" and observed >= self.plan_at:
            plan_status = payload.get("status")
            if plan_status in {"active", "paused", "ended"}:
                self.plan_at, self.plan_inactive = observed, plan_status != "active"
                if self.plan_inactive:
                    self.onsets.clear()
        if kind in {"heartbeat", "ignition_on"} and observed > self.vin_at:
            depot = depot_by_vin.get(payload.get("vin"))
            if depot is not None:
                if depot != self.depot:
                    self.onsets.clear()
                self.vin_at, self.depot = observed, depot


@dataclass(slots=True)
class Cohort:
    eligible: int = 0
    onsets: list[float] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Label:
    case_id: str
    route: Route
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Candidate:
    due: int
    spread: int
    count: int
    share: float
    healthy_count: int = MINIMUM_HEALTHY_PEERS
    healthy_share: float = MINIMUM_HEALTHY_SHARE

    def thresholds(self) -> dict:
        return {
            "tracker_due_seconds": self.due,
            "maximum_onset_spread_seconds": self.spread,
            "minimum_affected_devices": self.count,
            "minimum_affected_share": self.share,
            "minimum_healthy_comparison_devices": self.healthy_count,
            "minimum_healthy_comparison_share": self.healthy_share,
        }


@dataclass(slots=True)
class CaseDetection:
    first: int | None = None
    latest: int | None = None
    fragments: int = 0
    snapshots: int = 0
    peak_affected: int = 0
    peak_share: float = 0.0
    peak_eligible: int = 0
    minimum_healthy_peers: int | None = None

    def observe(self, at: int, affected: int, eligible: int, healthy: int) -> None:
        if self.first is None:
            self.first = at
        if self.latest != at - SNAPSHOT_SECONDS:
            self.fragments += 1
        self.latest = at
        self.snapshots += 1
        self.peak_affected = max(self.peak_affected, affected)
        self.peak_share = max(self.peak_share, affected / eligible)
        self.peak_eligible = max(self.peak_eligible, eligible)
        self.minimum_healthy_peers = healthy if self.minimum_healthy_peers is None else min(self.minimum_healthy_peers, healthy)


@dataclass(slots=True)
class SplitMetrics:
    background_snapshots: int = 0
    background_episodes: int = 0
    background_latest: dict[Route, int] = field(default_factory=dict)
    cases: dict[str, CaseDetection] = field(default_factory=dict)

    def background(self, at: int, route: Route) -> None:
        self.background_snapshots += 1
        if self.background_latest.get(route) != at - SNAPSHOT_SECONDS:
            self.background_episodes += 1
        self.background_latest[route] = at

    def report(self, labels: list[Label], samples: int, background_samples: int) -> dict:
        results = []
        for label in labels:
            detection = self.cases.get(label.case_id, CaseDetection())
            results.append({
                "case_id": label.case_id,
                "first_detection_at": utc_text(detection.first),
                "detection_delay_seconds": detection.first - label.start if detection.first is not None else None,
                "detected_snapshots": detection.snapshots,
                "fragments": detection.fragments,
                "peak_affected": detection.peak_affected,
                "peak_affected_share": round(detection.peak_share, 4),
                "peak_eligible": detection.peak_eligible,
                "minimum_healthy_comparison_devices": detection.minimum_healthy_peers,
            })
        return {
            "samples": samples,
            "background_samples": background_samples,
            "background_incident_snapshots": self.background_snapshots,
            "background_incident_episodes": self.background_episodes,
            "labelled_cases_detected": sum(row["first_detection_at"] is not None for row in results),
            "labelled_case_results": results,
        }


def evaluation_labels(refs: dict[str, list[dict[str, str]]], carriers: set[str]) -> list[Label]:
    labels = []
    for row in refs["support_cases"]:
        if row["root_cause"] != "carrier_outage":
            continue
        matching = [
            carrier for carrier in carriers
            if re.search(rf"\b{re.escape(carrier)}\b", row["notes"], re.IGNORECASE)
        ]
        start, end = timestamp(row["opened_at"]), timestamp(row["closed_at"])
        if len(matching) == 1 and start <= end:
            labels.append(Label(row["case_id"], (row["depot"], matching[0]), start, end))
    return sorted(labels, key=lambda label: (label.start, label.case_id))


def sample_cohorts(
    trackers: dict[str, Tracker], at: int, due_values: tuple[int, ...] = DRIVING_DUE_SECONDS,
) -> dict[Route, dict[int, Cohort]]:
    by_route: dict[Route, dict[int, Cohort]] = {}
    for tracker in trackers.values():
        if not tracker.depot or not tracker.carrier or not tracker.driving or tracker.power_lost or tracker.plan_inactive:
            tracker.onsets.clear()
            continue
        route = (tracker.depot, tracker.carrier)
        if route not in by_route:
            by_route[route] = {due: Cohort() for due in due_values}
        anchor = max(tracker.ignition_rank[0], tracker.last_position)
        for due, cohort in by_route[route].items():
            cohort.eligible += 1
            if at > anchor + due:
                cohort.onsets.append(tracker.onsets.setdefault(due, anchor + due))
            else:
                tracker.onsets.pop(due, None)
    return by_route


def onset_windows(onsets: list[float], spread: int) -> list[tuple[int, float, float]]:
    left = 0
    windows = []
    for right, latest in enumerate(onsets):
        while latest - onsets[left] > spread:
            left += 1
        count = right - left + 1
        if count >= MINIMUM_AFFECTED_COUNTS[0]:
            windows.append((count, onsets[left], latest))
    return windows


def select_candidate(rows: list[dict]) -> dict:
    def rank(row: dict) -> tuple:
        dev = row["development"]
        limits = row["thresholds"]
        return (
            -dev["labelled_cases_detected"],
            dev["background_incident_episodes"],
            dev["background_incident_snapshots"],
            sum(case["fragments"] for case in dev["labelled_case_results"]),
            sum(case["detection_delay_seconds"] or 0 for case in dev["labelled_case_results"]),
            abs(limits["tracker_due_seconds"] - 360),
            abs(limits["maximum_onset_spread_seconds"] - 600),
            abs(limits["minimum_affected_share"] - 0.50),
            abs(limits["minimum_affected_devices"] - 5),
        )

    return min(rows, key=rank)


def replay_candidates(
    conn: sqlite3.Connection, refs: dict[str, list[dict[str, str]]], labels: list[Label], candidates: list[Candidate],
) -> list[dict]:
    assets = {row["asset_id"]: row["depot"] for row in refs["assets"]}
    vin_routes: dict[str, set[str]] = {}
    for row in refs["assets"]:
        if row["vin"]:
            vin_routes.setdefault(row["vin"], set()).add(row["depot"])
    depot_by_vin = {vin: next(iter(depots)) for vin, depots in vin_routes.items() if len(depots) == 1}
    trackers = {
        row["serial"]: Tracker(row["carrier"], assets.get(row["asset_id"]))
        for row in refs["devices"] if row["family"] == "T"
    }
    candidate_groups: dict[int, dict[int, list[Candidate]]] = {}
    for candidate in candidates:
        candidate_groups.setdefault(candidate.due, {}).setdefault(candidate.spread, []).append(candidate)
    due_values = tuple(candidate_groups)
    min_comparison = min(candidate.healthy_count for candidate in candidates)
    metrics = [{candidate: SplitMetrics() for candidate in candidates} for _ in range(2)]
    counters = [[0, 0], [0, 0]]
    ongoing: dict[tuple[Candidate, Route], tuple[float, float]] = {}
    placeholders = ",".join("?" for _ in TRACKER_KINDS)
    events = iter(conn.execute(
        "SELECT serial, kind, observed, received, payload FROM events "
        f"WHERE kind IN ({placeholders}) AND observed <= received AND received < ? "
        "ORDER BY received, observed, event_id", (*TRACKER_KINDS, HISTORY_END),
    ))
    event = next(events, None)
    for at in range(HISTORY_START, HISTORY_END, SNAPSHOT_SECONDS):
        while event is not None and event["received"] <= at:
            tracker = trackers.get(event["serial"])
            if tracker is not None:
                tracker.observe(event, depot_by_vin)
            event = next(events, None)
        split = int(at >= VALIDATION_START)
        guarded = any(label.start - LABEL_GUARD_SECONDS <= at <= label.end + LABEL_GUARD_SECONDS for label in labels)
        counters[split][0] += 1
        counters[split][1] += not guarded
        active_labels = {label.route: label for label in labels if label.start <= at <= label.end}
        by_route = sample_cohorts(trackers, at, due_values)
        current: dict[tuple[Candidate, Route], tuple[float, float]] = {}
        for route, cohorts in by_route.items():
            for due, cohort in cohorts.items():
                if len(cohort.onsets) < MINIMUM_AFFECTED_COUNTS[0]:
                    continue
                comparison = [peers[due] for other, peers in by_route.items() if other[0] == route[0] and other[1] != route[1]]
                healthy = sum(peer.eligible - len(peer.onsets) for peer in comparison)
                if healthy < min_comparison:
                    continue
                comparison_eligible = sum(peer.eligible for peer in comparison)
                cohort.onsets.sort()
                for spread, comparable_candidates in candidate_groups[due].items():
                    windows = onset_windows(cohort.onsets, spread)
                    if not windows:
                        continue
                    for candidate in comparable_candidates:
                        if healthy < candidate.healthy_count or healthy < candidate.healthy_share * comparison_eligible:
                            continue
                        key = (candidate, route)
                        previous = ongoing.get(key)
                        compatible = (
                            (affected, first, last) for affected, first, last in windows
                            if affected >= candidate.count and affected >= candidate.share * cohort.eligible
                            and (last >= at - spread or (previous is not None and first <= previous[1] and last >= previous[0]))
                        )
                        best = max(compatible, key=lambda window: (window[0], window[2]), default=None)
                        if best is None:
                            continue
                        affected, first, last = best
                        current[key] = (first, last)
                        result = metrics[split][candidate]
                        label = active_labels.get(route)
                        if label is not None:
                            result.cases.setdefault(label.case_id, CaseDetection()).observe(at, affected, cohort.eligible, healthy)
                        elif not guarded:
                            result.background(at, route)
        ongoing = current

    return [
        {
            "thresholds": candidate.thresholds(),
            "development": metrics[0][candidate].report([label for label in labels if label.start < VALIDATION_START], *counters[0]),
            "validation": metrics[1][candidate].report([label for label in labels if label.start >= VALIDATION_START], *counters[1]),
        }
        for candidate in candidates
    ]


def measure_outages(conn: sqlite3.Connection, refs: dict[str, list[dict[str, str]]]) -> dict:
    """Sweep causal T-driving loss cohorts and evaluate without feeding labels to the detector."""
    labels = evaluation_labels(refs, {row["carrier"] for row in refs["devices"] if row["family"] == "T" and row["carrier"]})
    candidates = [Candidate(*values) for values in product(
        DRIVING_DUE_SECONDS, MAXIMUM_ONSET_SPREADS, MINIMUM_AFFECTED_COUNTS, MINIMUM_AFFECTED_SHARES,
    )]
    rows = replay_candidates(conn, refs, labels, candidates)
    selected = select_candidate(rows)
    base = candidates[rows.index(selected)]
    comparisons = [replace(base, healthy_count=count, healthy_share=share) for count, share in product(COMPARISON_COUNTS, COMPARISON_SHARES)]
    comparison_sensitivity = replay_candidates(conn, refs, labels, comparisons)
    return {
        "methodology": {
            "snapshot_seconds": SNAPSHOT_SECONDS,
            "label_guard_seconds": LABEL_GUARD_SECONDS,
            "development": [utc_text(HISTORY_START), utc_text(VALIDATION_START)],
            "validation": [utc_text(VALIDATION_START), utc_text(HISTORY_END)],
            "cohort": "Eligible ignition-on T trackers grouped by carrier and depot. Depot follows known VIN evidence when available. No end-of-history status filter.",
            "clock": "Receipts enter on the inclusive snapshot boundary. Future-skewed observations are excluded. Observation order guards ignition, fault and plan transitions.",
            "gap": "Driving is overdue strictly after latest driving evidence plus the candidate delay. Equality stays timely. An uninterrupted overdue run keeps its first onset through stale backfill. Observed ignition-off, power loss and inactive plans remove the device from its cohort.",
            "cluster": "Choose a qualifying window of gap onsets within the maximum spread. New clusters require an onset within the last spread duration. Sustained clusters overlap their immediately prior window.",
            "contrast": "The selection grid requires at least three timely eligible trackers and at least half of the eligible other-carrier cohort in the same depot. The off-grid contrast sweep keeps the selected driving and outage parameters fixed and does not change selection.",
            "label_use": "Support case carrier, depot, open and close times only grade the snapshots. Guarded minutes around labels are omitted from background volume. Background counts are unlabelled alerts, not verified false positives.",
            "fragmentation": "A labelled fragment is a run of consecutive detected minutes in the label window. An episode is a consecutive run per carrier/depot in the unguarded background.",
            "selection": "Rank on development only by more label matches, fewer background episodes and snapshots, fewer label fragments and earlier detection. Exact ties favor the prior kit's center values. Validation is reported unchanged.",
            "limits": "These snapshots measure a driving tracker seed and initial detection. Runtime incident continuation and recovery, compatible camera and daily/parked memberships, full replacement ownership, and location dispersion require later validation.",
        },
        "labelled_cases": [
            {"case_id": label.case_id, "depot": label.route[0], "carrier": label.route[1], "start": utc_text(label.start), "end": utc_text(label.end)}
            for label in labels
        ],
        "candidates": rows,
        "selected": selected,
        "comparison_sensitivity": comparison_sensitivity,
    }
