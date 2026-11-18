"""Request and response shapes for the Quiet Fleet support service."""

from datetime import UTC
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)


from .time_utils import utc_text


Timestamp = Annotated[AwareDatetime, PlainSerializer(utc_text, return_type=str, when_used="json")]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Reasons = Annotated[list[NonBlank], Field(min_length=1)]


class DeviceState(StrEnum):
    REPORTING = "reporting"
    QUIET_EXPECTED = "quiet_expected"
    NEEDS_ACTION = "needs_action"
    UNKNOWN = "unknown"


class LikelyCause(StrEnum):
    NONE = "none"
    PARKED_NORMAL = "parked_normal"
    SLEEPING_BY_DESIGN = "sleeping_by_design"
    COLD_WEATHER = "cold_weather"
    PLANNED_DOWNTIME = "planned_downtime"
    COVERAGE_GAP = "coverage_gap"
    CARRIER_OUTAGE = "carrier_outage"
    POWER_LOSS = "power_loss"
    CAMERA_FAULT = "camera_fault"
    PLAN_PAUSED = "plan_paused"
    DEVICE_SWAPPED = "device_swapped"
    BATTERY_LOW = "battery_low"
    UNKNOWN = "unknown"


class WhoActs(StrEnum):
    CUSTOMER = "customer"
    TECHNICIAN = "technician"
    CARRIER = "carrier"
    SUPPORT = "support"
    NONE = "none"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ItemKind(StrEnum):
    DEVICE = "device"
    INCIDENT = "incident"


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ResponseModel):
    status: Literal["ok"]


class IngestEnvelope(BaseModel):
    # Individual events are validated independently after the envelope is accepted.
    events: Annotated[list[Any], Field(strict=True)]


class IngestResponse(ResponseModel):
    accepted: Annotated[int, Field(strict=True, ge=0)]


class DeviceStatus(ResponseModel):
    serial: NonBlank
    asset_id: NonBlank | None
    at: Timestamp
    state: DeviceState
    likely_cause: LikelyCause
    confidence: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    last_heard_at: Timestamp | None
    reasons: Reasons
    evidence: list[NonBlank]

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.state == DeviceState.REPORTING and self.likely_cause != LikelyCause.NONE:
            raise ValueError("reporting state requires likely_cause none")
        if self.last_heard_at is not None and self.last_heard_at.astimezone(UTC) > self.at.astimezone(UTC):
            raise ValueError("last_heard_at must be at or before at")
        return self


class TriageItem(ResponseModel):
    item_id: NonBlank
    kind: ItemKind
    serials: Annotated[list[NonBlank], Field(min_length=1)]
    asset_ids: list[NonBlank]
    likely_cause: LikelyCause
    who_acts: WhoActs
    next_action: NonBlank
    priority: Priority
    reasons: Reasons
    evidence: Annotated[list[NonBlank], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_serial_count(self) -> Self:
        if self.kind == ItemKind.DEVICE and len(self.serials) != 1:
            raise ValueError("a device item must contain one serial")
        if self.kind == ItemKind.INCIDENT and len(self.serials) < 2:
            raise ValueError("an incident must contain multiple distinct serials")
        if len(set(self.serials)) != len(self.serials) or len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("serials and assets must be unique within an item")
        return self


class TriageResponse(ResponseModel):
    at: Timestamp
    items: list[TriageItem]

    @model_validator(mode="after")
    def validate_unique_serials(self) -> Self:
        serials = [serial for item in self.items for serial in item.serials]
        if len(serials) != len(set(serials)):
            raise ValueError("each serial can appear at most once in triage")
        return self
