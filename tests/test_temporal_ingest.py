import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from quiet_fleet.api import create_app
from quiet_fleet.normalize import InvalidEvent, normalize_event
from quiet_fleet.projection import project_device
from quiet_fleet.store import open_store
from quiet_fleet.time_utils import parse_iso_instant, to_epoch_us
from test_http_foundation import TRACKER, write_references


def clock(hms):
    return f"2026-10-04T{hms}Z"


def instant(hms):
    return to_epoch_us(parse_iso_instant(clock(hms)))


def frame(event_id, kind, observed, received=None, *, serial=TRACKER, payload=None):
    return {
        "event_id": event_id,
        "type": kind,
        "serial": serial,
        "device_time": clock(observed),
        "received_at": clock(received or observed),
        "payload": {} if payload is None else payload,
    }


def normalize(event, tolerance=0):
    normalized = normalize_event(event, clock_ahead_tolerance_seconds=tolerance)
    assert normalized is not None
    return normalized


def facts(store, hms, serial=TRACKER):
    cutoff = instant(hms)
    return project_device(cutoff, store.snapshot(cutoff, serial))


class TemporalIngestTest(unittest.TestCase):
    def setUp(self):
        workspace = Path(self.enterContext(tempfile.TemporaryDirectory()))
        data = workspace / "references"
        write_references(data)
        self.app = create_app(data_dir=data)
        self.client = self.enterContext(TestClient(self.app))
        self.store = self.app.state.runtime.store

    def post(self, *events):
        response = self.client.post("/ingest", json={"events": events})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIs(type(response.json()["accepted"]), int)
        return response.json()["accepted"]

    def status(self, hms):
        response = self.client.get(f"/devices/{TRACKER}/status", params={"at": clock(hms)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_repeating_the_batch_and_later_alias_do_not_change_domain_responses(self):
        payload = {"ignition": True, "lat": 43.0, "lng": -79.0, "speed_kmh": 12}
        event = frame("first-position", "position", "10:00:00", "10:00:02", payload=payload)
        self.assertEqual(self.post(event), 1)
        original = self.status("10:30:00")
        probe = self.client.get("/triage", params={"at": clock("10:30:00")}).json()
        counts = self.store.counts()
        self.assertEqual(self.post(event), 1)
        self.assertEqual(self.store.counts(), counts)
        alias = event | {
            "event_id": "later-retry", "device_time": "2026-10-04T06:00:00-04:00",
            "received_at": clock("10:20:00"), "payload": dict(reversed(list(payload.items()))),
        }
        self.assertEqual(self.post(alias), 1)
        self.assertEqual(self.status("10:30:00"), original)
        self.assertEqual(self.client.get("/triage", params={"at": clock("10:30:00")}).json(), probe)
        self.assertEqual(original["last_heard_at"], clock("10:00:02"))
        self.assertEqual(original["evidence"], ["first-position"])
        self.assertEqual(len(facts(self.store, "10:30:00").observations), 1)
        self.assertEqual(self.store.counts().original_ids, 2)
        self.assertEqual(
            tuple(row.event_id for row in self.store.receipts_for("first-position", instant("10:19:59"))),
            ("first-position",),
        )
        self.assertEqual(
            tuple(row.event_id for row in self.store.receipts_for("first-position", instant("10:20:00"))),
            ("first-position", "later-retry"),
        )
        self.assertEqual(self.post(event | {"received_at": clock("10:25:00")}), 1)
        self.assertEqual(self.status("10:30:00"), original)
        self.assertEqual(self.store.counts().receipts, 3)

    def test_earlier_received_backfill_can_add_retrospective_evidence(self):
        late = frame("later-alias", "ignition_off", "11:00:00", "11:30:00")
        self.post(late)
        self.assertEqual(self.status("11:20:00")["evidence"], [])
        self.post(late | {"event_id": "earlier-alias", "received_at": clock("11:10:00")})
        self.assertEqual(self.status("11:09:59.999999")["evidence"], [])
        self.assertEqual(self.status("11:10:00")["evidence"], ["earlier-alias"])
        self.assertEqual(self.status("11:30:00")["last_heard_at"], clock("11:10:00"))

    def test_out_of_order_ignition_uses_observation_order_and_receipt_cutoff(self):
        off = frame("newer-off", "ignition_off", "10:10:00", "10:10:01")
        on = frame("older-on", "ignition_on", "10:00:00", "10:20:00", payload={"vin": "VIN-FOUNDATION"})
        self.post(off, on)
        self.assertEqual(self.status("10:10:00.999999")["evidence"], [])
        self.assertEqual(self.status("10:10:01")["evidence"], ["newer-off"])
        self.assertEqual(self.status("10:19:59")["evidence"], ["newer-off"])
        status = self.status("10:20:00")
        self.assertEqual(status["last_heard_at"], clock("10:20:00"))
        self.assertIn("older-on", status["evidence"])
        self.assertIn("newer-off", status["evidence"])
        projected = facts(self.store, "10:20:01")
        self.assertEqual([event.event_id for event in projected.observations], ["older-on", "newer-off"])
        self.assertIs(projected.ignition_on, False)
        self.assertEqual(projected.ignition_evidence.event_id, "newer-off")
        self.assertEqual(projected.freshest_measurement.event_id, "newer-off")
        with self.assertRaises(FrozenInstanceError):
            projected.ignition_on = True

    def test_explicit_ignition_wins_over_position_at_the_same_observation_time(self):
        self.post(
            frame("explicit-off", "ignition_off", "10:10:00", "10:10:01"),
            frame("same-time-position", "position", "10:10:00", "10:10:02",
                  payload={"lat": 43, "lng": -79, "speed_kmh": 0, "ignition": True}),
        )
        projected = facts(self.store, "10:10:02")
        self.assertIs(projected.ignition_on, False)
        self.assertEqual(projected.ignition_since.event_id, "explicit-off")

    def test_only_newer_visible_recording_and_power_restore_close_fault_facts(self):
        camera = "C-TEST"
        self.post(
            frame("storage-error", "camera_status", "10:05:00", "10:05:02", serial=camera,
                  payload={"status": "storage_error"}),
            frame("old-recording", "camera_status", "10:02:00", "10:07:00", serial=camera,
                  payload={"status": "recording"}),
            frame("boot", "camera_status", "10:06:00", "10:07:00", serial=camera, payload={"status": "booting"}),
            frame("restored-video", "camera_status", "10:08:00", "10:10:00", serial=camera,
                  payload={"status": "recording"}),
            frame("disconnect", "power_disconnect", "10:05:00", "10:05:02"),
            frame("old-restore", "power_restore", "10:02:00", "10:07:00"),
            frame("true-restore", "power_restore", "10:08:00", "10:10:00"),
        )
        camera_facts = facts(self.store, "10:09:59", camera)
        self.assertEqual(camera_facts.camera_status, "booting")
        self.assertEqual(camera_facts.camera_storage_error.event_id, "storage-error")
        self.assertIsNone(facts(self.store, "10:10:00", camera).camera_storage_error)
        self.assertEqual(facts(self.store, "10:09:59").power_disconnect.event_id, "disconnect")
        self.assertIsNone(facts(self.store, "10:10:00").power_disconnect)

    def test_platform_only_and_unknown_kind_never_report_contact(self):
        reboot = frame("reboot", "command", "12:00:00", "12:01:00",
                       payload={"command": "reboot", "issued_by": "support"})
        retry = reboot | {"event_id": "reboot-retry", "received_at": clock("12:05:00")}
        plan = frame("stream-plan", "plan_change", "12:02:00", "12:08:00",
                     payload={"plan": "data", "status": "ended", "reason": "request"})
        unknown = frame("unused", "unknown_protocol", "12:05:00")
        self.assertEqual(self.post(reboot, reboot, retry, unknown, plan), 5)
        projected = facts(self.store, "12:07:59")
        self.assertEqual([event.event_id for event in projected.reboot_commands], ["reboot"])
        self.assertIsNone(projected.plan_status)
        self.assertEqual(facts(self.store, "12:08:00").plan_status, "ended")
        self.assertEqual(self.status("12:07:59")["evidence"], [])
        inactive = self.status("12:09:00")
        self.assertIsNone(inactive["last_heard_at"])
        self.assertEqual(inactive["likely_cause"], "plan_paused")
        self.assertEqual(inactive["evidence"], ["stream-plan"])
        self.assertEqual(self.store.counts().messages, 2)

    def test_clock_ahead_receipt_stays_uncertain_after_a_later_retry(self):
        first = frame("bad-clock", "ignition_on", "13:10:00", "13:00:00", payload={"vin": "VIN-FOUNDATION"})
        self.assertEqual(self.post(first), 1)
        self.assertEqual(self.status("12:59:59")["evidence"], [])
        self.assertEqual(self.status("13:00:00")["last_heard_at"], clock("13:00:00"))
        self.assertEqual(self.post(first | {"event_id": "late-retry", "received_at": clock("13:11:00")}), 1)
        projected = facts(self.store, "13:12:00")
        self.assertEqual(projected.last_contact.time_quality, "clock_ahead")
        self.assertEqual(projected.last_contact.event_id, "bad-clock")
        self.assertEqual(projected.observations, ())
        self.assertIsNone(projected.ignition_on)
        self.assertIsNone(projected.freshest_measurement)

    def test_independent_observation_cutoff_even_with_permitted_clock_tolerance(self):
        event = frame("precise-off", "ignition_off", "14:00:00.000002", "14:00:00.000001")
        self.store.write_batch([normalize(event, tolerance=1)])
        self.assertIsNone(facts(self.store, "14:00:00").last_contact)
        first = facts(self.store, "14:00:00.000001")
        self.assertEqual(first.last_contact.event_id, "precise-off")
        self.assertEqual(first.observations, ())
        self.assertIs(facts(self.store, "14:00:00.000002").ignition_on, False)
        self.assertIs(facts(self.store, "14:00:00.000003").ignition_on, False)

    def test_conflicting_id_invalid_neighbors_and_programming_errors_are_distinct(self):
        good = frame("stable-id", "ignition_off", "10:00:00")
        bad = frame("bad-time", "ignition_off", "10:01:00") | {"device_time": True}
        conflict = good | {"type": "power_disconnect"}
        later = frame("later-good", "ignition_off", "10:02:00")
        self.assertEqual(self.post(good, conflict, bad, later), 2)
        self.assertEqual(self.store.counts().conflicts, 1)
        self.assertEqual(self.store.counts().messages, 2)
        self.assertEqual(facts(self.store, "10:02:00").observations[0].kind, "ignition_off")
        with patch("quiet_fleet.api.normalize_event", side_effect=RuntimeError("unexpected bug")):
            with self.assertRaisesRegex(RuntimeError, "unexpected bug"):
                self.client.post("/ingest", json={"events": [later]})


class StoreAndNormalizationTest(unittest.TestCase):
    def test_legacy_seconds_reject_invalid_numeric_inputs_and_preserve_raw_time(self):
        seconds = instant("10:00:00") // 1_000_000
        event = frame("legacy-tag", "check_in", "10:00:00", serial="A-TEST",
                      payload={"battery_pct": 60, "lat": 44, "lng": -79, "temp_c": 10})
        payload = event | {"device_time": seconds}
        legacy = normalize(payload)
        self.assertEqual(legacy.observed_us, instant("10:00:00"))
        self.assertEqual(json.loads(legacy.raw_device_time_json), seconds)
        self.assertEqual(legacy.fingerprint, normalize(event).fingerprint)
        for value in (True, float("nan"), float("inf"), seconds * 1000, 7, "2026-10-04T10:00:00", []):
            with self.subTest(value=value), self.assertRaises(InvalidEvent):
                normalize(event | {"device_time": value})
        with self.assertRaises(InvalidEvent):
            normalize(frame("other-clock", "ignition_off", "10:00:00") | {"device_time": seconds})

    def test_opaque_bx_retains_original_ids_and_raw_frame_without_serial_or_clock(self):
        bx = {"event_id": "bx-id", "received_at": clock("09:00:00"), "type": "bx_raw", "raw": '{"t":"1A"}'}
        bx_alias = bx | {"event_id": "bx-retry", "received_at": clock("09:05:00")}
        with open_store() as store:
            self.assertEqual(store.write_batch([normalize(bx), normalize(bx_alias)]).accepted, 2)
            self.assertEqual(store.counts().messages, 1)
            self.assertEqual(store.snapshot(instant("08:59:59"), None), ())
            opaque, = store.snapshot(instant("09:00:00"), None)
            self.assertIsNone(opaque.observed_us)
            self.assertEqual(opaque.time_quality, "undecoded")
            self.assertEqual(json.loads(opaque.payload_json), {"raw": bx["raw"]})
            self.assertEqual([receipt.event_id for receipt in store.receipts_for("bx-id", instant("09:08:00"))],
                             ["bx-id", "bx-retry"])

    def test_new_id_with_equal_receipt_uses_stable_id_and_keeps_alias_raw_device_time(self):
        original = frame("z-alias", "ignition_off", "10:00:00", "10:00:03")
        alias = original | {"event_id": "a-alias", "device_time": "2026-10-04T06:00:00-04:00"}
        with open_store() as one, open_store() as two:
            events = [normalize(original), normalize(alias)]
            one.write_batch(events)
            two.write_batch(list(reversed(events)))
            cutoff = instant("10:01:00")
            self.assertEqual(one.snapshot(cutoff, TRACKER), two.snapshot(cutoff, TRACKER))
            self.assertEqual(one.snapshot(cutoff, TRACKER)[0].event_id, "a-alias")
            receipts = one.receipts_for("a-alias", cutoff)
            self.assertEqual([json.loads(receipt.raw_device_time_json) for receipt in receipts],
                             [alias["device_time"], original["device_time"]])

    def test_snapshot_during_write_waits_for_complete_batch(self):
        first = normalize(frame("first", "ignition_off", "10:00:00"))
        second = normalize(frame("second", "ignition_off", "10:00:01"))
        writer_paused = Event()
        reader_started = Event()
        resume = Event()

        class PausingBatch(list):
            def __iter__(self):
                yield first
                writer_paused.set()
                if not resume.wait(5):
                    raise RuntimeError("Test failed to release writer")
                yield second

        with open_store() as store, ThreadPoolExecutor(max_workers=2) as worker:
            cutoff = instant("10:01:00")

            def read():
                reader_started.set()
                return store.snapshot(cutoff, TRACKER)

            writer = worker.submit(store.write_batch, PausingBatch([first, second]))
            try:
                self.assertTrue(writer_paused.wait(3))
                reader = worker.submit(read)
                self.assertTrue(reader_started.wait(3))
                with self.assertRaises(TimeoutError):
                    reader.result(timeout=0.05)
            finally:
                resume.set()
            self.assertEqual(writer.result(timeout=3).accepted, 2)
            self.assertEqual([event.event_id for event in reader.result(timeout=3)], ["first", "second"])

    def test_unexpected_batch_failure_rolls_back_its_first_write(self):
        first = normalize(frame("discarded", "ignition_off", "10:00:00"))

        class BrokenBatch(list):
            def __iter__(self):
                yield first
                raise RuntimeError("test rollback")

        with open_store() as store:
            with self.assertRaisesRegex(RuntimeError, "test rollback"):
                store.write_batch(BrokenBatch([first]))
            self.assertEqual(store.counts().messages, 0)
            self.assertEqual(store.counts().original_ids, 0)
            self.assertEqual(store.counts().receipts, 0)
            self.assertEqual(store.write_batch([first]).inserted, 1)


if __name__ == "__main__":
    unittest.main()
