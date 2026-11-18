import csv
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from quiet_fleet.api import create_app
from test_http_foundation import ASSET, RULES, STOCK_TRACKER, TRACKER, write_references


BASE = datetime(2026, 10, 4, 10, tzinfo=UTC)
VIN = "1FTBW1X80RKA12345"
OTHER_ASSET = "V-902"
OTHER_VIN = "1FTBW1X80RKA12346"
TRAILER = "TR-901"
CAMERA = "C-90001"
OTHER_CAMERA = "C-90002"
OTHER_TRACKER = "T-90003"
TAG = "A-90001"


def instant(offset: int) -> str:
    return (BASE + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


def event(
    event_id: str, serial: str, kind: str, observed: int, payload: dict,
    *, received: int | None = None, numeric_clock: bool = False,
) -> dict:
    clock = int((BASE + timedelta(seconds=observed)).timestamp()) if numeric_clock else instant(observed)
    return {
        "event_id": event_id,
        "serial": serial,
        "type": kind,
        "received_at": instant(observed if received is None else received),
        "device_time": clock,
        "payload": payload,
    }


def position(event_id: str, serial: str, observed: int, *, received: int | None = None) -> dict:
    return event(event_id, serial, "position", observed, {
        "lat": 43.6, "lng": -79.6, "speed_kmh": 0, "ignition": True,
    }, received=received)


class ReportingFixture(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data = root / "data"
        write_references(self.data)
        self.append_csv("assets", (OTHER_ASSET, "van", "MSS", "service", "Test Van", "2024", OTHER_VIN, "active"))
        self.append_csv("assets", (TRAILER, "trailer", "MSS", "service", "Test Trailer", "2024", "", "active"))
        self.add_device(CAMERA, "C", ASSET)
        self.add_device(OTHER_CAMERA, "C", OTHER_ASSET)
        self.add_device(TAG, "A", TRAILER)

    def append_csv(self, table: str, row: tuple[str, ...]) -> None:
        with (self.data / f"{table}.csv").open("a", newline="", encoding="utf-8") as destination:
            csv.writer(destination).writerow(row)

    def add_device(self, serial: str, family: str, asset: str, *, installed: str = "2024-01-01") -> None:
        self.append_csv("devices", (serial, family, f"{family}-series", "1.0.0", "Test Carrier", asset, "active", installed))

    def client(self) -> TestClient:
        return self.enterContext(TestClient(create_app(data_dir=self.data, config_path=RULES)))

    def ingest(self, client: TestClient, *events: dict) -> None:
        response = client.post("/ingest", json={"events": list(events)})
        self.assertEqual((response.status_code, response.json()), (200, {"accepted": len(events)}))

    def status(self, client: TestClient, serial: str, at: int, state: str, cause: str = "unknown") -> dict:
        response = client.get(f"/devices/{serial}/status", params={"at": instant(at)})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["state"], body["likely_cause"]), (state, cause), body)
        return body


class NormalReportingTest(ReportingFixture):
    def test_zero_speed_driving_deadline_and_buffered_contact(self) -> None:
        client = self.client()
        self.ingest(client, position("at-zero-speed", TRACKER, 0, received=2))
        before_receipt = self.status(client, TRACKER, 1, "unknown")
        self.assertIsNone(before_receipt["last_heard_at"])
        for at in (2, 360):
            with self.subTest(at=at):
                reporting = self.status(client, TRACKER, at, "reporting", "none")
                self.assertIn("at-zero-speed", reporting["evidence"])
                self.assertEqual(reporting["last_heard_at"], instant(2))
        self.status(client, TRACKER, 361, "unknown")

        self.ingest(client, position("buffer-draining", TRACKER, 10, received=1000))
        backfilled = self.status(client, TRACKER, 1000, "unknown")
        self.assertEqual(backfilled["last_heard_at"], instant(1000))
        self.assertIn("buffer-draining", backfilled["evidence"])
        self.assertEqual(self.status(client, TRACKER, 360, "reporting", "none"), reporting)

    def test_parked_heartbeat_is_late_only_after_270_minutes(self) -> None:
        client = self.client()
        self.ingest(client,
            event("park", TRACKER, "ignition_off", 0, {}),
            event("parked-heartbeat", TRACKER, "heartbeat", 2, {"battery_v": 12.4, "signal": 4, "vin": VIN}),
        )
        for age in (269 * 60 + 59, 270 * 60):
            with self.subTest(age=age):
                normal = self.status(client, TRACKER, 2 + age, "quiet_expected", "parked_normal")
                self.assertTrue({"park", "parked-heartbeat"}.issubset(normal["evidence"]))
        self.status(client, TRACKER, 2 + 270 * 60 + 1, "unknown")

    def test_future_job_does_not_imply_tracker_ignition(self) -> None:
        client = self.client()
        self.ingest(client, event("ignition-absent", TRACKER, "heartbeat", 0, {
            "battery_v": 12.4, "signal": 4, "vin": VIN,
        }))
        # The fixture's 11:00 UTC job is still an hour away.
        unknown = self.status(client, TRACKER, 0, "unknown")
        self.assertIn("ignition-absent", unknown["evidence"])

    def test_camera_sleep_transition_uses_only_same_asset_tracker(self) -> None:
        self.add_device(OTHER_TRACKER, "T", OTHER_ASSET)
        client = self.client()
        self.ingest(client,
            event("paired-off", TRACKER, "ignition_off", 0, {}),
            event("post-off-recording", CAMERA, "camera_status", 10, {"status": "recording"}),
            position("unrelated-drive", OTHER_TRACKER, 899),
            event("camera-sleeps", CAMERA, "camera_status", 901, {"status": "sleeping"}),
        )
        self.status(client, CAMERA, 610, "reporting", "none")
        self.status(client, CAMERA, 611, "unknown")
        self.status(client, CAMERA, 899, "unknown")
        sleep_inferred = self.status(client, CAMERA, 900, "quiet_expected", "sleeping_by_design")
        self.assertIn("paired-off", sleep_inferred["evidence"])
        self.assertNotIn("camera-sleeps", sleep_inferred["evidence"])
        asleep = self.status(client, CAMERA, 901, "quiet_expected", "sleeping_by_design")
        self.assertTrue({"paired-off", "camera-sleeps"}.issubset(asleep["evidence"]))
        self.assertNotIn("unrelated-drive", asleep["evidence"])
        self.status(client, OTHER_CAMERA, 900, "unknown")

    def test_camera_wake_grace_tracks_transition_not_repeated_positions(self) -> None:
        client = self.client()
        self.ingest(client,
            event("old-off", TRACKER, "ignition_off", 0, {}),
            event("old-sleep", CAMERA, "camera_status", 900, {"status": "sleeping"}),
            event("new-ignition", TRACKER, "ignition_on", 1200, {"vin": VIN}),
            event("camera-boot", CAMERA, "camera_status", 1201, {"status": "booting"}),
            position("still-ignition-on", TRACKER, 1259),
            event("new-recording", CAMERA, "camera_status", 1262, {"status": "recording"}),
        )
        self.status(client, CAMERA, 1199, "quiet_expected", "sleeping_by_design")
        grace = self.status(client, CAMERA, 1260, "unknown")
        self.assertRegex(" ".join(grace["reasons"]).lower(), r"wake|grace")
        overdue = self.status(client, CAMERA, 1261, "unknown")
        self.assertIn("new-ignition", overdue["evidence"])
        self.assertNotIn("new-recording", overdue["evidence"])
        self.assertNotEqual(grace["reasons"], overdue["reasons"])
        recording = self.status(client, CAMERA, 1262, "reporting", "none")
        self.assertIn("new-recording", recording["evidence"])

    def test_camera_missing_or_competing_trackers_leaves_sleep_uncertain(self) -> None:
        self.add_device(OTHER_TRACKER, "T", ASSET)
        client = self.client()
        self.ingest(client,
            event("primary-off", TRACKER, "ignition_off", 0, {}),
            event("primary-vin", TRACKER, "heartbeat", 1, {"battery_v": 12.4, "signal": 4, "vin": VIN}),
            event("competing-vin", OTHER_TRACKER, "ignition_on", 1, {"vin": VIN}),
            event("ambiguous-sleep", CAMERA, "camera_status", 920, {"status": "sleeping"}),
            event("unpaired-sleep", OTHER_CAMERA, "camera_status", 920, {"status": "sleeping"}),
            event("ambiguous-recording", CAMERA, "camera_status", 950, {"status": "recording"}),
            event("unpaired-recording", OTHER_CAMERA, "camera_status", 950, {"status": "recording"}),
        )
        for serial in (CAMERA, OTHER_CAMERA):
            with self.subTest(serial=serial):
                self.status(client, serial, 920, "unknown")
                self.status(client, serial, 950, "reporting", "none")

    def test_explicit_faults_survive_backup_or_boot(self) -> None:
        client = self.client()
        self.ingest(client,
            event("parked-off", TRACKER, "ignition_off", 0, {}),
            event("disconnect", TRACKER, "power_disconnect", 10, {}),
            position("backup-position", TRACKER, 20),
            event("storage-error", CAMERA, "camera_status", 25, {"status": "storage_error"}),
            event("boot-only", CAMERA, "camera_status", 30, {"status": "booting"}),
            event("old-delayed-recording", CAMERA, "camera_status", 24, {"status": "recording"}, received=35),
        )
        tracker = self.status(client, TRACKER, 35, "needs_action", "power_loss")
        self.assertIn("disconnect", tracker["evidence"])
        camera = self.status(client, CAMERA, 35, "needs_action", "camera_fault")
        self.assertIn("storage-error", camera["evidence"])

    def test_daily_a_numeric_clock_jitter_and_prolonged_gap(self) -> None:
        client = self.client()
        empty = self.status(client, TAG, 0, "unknown")
        self.assertEqual(empty["evidence"], [])
        self.ingest(client, event("a-epoch", TAG, "check_in", 0, {
            "lat": 43.6, "lng": -79.6, "battery_pct": 72, "temp_c": 12,
        }, received=20, numeric_clock=True))
        for age in (24 * 3600, 26 * 3600):
            with self.subTest(age=age):
                healthy = self.status(client, TAG, age, "reporting", "none")
                self.assertEqual(healthy["last_heard_at"], instant(20))
                self.assertIn("a-epoch", healthy["evidence"])
        first_miss = self.status(client, TAG, 26 * 3600 + 1, "unknown")
        still_first = self.status(client, TAG, 50 * 3600, "unknown")
        prolonged = self.status(client, TAG, 50 * 3600 + 1, "unknown")
        for body in (first_miss, still_first):
            self.assertRegex(" ".join(body["reasons"]).lower(), r"missed|overdue")
        self.assertRegex(" ".join(prolonged["reasons"]).lower(), r"prolonged|multiple|more than one|two|second|\b2\b")

    def test_removed_tracker_works_historically_before_replacement_receipt(self) -> None:
        devices_path = self.data / "devices.csv"
        with devices_path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            fields = reader.fieldnames
            devices = list(reader)
        for device in devices:
            if device["serial"] == TRACKER:
                device["status"] = "removed"
        with devices_path.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=fields)
            writer.writeheader()
            writer.writerows(devices)
        self.add_device(OTHER_TRACKER, "T", ASSET, installed="2026-10-05")
        client = self.client()
        replacement_time = 24 * 3600
        self.ingest(client,
            event("old-tracker-off", TRACKER, "ignition_off", 0, {}),
            event("historical-sleep", CAMERA, "camera_status", 900, {"status": "sleeping"}),
            event("former-tracker-heartbeat", TRACKER, "heartbeat", replacement_time - 20, {
                "battery_v": 12.4, "signal": 4, "vin": VIN,
            }),
            event("replacement-seen", OTHER_TRACKER, "ignition_on", replacement_time, {"vin": VIN},
                  received=replacement_time + 10),
        )
        preinstall = self.status(client, OTHER_TRACKER, 900, "unknown")
        self.assertIsNone(preinstall["asset_id"])
        historic = self.status(client, CAMERA, 900, "quiet_expected", "sleeping_by_design")
        self.assertIn("old-tracker-off", historic["evidence"])
        self.assertNotIn("replacement-seen", historic["evidence"])
        self.status(client, CAMERA, replacement_time + 9, "quiet_expected", "sleeping_by_design")
        resumed = self.status(client, CAMERA, replacement_time + 10, "unknown")
        self.assertIn("replacement-seen", resumed["evidence"])
        self.assertRegex(" ".join(resumed["reasons"]).lower(), r"wake|grace")

    def test_stock_tracker_uses_known_vin_only_after_receipt(self) -> None:
        client = self.client()
        self.ingest(client, event("stock-vin", STOCK_TRACKER, "heartbeat", 2, {
            "battery_v": 12.4, "signal": 4, "vin": VIN,
        }, received=10))
        earlier = self.status(client, STOCK_TRACKER, 9, "unknown")
        self.assertIsNone(earlier["asset_id"])
        self.assertEqual(earlier["evidence"], [])
        current = self.status(client, STOCK_TRACKER, 10, "needs_action", "device_swapped")
        self.assertEqual(current["asset_id"], ASSET)
        self.assertIn("stock-vin", current["evidence"])


if __name__ == "__main__":
    unittest.main()
