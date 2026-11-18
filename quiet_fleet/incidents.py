"""Reconstruct shared reporting-loss episodes from immutable receipt-cutoff views."""

from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
import json
from operator import attrgetter

from .asset_context import DeviceContextReader
from .config import RulesConfig
from .models import LikelyCause, WhoActs
from .reference import Device, References
from .reporting_peers import ReportingMode, ReportingPeer, reporting_peer
from .store import ReadSnapshot
from .time_utils import from_epoch_us, utc_text


_US_PER_SECOND = 1_000_000
_SHARED_ACTION = "Ask support to check the common platform or network path and verify reporting recovery before routing to a provider."


def _deadline(peer: ReportingPeer) -> int:
    assert peer.missing_since_us is not None
    return peer.missing_since_us


@dataclass(frozen=True, slots=True)
class _Policy:
    spread: int
    probe: int
    minimum: int
    share: float
    control_minimum: int
    control_share: float
    retain: int
    mode_offset: int

    @classmethod
    def from_rules(cls, rules: RulesConfig) -> "_Policy":
        policy = rules.operational_assumptions
        timings = rules.calibrated_parameters
        return cls(
            spread=policy.outage_maximum_onset_spread_seconds.value * _US_PER_SECOND,
            probe=policy.outage_probe_interval.value * _US_PER_SECOND,
            minimum=policy.outage_minimum_affected_devices.value,
            share=policy.outage_minimum_affected_share.value,
            control_minimum=policy.outage_minimum_healthy_comparison_devices.value,
            control_share=policy.outage_minimum_healthy_comparison_share.value,
            retain=policy.incident_close_below_remaining_devices.value,
            mode_offset=abs(timings.tracker_driving_overdue.value - timings.camera_recording_overdue.value) * _US_PER_SECOND,
        )


@dataclass(frozen=True, slots=True)
class _Seed:
    at_us: int
    depot: str
    carriers: tuple[str, ...]
    mode: ReportingMode
    members: tuple[ReportingPeer, ...]
    eligible_count: int
    controls: tuple[ReportingPeer, ...]
    firmware: tuple[str, str] | None = None

    @property
    def first_deadline(self) -> int:
        return _deadline(self.members[0])

    @property
    def carrier_specific(self) -> bool:
        return len(self.carriers) == 1


@dataclass(slots=True)
class _Episode:
    seed: _Seed
    remaining: dict[str, ReportingPeer]
    joined: set[str] = field(init=False)

    def __post_init__(self) -> None:
        self.joined = set(self.remaining)

    def update(self, peers: list[ReportingPeer]) -> None:
        self.remaining = {
            peer.serial: peer for peer in peers
            if peer.serial in self.remaining and peer.missing_since_us == self.remaining[peer.serial].missing_since_us
        }

    def join(self, peer: ReportingPeer, policy: _Policy) -> bool:
        if peer.serial in self.joined or peer.carrier not in self.seed.carriers:
            return False
        if self.seed.firmware is not None and _firmware(peer) != self.seed.firmware:
            return False
        delta = _deadline(peer) - self.seed.first_deadline
        if peer.mode == self.seed.mode:
            compatible = 0 <= delta <= policy.spread
        else:
            # Cameras and trackers use different deadlines for the same missing
            # transport. Compare in-mode first, then adjust cross-mode onset.
            compatible = self.seed.carrier_specific and abs(delta) <= policy.spread + policy.mode_offset
            compatible = compatible and abs(_last_report_us(peer) - _last_report_us(self.seed.members[0])) <= policy.spread
        if compatible:
            self.remaining[peer.serial] = peer
            self.joined.add(peer.serial)
        return compatible


@dataclass(frozen=True, slots=True)
class Incident:
    item_id: str
    serials: tuple[str, ...]
    asset_ids: tuple[str, ...]
    cause: LikelyCause
    owner: WhoActs
    next_action: str
    confidence: float
    reasons: tuple[str, ...]
    evidence: tuple[str, ...]


def _last_report_us(peer: ReportingPeer) -> int:
    observed = peer.report.observed_us
    assert observed is not None
    return observed


def _firmware(peer: ReportingPeer) -> tuple[str, str] | None:
    device = peer.device
    return (device.model, device.firmware) if device.model and device.firmware else None


def _windows(gaps: list[ReportingPeer], at_us: int, policy: _Policy) -> list[tuple[ReportingPeer, ...]]:
    gaps = sorted(gaps, key=lambda peer: (_deadline(peer), peer.serial))
    windows = []
    left = 0
    for right, latest in enumerate(gaps):
        while _deadline(latest) - _deadline(gaps[left]) > policy.spread:
            left += 1
        if right - left + 1 >= policy.minimum and at_us - _deadline(latest) <= max(policy.spread, policy.probe):
            windows.append(tuple(gaps[left:right + 1]))
    return windows


def _enough(affected: int, eligible: int, minimum: int, share: float) -> bool:
    return affected >= minimum and affected >= eligible * share


def _live_controls(peers: list[ReportingPeer], missing: tuple[ReportingPeer, ...]) -> tuple[ReportingPeer, ...]:
    last_loss_report = max(map(_last_report_us, missing))
    return tuple(
        peer for peer in peers if peer.missing_since_us is None and _last_report_us(peer) > last_loss_report
    )


def _shared_seed(
    at_us: int, depot: str, mode: ReportingMode, peers: list[ReportingPeer],
    gaps: list[ReportingPeer], policy: _Policy,
) -> _Seed | None:
    by_carrier = defaultdict(list)
    by_firmware = defaultdict(list)
    for peer in peers:
        by_carrier[peer.carrier].append(peer)
        signature = _firmware(peer)
        if signature is not None:
            by_firmware[signature].append(peer)

    candidates = []
    for members in _windows(gaps, at_us, policy):
        affected = defaultdict(int)
        for member in members:
            affected[member.carrier] += 1
        carriers = tuple(sorted(affected))
        if len(carriers) > 1 and all(
            _enough(count, len(by_carrier[carrier]), policy.retain, policy.share)
            for carrier, count in affected.items()
        ):
            candidates.append(_Seed(
                at_us, depot, carriers, mode, members, len(peers), _live_controls(peers, members),
            ))
    for signature, comparable in by_firmware.items():
        for members in _windows([peer for peer in gaps if _firmware(peer) == signature], at_us, policy):
            affected = defaultdict(int)
            for member in members:
                affected[member.carrier] += 1
            carriers = tuple(sorted(affected))
            controls = _live_controls([peer for peer in peers if _firmware(peer) != signature], members)
            if len(carriers) > 1 and min(affected.values()) >= policy.retain and controls and _enough(
                len(members), len(comparable), policy.minimum, policy.share,
            ):
                candidates.append(_Seed(
                    at_us, depot, carriers, mode, members, len(comparable), controls, firmware=signature,
                ))
    return max(candidates, key=lambda seed: (len(seed.members), -seed.first_deadline, seed.firmware is not None), default=None)


def _carrier_seeds(
    at_us: int, depot: str, mode: ReportingMode, peers: list[ReportingPeer],
    gaps: list[ReportingPeer], policy: _Policy,
) -> list[_Seed]:
    by_carrier = defaultdict(list)
    for peer in peers:
        by_carrier[peer.carrier].append(peer)
    seeds = []
    for carrier, eligible in sorted(by_carrier.items()):
        others = [peer for peer in peers if peer.carrier != carrier]
        candidates = []
        for members in _windows([peer for peer in gaps if peer.carrier == carrier], at_us, policy):
            if not _enough(len(members), len(eligible), policy.minimum, policy.share):
                continue
            controls = _live_controls(others, members)
            if _enough(len(controls), len(others), policy.control_minimum, policy.control_share):
                candidates.append(_Seed(at_us, depot, (carrier,), mode, members, len(eligible), controls))
        best = max(candidates, key=lambda seed: (len(seed.members), -seed.first_deadline), default=None)
        if best is not None:
            seeds.append(best)
    return seeds


def _peers(reader: DeviceContextReader, devices: list[Device], rules: RulesConfig) -> list[ReportingPeer]:
    peers = []
    for device in devices:
        peer = reporting_peer(reader.read(device, cohort=True), reader.snapshot.at_us, rules)
        if peer is not None:
            peers.append(peer)
    return peers


def _probe_windows(gaps: list[ReportingPeer], at_us: int, policy: _Policy) -> list[tuple[int, int]]:
    """Search only near groups that could still have enough continuous members."""
    ordered = sorted(map(_deadline, gaps))
    tolerance = policy.spread + policy.mode_offset
    windows: list[tuple[int, int]] = []
    for index, onset in enumerate(ordered):
        nearby = ordered[max(0, index - policy.retain + 1):index + policy.retain]
        if sum(abs(value - onset) <= tolerance for value in nearby) < policy.retain:
            continue
        start = ((onset - tolerance) // policy.probe) * policy.probe
        end = min(at_us, onset + tolerance + max(policy.spread, policy.probe))
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return windows


def _advance(
    episodes: list[_Episode], peers: list[ReportingPeer], at_us: int, depot: str, policy: _Policy,
) -> list[_Episode]:
    gaps = [peer for peer in peers if peer.missing_since_us is not None]
    ongoing = []
    claimed = set()
    for episode in episodes:
        episode.update(gaps)
        if len(episode.remaining) >= policy.retain:
            claimed.update(episode.remaining)
            ongoing.append(episode)

    def join(episode: _Episode) -> None:
        for peer in gaps:
            if peer.serial not in claimed and episode.join(peer, policy):
                claimed.add(peer.serial)

    # A synchronized cross-carrier pattern can supersede an earlier carrier
    # interpretation when it explains that group's complete surviving core.
    for mode in ReportingMode:
        comparable = [peer for peer in peers if peer.mode == mode]
        active = [peer for peer in gaps if peer.mode == mode]
        seed = _shared_seed(at_us, depot, mode, comparable, active, policy)
        if seed is not None and any(peer.serial in claimed for peer in seed.members):
            serials = {peer.serial for peer in seed.members}
            superseded = [
                episode for episode in ongoing if episode.seed.carrier_specific and episode.seed.mode == mode
                and {peer.serial for peer in episode.remaining.values() if peer.mode == mode} <= serials
                and sum(peer.mode == mode for peer in episode.remaining.values()) >= policy.retain
            ]
            still_claimed = claimed.difference(*(episode.remaining for episode in superseded))
            if serials.isdisjoint(still_claimed):
                ongoing = [episode for episode in ongoing if episode not in superseded]
                claimed = still_claimed
            else:
                seed = _shared_seed(at_us, depot, mode, comparable, [p for p in active if p.serial not in claimed], policy)
        if seed is not None:
            episode = _Episode(seed, {peer.serial: peer for peer in seed.members})
            claimed.update(episode.remaining)
            join(episode)
            ongoing.append(episode)
    for episode in ongoing:
        join(episode)
    for mode in ReportingMode:
        comparable = [peer for peer in peers if peer.mode == mode]
        available = [peer for peer in gaps if peer.mode == mode and peer.serial not in claimed]
        for seed in _carrier_seeds(at_us, depot, mode, comparable, available, policy):
            episode = _Episode(seed, {peer.serial: peer for peer in seed.members})
            claimed.update(episode.remaining)
            join(episode)
            ongoing.append(episode)
    return ongoing


def _to_incident(episode: _Episode) -> Incident:
    seed = episode.seed
    members = sorted(episode.remaining.values(), key=attrgetter("serial"))
    scope = seed.carriers[0] if seed.carrier_specific else " and ".join(seed.carriers)
    if seed.carrier_specific:
        cause, owner = LikelyCause.CARRIER_OUTAGE, WhoActs.CARRIER
        action = (
            f"Escalate one incident to {scope} for a network check. "
            "Recommend one consolidated customer impact update and monitor reporting recovery."
        )
        explanation = (
            f"{scope} had {len(seed.members)} of {seed.eligible_count} eligible {seed.mode} devices become overdue "
            f"together in {seed.depot}. {len(seed.controls)} comparable devices on other carriers continued reporting."
        )
        confidence = 0.9
    else:
        cause, owner, action = LikelyCause.UNKNOWN, WhoActs.SUPPORT, _SHARED_ACTION
        explanation = (
            f"{len(seed.members)} eligible {seed.mode} devices on {scope} became overdue together in {seed.depot}. "
            "The interruption spans carriers, so provider ownership is uncertain."
        )
        if seed.firmware is not None:
            model, version = seed.firmware
            explanation += f"The affected set shares {model} firmware {version}, while other firmware kept reporting."
        confidence = 0.6

    identifier = sha256(json.dumps(
        (seed.depot, seed.carriers, seed.mode, seed.at_us, seed.first_deadline, seed.firmware),
        ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")).hexdigest()
    allowance = (seed.first_deadline - _last_report_us(seed.members[0])) / _US_PER_SECOND
    spread = (_deadline(seed.members[-1]) - seed.first_deadline) / _US_PER_SECOND
    timing = (
        f"The group qualified at {utc_text(from_epoch_us(seed.at_us))}. "
        f"Its {allowance:g}-second reporting deadlines fell within a {spread:g}-second span."
    )
    evidence = tuple(dict.fromkeys(peer.report.event_id for peer in (*members, *seed.members, *seed.controls)))
    assets = tuple(sorted({peer.asset.asset_id for peer in members}))
    return Incident(
        item_id=f"incident-{identifier[:24]}",
        serials=tuple(peer.serial for peer in members),
        asset_ids=assets,
        cause=cause,
        owner=owner,
        next_action=action,
        reasons=(explanation, timing, f"{len(members)} overdue devices on {len(assets)} assets still need follow-up."),
        evidence=evidence,
        confidence=confidence,
    )


def detect_incidents(snapshot: ReadSnapshot, references: References, rules: RulesConfig) -> tuple[Incident, ...]:
    policy = _Policy.from_rules(rules)
    by_depot = defaultdict(list)
    # An unresolved VIN/roster discrepancy cannot arbitrate a carrier
    # comparison. Use the roster to shortlist, then verify it in the reader.
    for device in references.devices.values():
        asset = references.assets.get(device.asset_id)
        if asset is not None and device.family in {"T", "C"} and device.carrier and device.status != "stock":
            by_depot[asset.depot].append(device)
    reader = DeviceContextReader(snapshot, references, rules)
    found = []
    for depot, devices in sorted(by_depot.items()):
        current = _peers(reader, devices, rules)
        gaps = [peer for peer in current if peer.missing_since_us is not None]
        if len(gaps) < policy.retain:
            continue
        episodes = []
        for start, end in _probe_windows(gaps, snapshot.at_us, policy):
            for probe in range(start, end + 1, policy.probe):
                historical = DeviceContextReader(snapshot.as_of(probe), references, rules)
                episodes = _advance(episodes, _peers(historical, devices, rules), probe, depot, policy)
        for episode in episodes:
            episode.update(gaps)
            if len(episode.remaining) >= policy.retain:
                found.append(_to_incident(episode))
    return tuple(found)
