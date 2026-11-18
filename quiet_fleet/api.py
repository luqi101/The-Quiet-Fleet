"""HTTP and process-lifecycle boundary for the support service."""

import json
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated, NoReturn

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

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
from .reference import References, load_references
from .store import open_store

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "rules.json"
AT_FORMAT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


@dataclass(frozen=True)
class Runtime:
    rules: RulesConfig
    references: References
    store: Connection


def get_runtime(request: Request) -> Runtime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Service is not ready.")
    return runtime


def parse_at(at: Annotated[str, Query(description="An ISO 8601 instant with an explicit UTC offset.")]) -> datetime:
    message = "Use an aware timestamp for 'at', such as 2026-10-12T14:05:12Z."
    if not AT_FORMAT.fullmatch(at):
        raise HTTPException(status_code=400, detail=message)
    try:
        return datetime.fromisoformat(at).astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail=message) from exc


def reject_non_json_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is outside the JSON grammar")


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

        # P03 processes individual events. The foundation acknowledges zero persisted observations.
        return IngestResponse(accepted=0)

    @application.get("/devices/{serial}/status", responses={404: {"description": "Unknown device serial"}})
    def device_status(serial: str, at: AtInstant, runtime: CurrentRuntime) -> DeviceStatus:
        device = runtime.references.devices.get(serial)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device serial.")
        return DeviceStatus(
            serial=device.serial,
            asset_id=device.asset_id,
            at=at,
            state=DeviceState.UNKNOWN,
            likely_cause=LikelyCause.UNKNOWN,
            confidence=0.0,
            last_heard_at=None,
            reasons=["No device observations are available at the requested instant."],
            evidence=[],
        )

    @application.get("/triage", dependencies=[Depends(get_runtime)])
    def triage(at: AtInstant) -> TriageResponse:
        return TriageResponse(at=at, items=[])

    return application


app = create_app()
