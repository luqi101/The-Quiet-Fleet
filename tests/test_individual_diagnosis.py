import csv
import json

from fastapi.testclient import TestClient

import test_normal_reporting as fixture
from quiet_fleet.api import create_app
from quiet_fleet.asset_context import load_device_context
from quiet_fleet.diagnosis import assess_device
from quiet_fleet.models import WhoActs
from quiet_fleet.time_utils import parse_iso_instant, to_epoch_us


class IndividualDiagnosisTest(fixture.ReportingFixture):
    def assessment(self, client, serial, at):
        runtime = client.app.state.runtime
        now = parse_iso_instant(fixture.instant(at))
        context = load_device_context(
            runtime.store, runtime.references, runtime.references.devices[serial], to_epoch_us(now), runtime.rules,
        )
        return assess_device(now, runtime.rules, context)

    def test_external_power_episode_survives_backup_positions_until_later_restore(self):
        client = self.client()
        tracker = fixture.TRACKER
        event = fixture.event
        self.ingest(
            client, fixture.position("forklift-first-fix", tracker, 0),
            event("vehicle-voltage", tracker, "low_voltage", 10, {"volts": 9.1, "source": "vehicle_battery"}),
            event("cable-open", tracker, "power_disconnect", 30, {}),
            event("reserve-low", tracker, "low_voltage", 630, {"volts": 3.1, "source": "backup_battery"}),
            fixture.position("backup-location", tracker, 1100),
            event("stale-repair", tracker, "power_restore", 20, {}, received=1110),
            event("also-paused", tracker, "plan_change", 1115,
                  {"plan": "data", "status": "paused", "reason": "approval pending"}),
            event("external-back", tracker, "power_restore", 1120, {}, received=1130),
            fixture.position("after-repair", tracker, 1125),
            event("also-resumed", tracker, "plan_change", 1130,
                  {"plan": "data", "status": "active", "reason": "approved"}),
        )
        self.status(client, tracker, 10, "reporting", "none")
        fault = self.status(client, tracker, 1129, "needs_action", "power_loss")
        self.assertTrue({"cable-open", "reserve-low", "also-paused"}.issubset(fault["evidence"]))
        self.assertNotIn("external-back", fault["evidence"])
        self.assertEqual(self.assessment(client, tracker, 1129).owner, WhoActs.TECHNICIAN)
        self.status(client, tracker, 1130, "reporting", "none")

    def test_camera_escalates_after_two_unique_awake_tests_and_recovers_on_recording(self):
        client = self.client()
        camera, tracker = fixture.CAMERA, fixture.TRACKER
        event = fixture.event
        first = event("first-command", camera, "command", 100, {"command": "reboot", "issued_by": "support"})
        self.ingest(
            client, event("drive-start", tracker, "ignition_on", 0, {"vin": fixture.VIN}),
            event("storage-failure", camera, "camera_status", 50, {"status": "storage_error"}),
            first, first | {"event_id": "first-command-retry", "received_at": fixture.instant(130)},
            event("second-command", camera, "command", 800, {"command": "reboot", "issued_by": "support"}),
            event("boot-after-reboot", camera, "camera_status", 900, {"status": "booting"}),
            *[fixture.position(f"drive-{at}", tracker, at) for at in (300, 550, 780, 1000, 1240, 1390)],
            event("off-after-tests", tracker, "ignition_off", 1450, {}),
            event("sleep-isnt-repair", camera, "camera_status", 1470, {"status": "sleeping"}),
            event("recordings-return", camera, "camera_status", 1500, {"status": "recording"}, received=1510),
        )
        self.assertEqual(self.assessment(client, camera, 750).owner, WhoActs.SUPPORT)
        self.assertEqual(self.assessment(client, camera, 1399).owner, WhoActs.SUPPORT)
        escalated = self.assessment(client, camera, 1400)
        self.assertEqual(escalated.owner, WhoActs.TECHNICIAN)
        self.assertTrue({"storage-failure", "first-command", "second-command"}.issubset(escalated.status.evidence))
        self.assertNotIn("first-command-retry", escalated.status.evidence)
        parked = self.assessment(client, camera, 1510 - 1)
        self.assertEqual(parked.status.likely_cause.value, "camera_fault")
        queue = client.get("/triage", params={"at": fixture.instant(1509)}).json()
        item, = [item for item in queue["items"] if item["serials"] == [camera]]
        self.assertEqual(item["priority"], "high")  # The parked vehicle has imminent scheduled work.
        self.status(client, camera, 1510, "reporting", "none")
        self.ingest(client, event("new-storage-error", camera, "camera_status", 1600, {"status": "storage_error"}))
        new_episode = self.assessment(client, camera, 1600)
        self.assertEqual(new_episode.owner, WhoActs.SUPPORT)
        self.assertNotIn("second-command", new_episode.status.evidence)

    def test_ignition_off_interrupts_a_reboot_response_window(self):
        client = self.client()
        camera, tracker = fixture.CAMERA, fixture.TRACKER
        event = fixture.event
        command = {"command": "reboot", "issued_by": "support"}
        self.ingest(
            client,
            event("initial-ignition", tracker, "ignition_on", 0, {"vin": fixture.VIN}),
            event("persistent-storage", camera, "camera_status", 50, {"status": "storage_error"}),
            event("interrupted-command", camera, "command", 100, command),
            event("mid-check-off", tracker, "ignition_off", 400, {}),
            event("next-ignition", tracker, "ignition_on", 1000, {"vin": fixture.VIN}),
            event("completed-command", camera, "command", 1100, command),
            fixture.position("same-drive-position", tracker, 1690),
        )
        outcome = self.assessment(client, camera, 1700)
        self.assertEqual(outcome.status.likely_cause.value, "camera_fault")
        self.assertEqual(outcome.owner, WhoActs.SUPPORT)
        self.assertNotIn("interrupted-command", outcome.status.evidence)
        self.assertIn("completed-command", outcome.status.evidence)

    def test_awake_recording_gap_yields_to_streamed_plan_and_resumes_after_grace(self):
        client = self.client()
        camera, tracker = fixture.CAMERA, fixture.TRACKER
        event = fixture.event
        self.ingest(
            client, event("camera-route-start", tracker, "ignition_on", 0, {"vin": fixture.VIN}),
            event("camera-last-recording", camera, "camera_status", 60, {"status": "recording"}),
            fixture.position("camera-route-continuing", tracker, 640),
            event("pause-video", camera, "plan_change", 662, {"plan": "video", "status": "paused", "reason": "test"}),
            event("resume-video", camera, "plan_change", 700, {"plan": "video", "status": "active", "reason": "resolved"}),
            event("late-old-video-end", camera, "plan_change", 680,
                  {"plan": "video", "status": "ended", "reason": "old"}, received=720),
            event("unrelated-update", camera, "plan_change", 800,
                  {"plan": "maintenance", "status": "active", "reason": "separate plan"}),
            fixture.position("route-after-resume", tracker, 1290),
        )
        self.status(client, camera, 660, "reporting", "none")
        self.status(client, camera, 661, "needs_action", "camera_fault")
        self.status(client, camera, 699, "needs_action", "plan_paused")
        self.status(client, camera, 721, "unknown")
        self.status(client, camera, 1300, "unknown")
        self.status(client, camera, 1301, "needs_action", "camera_fault")

    def test_cold_local_date_does_not_override_battery_and_hysteresis(self):
        tag = fixture.TAG
        event = fixture.event
        self.append_csv("weather", ("2026-10-05", "MSS", "-14", "5"))
        self.append_csv("weather", ("2026-10-06", "MSS", "8", "17"))
        client = self.client()
        start = 12 * 3600

        def reading(name, offset, percent, received=None):
            return event(name, tag, "check_in", start + offset, {
                "lat": 43.6, "lng": -79.6, "battery_pct": percent, "temp_c": -12,
            }, received=received)

        self.ingest(client, reading("healthy-before-cold", 0, 65))
        # The first missed deadline is Oct 6 at 00:00 UTC and Oct 5 in Mississauga.
        self.status(client, tag, start + 26 * 3600, "reporting", "none")
        self.status(client, tag, start + 26 * 3600 + 1, "quiet_expected", "cold_weather")
        self.status(client, tag, start + 52 * 3600, "quiet_expected", "cold_weather")
        self.status(client, tag, start + 52 * 3600 + 1, "unknown")
        self.ingest(
            client, reading("depleted", 20, 10), reading("intermediate", 30, 15),
            reading("older-high-backfill", 10, 90, received=start + 40),
            reading("restored-threshold", 50, 20, received=start + 70),
        )
        self.status(client, tag, start + 20, "needs_action", "battery_low")
        self.status(client, tag, start + 26 * 3600 + 30, "reporting", "none")
        still_low = self.status(client, tag, start + 69, "needs_action", "battery_low")
        self.assertIn("depleted", still_low["evidence"])
        self.assertNotIn("restored-threshold", still_low["evidence"])
        self.status(client, tag, start + 70, "reporting", "none")
        self.ingest(client, reading("depleted-during-local-cold", 25 * 3600, 7))
        self.status(client, tag, start + 26 * 3600 + 30, "needs_action", "battery_low")

    def test_confirmed_downtime_is_local_date_scoped_and_direct_power_wins(self):
        config = json.loads(fixture.RULES.read_text())
        config["operational_assumptions"]["seasonal_downtime_suppression_enabled"]["value"] = True
        config["site_policy"] = {"downtime": [{
            "asset_ids": [fixture.ASSET], "depot": "MSS",
            "start_local": "2026-10-05", "end_local": "2026-10-06",
            "provenance": "Synthetic confirmed operations record",
        }]}
        rules = self.data / "approved-rules.json"
        rules.write_text(json.dumps(config), encoding="utf-8")
        client = self.enterContext(TestClient(create_app(data_dir=self.data, config_path=rules)))
        tracker = fixture.TRACKER
        cutoff = 18 * 3600
        self.status(client, tracker, cutoff - 1, "unknown")
        self.status(client, tracker, cutoff, "quiet_expected", "planned_downtime")
        self.status(client, tracker, cutoff + 24 * 3600, "unknown")
        self.ingest(client, fixture.event("during-approved-stop", tracker, "power_disconnect", cutoff + 1, {}))
        diagnosis = self.status(client, tracker, cutoff + 1, "needs_action", "power_loss")
        self.assertGreaterEqual(len(diagnosis["reasons"]), 2)

    def test_live_competing_vin_routes_to_support_and_completed_removal_is_quiet(self):
        devices_path = self.data / "devices.csv"
        with devices_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            devices = list(reader)
        for device in devices:
            if device["serial"] == fixture.TRACKER:
                device["status"] = "removed"
        with devices_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(devices)
        self.add_device(fixture.OTHER_TRACKER, "T", fixture.ASSET)
        client = self.client()
        old, new = fixture.TRACKER, fixture.OTHER_TRACKER
        event = fixture.event
        self.ingest(
            client,
            event("legacy-vin", old, "ignition_on", 0, {"vin": fixture.VIN}),
            fixture.position("legacy-fix", old, 10),
            event("successor-vin", new, "ignition_on", 100, {"vin": fixture.VIN}, received=110),
            fixture.position("old-tracker-still-live", old, 130),
        )
        self.status(client, old, 109, "reporting", "none")
        self.status(client, old, 110, "unknown")
        self.assertEqual(self.assessment(client, old, 110).owner, WhoActs.NONE)
        conflict = self.status(client, old, 130, "needs_action", "device_swapped")
        self.assertIn("successor-vin", conflict["evidence"])
        self.assertEqual(self.assessment(client, old, 130).owner, WhoActs.SUPPORT)

    def test_stale_backfill_explains_delivery_only_after_its_receipt(self):
        client = self.client()
        tracker = fixture.TRACKER
        self.ingest(
            client, fixture.position("current-drive-anchor", tracker, 0),
            fixture.position("buffered-location", tracker, 200, received=800),
            fixture.position("first-current-fix", tracker, 950),
        )
        earlier = self.status(client, tracker, 799, "needs_action", "unknown")
        self.assertNotIn("buffered-location", earlier["evidence"])
        restored_transport = self.status(client, tracker, 800, "needs_action", "unknown")
        self.assertIn("buffered-location", restored_transport["evidence"])
        self.assertRegex(" ".join(restored_transport["reasons"]).lower(), r"buffer|backfill|delayed")
        self.assertEqual(restored_transport["last_heard_at"], fixture.instant(800))
        self.status(client, tracker, 950, "reporting", "none")

    def test_weak_signal_and_observed_buffer_history_support_a_bounded_gap(self):
        client = self.client()
        tracker = fixture.TRACKER
        self.ingest(
            client, fixture.position("older-buffered-position", tracker, 10, received=200),
            fixture.event("weak-modem", tracker, "heartbeat", 260, {"battery_v": 12, "signal": 1, "vin": fixture.VIN}),
            fixture.position("route-current-position", tracker, 300),
        )
        response = client.get(f"/devices/{tracker}/status", params={"at": fixture.instant(661)}).json()
        self.assertEqual(response["likely_cause"], "coverage_gap", response)
        self.assertTrue({"older-buffered-position", "weak-modem"}.issubset(response["evidence"]))
        self.status(client, tracker, 5800, "needs_action", "unknown")


if __name__ == "__main__":
    import unittest
    unittest.main()
