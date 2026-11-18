"""Comparable driving-location and awake-video opportunities for carrier diagnosis."""

import json
from dataclasses import dataclass
from enum import StrEnum

from .asset_context import DeviceContext
from .assignment_fault import assignment_fault
from .config import RulesConfig
from .environment_faults import downtime_fault
from .individual_faults import plan_timeline
from .reference import Asset, Device
from .store import EventFact


_US_PER_SECOND = 1_000_000


class ReportingMode(StrEnum):
    DRIVING = "driving location"
    AWAKE = "awake camera"


@dataclass(frozen=True, slots=True)
class ReportingPeer:
    device: Device
    asset: Asset
    carrier: str
    mode: ReportingMode
    report: EventFact
    missing_since_us: int | None

    @property
    def serial(self) -> str:
        return self.device.serial


def _observed(event: EventFact) -> int:
    assert event.observed_us is not None
    return event.observed_us


def reporting_peer(context: DeviceContext, at_us: int, rules: RulesConfig) -> ReportingPeer | None:
    """Require a proven reporting mode and usable report in the current opportunity."""
    device, asset, facts = context.device, context.asset, context.facts
    if (
        asset is None or not device.carrier or device.family not in {"T", "C"}
        or context.documented_removed or assignment_fault(context) is not None
        or downtime_fault(at_us, context, rules) is not None
    ):
        return None
    plan = plan_timeline(facts.observations)
    if plan.opening is not None:
        return None
    resumed = plan.last_resumption

    driving = device.family == "T"
    tracker = facts if driving else context.tracker_facts
    if (
        tracker is None or context.tracker_ambiguous or tracker.ignition_on is not True
        or tracker.ignition_since is None or tracker.power_disconnect is not None
        or (not driving and facts.camera_storage_error is not None)
    ):
        return None

    mode = ReportingMode.DRIVING if driving else ReportingMode.AWAKE
    ruleset = rules.calibrated_parameters
    duration = ruleset.tracker_driving_overdue if driving else ruleset.camera_recording_overdue
    allowance = duration.value * _US_PER_SECOND
    start = _observed(tracker.ignition_since)
    # Recommissioning requires a report since the drive, restoration or plan resumption.
    restored = next((event for event in reversed(tracker.observations) if event.kind == "power_restore"), None)
    start = max(_observed(event) for event in (tracker.ignition_since, restored, resumed) if event is not None)
    if not driving and facts.camera_status == "sleeping":
        return None

    report = None
    latest_transport_us = None
    for event in reversed(facts.observations):
        observed = _observed(event)
        if observed < start or (report is not None and observed < _observed(report)):
            break
        if max(observed, event.first_received_us) > observed + allowance:
            continue
        if driving and event.kind in {"position", "heartbeat", "ignition_on", "low_voltage"}:
            is_report = event.kind == "position" and json.loads(event.payload_json)["ignition"] is True
        elif not driving and event.kind == "camera_status":
            is_report = json.loads(event.payload_json)["status"] == "recording"
        else:
            continue
        if is_report:
            report = report or event
        elif latest_transport_us is None:
            latest_transport_us = observed
    if report is None:
        return None

    # A new measurement whose deadline had already expired before receipt does
    # not reset a gap. A timely non-report can establish a working transport
    # path without making video or location healthy.
    through = _observed(report) + allowance
    transport_cutoff = through + 1 if driving else _observed(report)
    if latest_transport_us is not None and latest_transport_us >= transport_cutoff:
        return None
    return ReportingPeer(device, asset, device.carrier, mode, report, through if at_us > through else None)
