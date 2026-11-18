"""HTTP and process-lifecycle boundary for the support service."""

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .config import RulesConfig, load_config
from .models import (
    DeviceState,
    DeviceStatus,
    HealthResponse,
    IngestEnvelope,
    IngestResponse,
    LikelyCause,
    TriageResponse,
)
from .normalize import InvalidEvent, NormalizedEvent, normalize_event
from .projection import project_device
from .reference import References, load_references
from .store import EventStore, open_store
from .time_utils import from_epoch_us, parse_iso_instant, to_epoch_us

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "rules.json"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    rules: RulesConfig
    references: References
    store: EventStore


def get_runtime(request: Request) -> Runtime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Service is not ready.")
    return runtime


def parse_at(at: Annotated[str, Query(description="An ISO 8601 instant with an explicit UTC offset.")]) -> datetime:
    try:
        return parse_iso_instant(at)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(
            status_code=400, detail="Use an aware timestamp for 'at', such as 2026-10-12T14:05:12Z."
        ) from exc


def reject_non_json_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is outside the JSON grammar")


def accept_batch(events: list[object], runtime: Runtime) -> IngestResponse:
    tolerance = runtime.rules.defensive_limits.clock_ahead_tolerance.value
    normalized: list[NormalizedEvent] = []
    malformed = ignored = 0
    for event in events:
        try:
            observation = normalize_event(event, clock_ahead_tolerance_seconds=tolerance)
        except InvalidEvent:
            malformed += 1
            continue
        if observation is None:
            ignored += 1
        else:
            normalized.append(observation)

    result = runtime.store.write_batch(normalized)
    accepted = result.accepted + ignored
    logger.debug(
        "Ingest batch: accepted=%d inserted=%d retries=%d ignored=%d malformed=%d conflicts=%d",
        accepted, result.inserted, result.accepted - result.inserted, ignored, malformed, result.conflicts,
    )
    return IngestResponse(accepted=accepted)


CurrentRuntime = Annotated[Runtime, Depends(get_runtime)]
AtInstant = Annotated[datetime, Depends(parse_at)]


def create_app(data_dir: Path | None = None, config_path: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        rules = load_config(config_path if config_path is not None else RULES_PATH)
        reference_dir = data_dir if data_dir is not None else Path(os.environ.get("QF_DATA_DIR", "./data"))
        references = load_references(reference_dir)
        with open_store() as store:
            application.state.runtime = Runtime(rules, references, store)
            try:
                yield
            finally:
                del application.state.runtime

    application = FastAPI(
        title="The Quiet Fleet",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        responses={"4XX": {"description": "Invalid request or unknown resource"}},
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "Missing or invalid request parameters."})

    @application.get("/health", dependencies=[Depends(get_runtime)])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.post(
        "/ingest",
        responses={400: {"description": "Invalid JSON, event envelope, or batch size"}},
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": IngestEnvelope.model_json_schema()}},
            },
        },
    )
    async def ingest(request: Request, runtime: CurrentRuntime) -> IngestResponse:
        try:
            payload = json.loads(await request.body(), parse_constant=reject_non_json_constant)
        except (ValueError, RecursionError) as exc:
            raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from exc
        try:
            envelope = IngestEnvelope.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="Expected an object with an events list.") from exc

        maximum = runtime.rules.given_rules.ingest_batch_max.value
        if len(envelope.events) > maximum:
            raise HTTPException(status_code=400, detail=f"An events list can contain at most {maximum} entries.")

        return await run_in_threadpool(accept_batch, envelope.events, runtime)

    @application.get("/devices/{serial}/status", responses={404: {"description": "Unknown device serial"}})
    def device_status(serial: str, at: AtInstant, runtime: CurrentRuntime) -> DeviceStatus:
        device = runtime.references.devices.get(serial)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device serial.")
        cutoff = to_epoch_us(at)
        facts = project_device(cutoff, runtime.store.snapshot(cutoff, serial))
        contact = facts.last_contact
        if contact is None:
            reason = "No device observations are available at the requested instant."
        elif contact.time_quality == "clock_ahead":
            reason = "A device receipt is available, and its observation clock is ahead of the platform receipt."
        else:
            reason = "A device receipt is available. Device diagnosis is pending."
        return DeviceStatus(
            serial=device.serial,
            asset_id=device.asset_id,
            at=at,
            state=DeviceState.UNKNOWN,
            likely_cause=LikelyCause.UNKNOWN,
            confidence=0.0,
            last_heard_at=from_epoch_us(contact.first_received_us) if contact else None,
            reasons=[reason],
            evidence=[contact.event_id] if contact else [],
        )

    @application.get("/triage", dependencies=[Depends(get_runtime)])
    def triage(at: AtInstant) -> TriageResponse:
        return TriageResponse(at=at, items=[])

    return application


app = create_app()
