"""Apply the support priority policy to actual scheduled use and local shifts."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from types import MappingProxyType

from .config import RulesConfig
from .models import LikelyCause, Priority
from .reference import Job
from .time_utils import DEPOT_ZONES, utc_text


_CONFIRMED_IMPACT = {
    LikelyCause.POWER_LOSS, LikelyCause.BATTERY_LOW, LikelyCause.CAMERA_FAULT,
    LikelyCause.PLAN_PAUSED, LikelyCause.CARRIER_OUTAGE,
}


def next_shift(at: datetime, depot: str, start: time) -> datetime | None:
    """Return the shift at or after the checkpoint, including weekends."""
    zone = DEPOT_ZONES[depot]
    try:
        local_date = at.astimezone(zone).date()
        shift = datetime.combine(local_date, start, zone).astimezone(UTC)
        if shift < at:
            shift = datetime.combine(local_date + timedelta(days=1), start, zone).astimezone(UTC)
        return shift
    except OverflowError:
        # The explicit query instant can be at a limit of datetime's range.
        return None


def _local_text(instant: datetime, depot: str) -> str:
    try:
        return instant.astimezone(DEPOT_ZONES[depot]).isoformat(sep=" ")
    except OverflowError:
        return utc_text(instant)


@dataclass(frozen=True, slots=True)
class Work:
    active: tuple[Job, ...]
    next_job: Job | None
    deadline: datetime | None
    shift_due: bool
    urgent: bool

    def reason(self) -> str | None:
        if self.active:
            job = self.active[0]
            affected = len({active.asset_id for active in self.active})
            prefix = f"{affected} affected assets have work in progress. " if affected > 1 else ""
            return (
                f"{prefix}Asset {job.asset_id} has {job.job_type} work in progress in {job.depot} "
                f"until {_local_text(job.end, job.depot)}. Verify service for the current work."
            )
        if self.next_job is None:
            return None
        job = self.next_job
        reason = (
            f"Asset {job.asset_id} is scheduled for {job.job_type} work in {job.depot} "
            f"at {_local_text(job.start, job.depot)}."
        )
        if self.shift_due:
            assert self.deadline is not None
            return f"{reason} Prepare for its local shift at {_local_text(self.deadline, job.depot)}."
        return f"{reason} Verify service before the job starts."


def _job_order(job: Job) -> tuple[datetime, str, str]:
    return job.start, job.asset_id, job.job_id


@dataclass(frozen=True, slots=True)
class OperationalContext:
    at: datetime
    jobs_by_asset: Mapping[str, tuple[Job, ...]]
    shifts: Mapping[str, datetime | None]
    urgent_horizon: timedelta
    broad_device_count: int

    def _deadline(self, job: Job) -> datetime:
        shift = self.shifts[job.depot]
        if shift is not None and shift < job.start:
            zone = DEPOT_ZONES[job.depot]
            try:
                if shift.astimezone(zone).date() == job.start.astimezone(zone).date():
                    return shift
            except OverflowError:
                pass
        return job.start

    def work_for(self, assets: Iterable[str]) -> Work:
        active = []
        upcoming = []
        for asset in assets:
            for job in self.jobs_by_asset.get(asset, ()):
                if job.start > self.at:
                    upcoming.append(job)
                    break
                if self.at < job.end:
                    active.append(job)
        if active:
            return Work(tuple(sorted(active, key=_job_order)), None, self.at, False, True)
        if not upcoming:
            return Work((), None, None, False, False)
        job = min(upcoming, key=lambda item: (self._deadline(item), _job_order(item)))
        deadline = self._deadline(job)
        return Work((), job, deadline, deadline < job.start, deadline - self.at <= self.urgent_horizon)

    def priority(
        self, cause: LikelyCause, work: Work, *,
        incident_devices: int = 0, parked_camera: bool = False, recheck_at: datetime | None = None,
    ) -> Priority:
        if cause == LikelyCause.CARRIER_OUTAGE and incident_devices >= self.broad_device_count:
            return Priority.HIGH
        if cause in _CONFIRMED_IMPACT and work.urgent:
            if work.active or recheck_at is None or (work.deadline is not None and recheck_at >= work.deadline):
                return Priority.HIGH
        if cause == LikelyCause.COVERAGE_GAP:
            return Priority.MEDIUM if work.urgent else Priority.LOW
        if work.deadline is not None:
            return Priority.MEDIUM
        if cause in {LikelyCause.PLAN_PAUSED, LikelyCause.DEVICE_SWAPPED} or parked_camera:
            return Priority.LOW
        return Priority.MEDIUM


class Operations:
    def __init__(self, jobs: Iterable[Job], rules: RulesConfig) -> None:
        by_asset = defaultdict(list)
        for job in jobs:
            by_asset[job.asset_id].append(job)
        self._jobs = MappingProxyType({asset: tuple(sorted(rows, key=_job_order)) for asset, rows in by_asset.items()})
        self._shift_start = time.fromisoformat(rules.given_rules.shift_start_local.value)
        self._horizon = timedelta(seconds=rules.operational_assumptions.urgent_operational_horizon.value)
        self._broad = rules.operational_assumptions.outage_minimum_affected_devices.value

    def at(self, at: datetime) -> OperationalContext:
        shifts = MappingProxyType({depot: next_shift(at, depot, self._shift_start) for depot in DEPOT_ZONES})
        return OperationalContext(at, self._jobs, shifts, self._horizon, self._broad)
