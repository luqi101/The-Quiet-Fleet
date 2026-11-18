import builtins
import csv
import io
import math
import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from quiet_fleet.api import create_app
from quiet_fleet.models import DeviceState, ItemKind, LikelyCause, Priority, WhoActs


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "config" / "rules.json"
TRACKER = "T-90001"
STOCK_TRACKER = "T-90002"
ASSET = "V-901"
AT = "2026-10-04T14:17:20Z"
OFFSET_AT = "2026-10-04T10:17:20-04:00"


def write_references(directory: Path, tracker: str = TRACKER) -> None:
    directory.mkdir()
    tables = {
        "assets": (
            ("asset_id", "type", "depot", "use", "make_model", "year", "vin", "status"),
            (ASSET, "van", "MSS", "service", "Test Van", "2024", "1FTBW1X80RKA12345", "active"),
        ),
        "devices": (
            ("serial", "family", "model", "firmware", "carrier", "asset_id", "status", "installed_at"),
            (tracker, "T", "T-series", "1.0.0", "Test Carrier", ASSET, "active", "2024-01-01"),
            (STOCK_TRACKER, "T", "T-series", "1.0.0", "Test Carrier", "", "stock", ""),
        ),
        "schedule": (
            ("job_id", "asset_id", "depot", "start", "end", "job_type"),
            ("J-MSS-1004-90000", ASSET, "MSS", "2026-10-04T11:00:00Z", "2026-10-04T13:00:00Z", "inspection"),
        ),
        "weather": (
            ("date", "depot", "low_c", "high_c"),
            ("2026-10-04", "MSS", "6", "17"),
        ),
        "plan_changes": (
            ("serial", "time", "plan", "status", "reason", "event_id"),
            (tracker, "2026-10-04T12:30:00Z", "data", "paused", "data_limit", "e90000001"),
        ),
        "support_cases": (
            ("case_id", "opened_at", "closed_at", "depot", "asset_id", "serial", "reported_by", "symptom", "root_cause", "action", "outcome", "notes"),
            ("CS-9001", "2026-10-04T12:00:00Z", "2026-10-04T13:00:00Z", "MSS", ASSET, tracker,
             "customer", "The tracker went quiet", "power_loss", "technician_visit", "resolved", "Test case"),
        ),
    }
    for name, rows in tables.items():
        with (directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as destination:
            csv.writer(destination).writerows(rows)


class HTTPFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data_dir = self.workspace / "data"
        write_references(self.data_dir)

    def client(self) -> TestClient:
        return TestClient(create_app(data_dir=self.data_dir, config_path=RULES))

    def test_default_and_alternate_reference_directory(self) -> None:
        alternate = self.workspace / "alternate"
        alternate_serial = "T-90101"
        write_references(alternate, alternate_serial)
        working_directory = Path.cwd()
        try:
            os.chdir(self.workspace)
            with patch.dict(os.environ):
                os.environ.pop("QF_DATA_DIR", None)
                with TestClient(create_app(config_path=RULES)) as client:
                    response = client.get(f"/devices/{TRACKER}/status", params={"at": AT})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["asset_id"], ASSET)
                os.environ["QF_DATA_DIR"] = str(alternate)
                with TestClient(create_app(config_path=RULES)) as client:
                    response = client.get(f"/devices/{alternate_serial}/status", params={"at": AT})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["serial"], alternate_serial)
                    self.assertEqual(client.get(f"/devices/{TRACKER}/status", params={"at": AT}).status_code, 404)
        finally:
            os.chdir(working_directory)

    def test_health_status_and_triage_contract(self) -> None:
        with self.client() as client:
            health = client.get("/health")
            self.assertEqual((health.status_code, health.json()), (200, {"status": "ok"}))
            for serial, asset in ((TRACKER, ASSET), (STOCK_TRACKER, None)):
                with self.subTest(serial=serial):
                    response = client.get(f"/devices/{serial}/status", params={"at": OFFSET_AT})
                    self.assertEqual(response.status_code, 200, response.text)
                    body = response.json()
                    self.assertEqual(set(body), {
                        "serial", "asset_id", "at", "state", "likely_cause", "confidence",
                        "last_heard_at", "reasons", "evidence",
                    })
                    self.assertEqual((body["serial"], body["asset_id"], body["at"]), (serial, asset, AT))
                    self.assertEqual((body["state"], body["likely_cause"]), ("unknown", "unknown"))
                    self.assertIn(type(body["confidence"]), (int, float))
                    self.assertTrue(math.isfinite(body["confidence"]))
                    self.assertLessEqual(0, body["confidence"])
                    self.assertLessEqual(body["confidence"], 1)
                    self.assertIsNone(body["last_heard_at"])
                    self.assertEqual(body["evidence"], [])
                    self.assertIsInstance(body["reasons"], list)
                    self.assertTrue(body["reasons"])
                    self.assertTrue(all(isinstance(reason, str) and reason.strip() for reason in body["reasons"]))
            triage = client.get("/triage", params={"at": OFFSET_AT})
            self.assertEqual((triage.status_code, triage.json()), (200, {"at": AT, "items": []}))

    def test_unknown_serial_and_unsupported_routes_return_404(self) -> None:
        with self.client() as client:
            for route in ("/devices/T-99999/status", "/job-cover", "/visits", "/docs", "/redoc"):
                with self.subTest(route=route):
                    response = client.get(route, params={"at": AT})
                    self.assertEqual(response.status_code, 404, response.text)

    def test_response_enum_values_match_vendor_contract(self) -> None:
        expected = {
            DeviceState: {"reporting", "quiet_expected", "needs_action", "unknown"},
            LikelyCause: {
                "none", "parked_normal", "sleeping_by_design", "cold_weather", "planned_downtime", "coverage_gap",
                "carrier_outage", "power_loss", "camera_fault", "plan_paused", "device_swapped", "battery_low", "unknown",
            },
            WhoActs: {"customer", "technician", "carrier", "support", "none"},
            Priority: {"high", "medium", "low"},
            ItemKind: {"device", "incident"},
        }
        for enum, values in expected.items():
            with self.subTest(enum=enum.__name__):
                self.assertEqual({member.value for member in enum}, values)

    def test_at_must_be_an_aware_instant(self) -> None:
        with self.client() as client:
            invalid = (
                None, "", "yesterday", "2026-10-04", "2026-10-04T14:17:20",
                "2026-10-04T25:00:00Z", "2026-10-04T14:17:20+01:60",
            )
            for route in (f"/devices/{TRACKER}/status", "/triage"):
                for value in invalid:
                    with self.subTest(route=route, at=value):
                        response = client.get(route, params={} if value is None else {"at": value})
                        self.assertEqual(response.status_code, 400, response.text)
                        self.assertTrue(response.headers["content-type"].startswith("application/json"))
            for offset, utc_hour in (("-04:00", "05"), ("-05:00", "06")):
                response = client.get("/triage", params={"at": f"2026-11-01T01:30:00{offset}"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["at"], f"2026-11-01T{utc_hour}:30:00Z")

    def test_ingest_rejects_bad_json_and_envelopes_with_400(self) -> None:
        with self.client() as client:
            invalid_bodies = (
                b"", b'{"events":[', b"null", b"[]", b"42", b"{}",
                b'{"events":null}', b'{"events":{}}', b'{"events":false}', b'{"events":[NaN]}',
            )
            for content in invalid_bodies:
                with self.subTest(content=content):
                    response = client.post("/ingest", content=content, headers={"content-type": "application/json"})
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertTrue(response.headers["content-type"].startswith("application/json"))
            too_many = client.post("/ingest", json={"events": [None] * 5001})
            self.assertEqual(too_many.status_code, 400, too_many.text)

    def test_ingest_accepts_empty_mixed_and_max_size_lists(self) -> None:
        event = {
            "event_id": "e90000002", "type": "position", "serial": TRACKER, "device_time": AT,
            "received_at": AT, "payload": {"lat": 43.6, "lng": -79.6, "speed_kmh": 5, "ignition": True},
        }
        future_kind = {"type": "unfamiliar", "received_at": AT, "event_id": "e90000003"}
        with self.client() as client:
            for events, accepted in (([], 0), ([event, False, {}, future_kind, None], 2), ([None] * 5000, 0)):
                with self.subTest(size=len(events)):
                    response = client.post("/ingest", json={"events": events})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json(), {"accepted": accepted})
                    self.assertIs(type(response.json()["accepted"]), int)

    def test_missing_or_invalid_configuration_prevents_startup(self) -> None:
        for contents in (None, "{", "{}"):
            with self.subTest(contents=contents):
                path = self.workspace / "bad-rules.json"
                if contents is not None:
                    path.write_text(contents, encoding="utf-8")
                app = create_app(data_dir=self.data_dir, config_path=path)
                with self.assertRaises(ValueError):
                    with TestClient(app):
                        self.fail("Invalid rules reached the serving state")
                self.assertFalse(hasattr(app.state, "runtime"))

    def test_missing_or_invalid_required_csv_prevents_startup(self) -> None:
        for contents in (None, "date,depot,low_c,high_c\ninvalid-date,MSS,6,17\n"):
            with self.subTest(contents=contents):
                path = self.data_dir / "weather.csv"
                if contents is None:
                    path.unlink()
                else:
                    path.write_text(contents, encoding="utf-8")
                app = create_app(data_dir=self.data_dir, config_path=RULES)
                with self.assertRaises(ValueError):
                    with TestClient(app):
                        self.fail("Invalid references reached the serving state")
                self.assertFalse(hasattr(app.state, "runtime"))

    def test_lifespan_ignores_telemetry_and_recreates_store(self) -> None:
        telemetry = (self.data_dir / "telemetry").resolve()
        telemetry.mkdir()
        (telemetry / "2026-10-04.jsonl").write_text("not a telemetry event\n", encoding="utf-8")
        attempted_access = []

        def guard(original):
            def checked(*args, **kwargs):
                path = args[0] if args else kwargs.get("file", kwargs.get("path"))
                if isinstance(path, (str, bytes, os.PathLike)):
                    absolute = Path(os.fsdecode(path)).resolve()
                    if absolute.is_relative_to(telemetry):
                        attempted_access.append(absolute)
                        self.fail(f"Runtime attempted to open or scan replay telemetry at {absolute}")
                return original(*args, **kwargs)

            return checked

        with ExitStack() as stack:
            for module, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "scandir"), (os, "listdir")):
                stack.enter_context(patch.object(module, name, guard(getattr(module, name))))
            app = create_app(data_dir=self.data_dir, config_path=RULES)
            self.assertFalse(hasattr(app.state, "runtime"))
            unstarted_client = TestClient(app)
            self.addCleanup(unstarted_client.close)
            self.assertEqual(unstarted_client.get("/health").status_code, 503)
            with TestClient(app) as client:
                original_store = app.state.runtime.store
                event = {
                    "event_id": "lifespan-probe", "type": "ignition_off", "serial": TRACKER,
                    "device_time": AT, "received_at": AT, "payload": {},
                }
                self.assertEqual(client.post("/ingest", json={"events": [event]}).json(), {"accepted": 1})
                self.assertEqual(original_store.counts().messages, 1)
                self.assertEqual(client.get("/health").status_code, 200)
            self.assertFalse(hasattr(app.state, "runtime"))
            with self.assertRaises(sqlite3.ProgrammingError):
                original_store.counts()
            with TestClient(app) as client:
                fresh_store = app.state.runtime.store
                self.assertIsNot(fresh_store, original_store)
                self.assertEqual(fresh_store.counts().messages, 0)
                response = client.get(f"/devices/{TRACKER}/status", params={"at": AT})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIsNone(response.json()["last_heard_at"])
                self.assertEqual(response.json()["evidence"], [])
        self.assertEqual(attempted_access, [])


if __name__ == "__main__":
    unittest.main()
