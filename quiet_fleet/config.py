"""Validate the versioned local policy register before serving requests."""

from datetime import date
from pathlib import Path
from typing import Annotated, Generic, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator


Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
PositiveInt = Annotated[int, Field(gt=0)]
NonnegativeInt = Annotated[int, Field(ge=0)]
GroupSize = Annotated[int, Field(ge=2)]
Ratio = Annotated[float, Field(ge=0, le=1)]
Percentage = Annotated[float, Field(ge=0, le=100)]
FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
LocalTime = Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
Radix = Annotated[int, Field(ge=2, le=36)]
SignalLevel = Annotated[int, Field(ge=0, le=5)]
T = TypeVar("T")


class ConfigError(ValueError):
    """A rules file is missing, unreadable, or invalid."""


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Rule(ConfigModel, Generic[T]):
    value: T
    unit: Text
    comparator: Text
    provenance: Text
    rationale: Text
    sample_size: NonnegativeInt | None
    sensitivity_candidates: list[T]
    test: Text


class GivenRules(ConfigModel):
    tracker_position_interval: Rule[PositiveInt]
    tracker_parked_heartbeat_interval: Rule[PositiveInt]
    tracker_parked_overdue: Rule[PositiveInt]
    camera_sleep_delay: Rule[PositiveInt]
    a_checkin_interval: Rule[PositiveInt]
    shift_start_local: Rule[LocalTime]
    ingest_batch_max: Rule[Annotated[int, Field(ge=5_000, le=5_000)]]
    ingest_response_limit: Rule[Annotated[int, Field(ge=10, le=10)]]


class CalibratedParameters(ConfigModel):
    tracker_driving_overdue: Rule[PositiveInt]
    camera_recording_overdue: Rule[PositiveInt]
    normal_receipt_lag: Rule[NonnegativeInt]
    a_daily_overdue: Rule[PositiveInt]
    bx_daily_overdue: Rule[PositiveInt]


class WireFormatConstants(ConfigModel):
    a_legacy_timestamp_scale: Rule[PositiveInt]
    bx_epoch_radix: Rule[Radix]
    bx_battery_full_scale: Rule[PositiveInt]
    bx_coordinate_scale: Rule[PositiveInt]
    bx_moving_mask: Rule[PositiveInt]
    bx_battery_low_mask: Rule[PositiveInt]
    bx_gps_fix_mask: Rule[PositiveInt]

    @model_validator(mode="after")
    def validate_bx_masks(self) -> Self:
        masks = (self.bx_moving_mask.value, self.bx_battery_low_mask.value, self.bx_gps_fix_mask.value)
        if len(set(masks)) != len(masks) or any(mask & (mask - 1) for mask in masks):
            raise ValueError("BX masks must be distinct single bits")
        return self


class OperationalAssumptions(ConfigModel):
    camera_wake_grace: Rule[PositiveInt]
    camera_reboot_response_grace: Rule[PositiveInt]
    camera_failed_reboots_before_visit: Rule[PositiveInt]
    a_low_battery: Rule[Percentage]
    a_battery_recovery: Rule[Percentage]
    bx_battery_recovery: Rule[Percentage]
    bx_percentage_only_low_enabled: Rule[bool]
    cold_temperature: Rule[FiniteNumber]
    cold_healthy_battery_minimum: Rule[Percentage]
    cold_silence_limit: Rule[PositiveInt]
    urgent_operational_horizon: Rule[PositiveInt]
    incident_close_below_remaining_devices: Rule[GroupSize]
    outage_maximum_onset_spread_seconds: Rule[NonnegativeInt]
    outage_minimum_affected_devices: Rule[GroupSize]
    outage_minimum_affected_share: Rule[Ratio]
    outage_minimum_healthy_comparison_devices: Rule[PositiveInt]
    outage_minimum_healthy_comparison_share: Rule[Ratio]
    seasonal_downtime_suppression_enabled: Rule[bool]

    @model_validator(mode="after")
    def validate_battery_thresholds(self) -> Self:
        low = self.a_low_battery.value
        if self.a_battery_recovery.value <= low or self.cold_healthy_battery_minimum.value <= low:
            raise ValueError("A recovery and healthy battery thresholds must exceed the A low battery threshold")
        return self


class DefensiveLimits(ConfigModel):
    clock_ahead_tolerance: Rule[NonnegativeInt]
    query_timestamp_requires_offset: Rule[bool]

    @model_validator(mode="after")
    def validate_timestamp_policy(self) -> Self:
        if not self.query_timestamp_requires_offset.value:
            raise ValueError("query timestamps must require an explicit UTC offset")
        return self


class ApprovedDowntime(ConfigModel):
    asset_ids: tuple[Text, ...] = ()
    asset_uses: tuple[Text, ...] = ()
    depot: Literal["MSS", "REG"] | None = None
    start_local: date
    end_local: date
    provenance: Text

    @model_validator(mode="after")
    def validate_scope_and_interval(self) -> Self:
        if not (self.asset_ids or self.asset_uses):
            raise ValueError("approved downtime requires a specific asset ID or use")
        if self.start_local >= self.end_local:
            raise ValueError("approved downtime ends after its first local date")
        return self


class SitePolicy(ConfigModel):
    downtime: tuple[ApprovedDowntime, ...] = ()
    weak_signal_max: Rule[SignalLevel] = Field(default_factory=lambda: Rule[SignalLevel](
        value=1,
        unit="modem signal level on the supplied 0–5 scale",
        comparator="signal <= value",
        provenance="Vendor heartbeat scale and P05 conservative engineering policy",
        rationale="Treat the lowest categories as corroboration only, alongside eligible device-specific buffering evidence.",
        sample_size=None,
        sensitivity_candidates=[0, 1],
        test="P05 coverage history and backfill fixtures",
    ))
    coverage_monitor_limit: Rule[PositiveInt] = Field(default_factory=lambda: Rule[PositiveInt](
        value=5_400,
        unit="seconds",
        comparator="elapsed <= value",
        provenance="P01 observed maximum T delivery lag of 5,396 seconds, rounded to 90 minutes",
        rationale="A provisional ceiling for coverage attribution on a still-overdue position.",
        sample_size=None,
        sensitivity_candidates=[3_600, 5_400],
        test="P05 coverage history and backfill fixtures",
    ))


class RulesConfig(ConfigModel):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    given_rules: GivenRules
    calibrated_parameters: CalibratedParameters
    wire_format_constants: WireFormatConstants
    operational_assumptions: OperationalAssumptions
    defensive_limits: DefensiveLimits
    site_policy: SitePolicy = Field(default_factory=SitePolicy)

    @model_validator(mode="after")
    def validate_cadence_thresholds(self) -> Self:
        given = self.given_rules
        calibrated = self.calibrated_parameters
        if given.tracker_parked_overdue.value <= given.tracker_parked_heartbeat_interval.value:
            raise ValueError("the parked tracker deadline must exceed the parked heartbeat interval")
        if calibrated.tracker_driving_overdue.value <= given.tracker_position_interval.value:
            raise ValueError("the driving tracker deadline must exceed the driving position interval")
        if calibrated.a_daily_overdue.value < given.a_checkin_interval.value:
            raise ValueError("the A reporting deadline must cover one full check-in interval")
        if self.operational_assumptions.seasonal_downtime_suppression_enabled.value and not self.site_policy.downtime:
            raise ValueError("seasonal downtime requires an approved scope, effective dates, and provenance")
        return self


def load_config(path: Path) -> RulesConfig:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"Cannot read rules configuration at {path}: {exc}") from exc

    try:
        return RulesConfig.model_validate_json(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid rules configuration at {path}: {exc}") from exc
