"""Independent causal, temporal and metamorphic checks through the HTTP API."""

import csv
import json
import random
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from itertools import batched, cycle, islice
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from evidence_client import AuditedClient
import test_normal_reporting as fixture
from quiet_fleet.api import create_app
from test_http_foundation import RULES, write_references


MISSED = tuple(f"miss-{i}" for i in range(5))
CONTROLS = tuple(f"control-{i}" for i in range(3))
LABELS = (*MISSED, *CONTROLS, "power", "camera", "account", "tag", "spare")
FIX = {"lat": 48.1, "lng": -92.4, "speed_kmh": 0, "ignition": True}
REBOOT = {"command": "reboot", "issued_by": "support"}
CUT = 720


class FleetScenario:
    """Five interrupted drives with live controls and unrelated individual issues."""

    def __init__(self, directory, *, relocated=False):
        self.data = directory
        write_references(directory)
        self.depot = "REG" if relocated else "MSS"
        zone = ZoneInfo("America/Regina" if relocated else "America/Toronto")
        day = (2027, 2, 7) if relocated else (2026, 11, 1)
        self.base = datetime(*day, 6, tzinfo=zone).astimezone(UTC)
        self.carrier, self.other = (
            ("Evening Radio", "Juniper Connect") if relocated else ("Orchard Mobile", "Wren Communications")
        )
        self.serials, self.assets, self.ids = {}, {}, {}
        for index, label in enumerate(LABELS):
            family = {"camera": "C", "tag": "BX"}.get(label, "T")
            self.serials[label] = f"{family}-{'Y' if relocated else 'Q'}{99 - index if relocated else index}"
            if label == "camera":
                asset = self.assets[CONTROLS[0]]
            elif label == "spare":
                asset = ""
            else:
                asset = f"{'Annex' if relocated else 'Field'}-{index * 7 if relocated else 99 - index}"
                self.append("assets", (
                    asset, "equipment" if label == "tag" else "van", self.depot, "service",
                    "Utility", "2025", self.vin(asset), "active",
                ))
            self.assets[label] = asset
            status = {MISSED[0]: "removed", "spare": "stock"}.get(label, "active")
            self.append("devices", (
                self.serials[label], family, "Test model", "1.2.3",
                self.other if label in CONTROLS else self.carrier,
                asset, status, "" if label == "spare" else "2025-01-01",
            ))
        self.append("schedule", (
            "fixture-duty", self.assets["power"], self.depot, self.at(700), self.at(900), "delivery",
        ))

    def at(self, second):
        return (self.base + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")

    def append(self, table, row):
        with (self.data / f"{table}.csv").open("a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(row)

    @staticmethod
    def vin(asset):
        return f"VIN-{asset}"

    def frame(self, name, label, kind, second, payload, *, received=None):
        index = len(self.ids)
        id_number = 900 + index if self.depot == "REG" else 900 - index
        event_id = self.ids.setdefault(name, f"{self.carrier[0]}-event-{id_number}")
        receipt = self.at(second if received is None else received)
        if kind == "bx_raw":
            seconds = int((self.base + timedelta(seconds=second)).timestamp())
            raw = {"u": self.serials[label], "t": f"{seconds:X}", "p": "4810000,-9240000", **payload}
            return {"event_id": event_id, "type": kind, "received_at": receipt, "raw": json.dumps(raw)}
        return {
            "event_id": event_id, "serial": self.serials[label], "type": kind,
            "device_time": self.at(second), "received_at": receipt, "payload": payload,
        }

    def initial(self):
        return [
            *[self.frame(label, label, "position", 0, FIX) for label in MISSED],
            # Controls are live near the gap onset as well as at the checkpoint.
            *[self.frame(f"{label}-{second}", label, "position", second, FIX)
              for label in CONTROLS for second in (360, 670)],
            self.frame("power-initial", "power", "position", 0, FIX),
            self.frame("harness", "power", "power_disconnect", 80, {}),
            self.frame("reserve", "power", "low_voltage", 120, {"source": "backup_battery", "volts": 3.1}),
            self.frame("backup-position", "power", "position", 690, FIX),
            self.frame("video-error", "camera", "camera_status", 90, {"status": "storage_error"}),
            self.frame("camera-command", "camera", "command", 700, REBOOT),
            self.frame("ending", "account", "plan_change", 100,
                       {"plan": "data", "status": "ended", "reason": "request"}),
            self.frame("bx-low", "tag", "bx_raw", 100, {"b": 573, "s": 0x26}),
        ]

    def later_receipts(self, first):
        return [
            *[self.frame(f"back-online-{label}", label, "position", 700, FIX, received=721)
              for label in MISSED],
            self.frame("video-restored", "camera", "camera_status", 600, {"status": "recording"}, received=722),
            self.frame("charged", "tag", "bx_raw", 600, {"b": 3000, "s": 0x28}, received=724),
            self.frame("restored-harness", "power", "power_restore", 715, {}, received=725),
            self.frame("activated", "account", "plan_change", 600,
                       {"plan": "data", "status": "active", "reason": "approved"}, received=730),
            self.frame("stock-vin", "spare", "heartbeat", 710,
                       {"battery_v": 12.5, "signal": 4, "vin": self.vin(self.assets[MISSED[0]])}, received=730),
            first | {"event_id": "future-duplicate-id", "received_at": self.at(745)},
        ]

    def snapshot(self, client, second):
        query = {"at": self.at(second)}
        statuses = {label: client.get(f"/devices/{serial}/status", params=query).json()
                    for label, serial in self.serials.items()}
        return statuses, client.get("/triage", params=query).json()

    def logical_view(self, snapshot):
        """Translate renamed wire identifiers and times to the fixture's roles."""
        statuses, queue = snapshot
        event_labels = {value: key for key, value in self.ids.items()}
        serial_labels = {value: key for key, value in self.serials.items()}
        asset_labels = {self.assets[key]: key for key in LABELS if key not in {"camera", "spare"}}

        def evidence(body):
            return {event_labels[event_id] for event_id in body["evidence"]}

        def seconds(instant):
            return (datetime.fromisoformat(instant) - self.base).total_seconds() if instant else None

        return {
            label: (body["state"], body["likely_cause"], body["confidence"],
                    asset_labels[body["asset_id"]] if body["asset_id"] is not None else None,
                    seconds(body["last_heard_at"]), evidence(body))
            for label, body in statuses.items()
        }, {
            frozenset(serial_labels[serial] for serial in item["serials"]): (
                item["kind"], item["likely_cause"], item["who_acts"], item["priority"],
                {asset_labels[asset] for asset in item["asset_ids"]}, evidence(item),
            )
            for item in queue["items"]
        }


class WholeFleetTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def client(self, scenario):
        return self.enterContext(AuditedClient(create_app(scenario.data, RULES)))

    def post(self, client, events):
        response = client.post("/ingest", json={"events": events})
        self.assertEqual((response.status_code, response.json()), (200, {"accepted": len(events)}))

    def assert_baseline(self, scenario, snapshot):
        statuses, queue = snapshot
        items = {frozenset(item["serials"]): item for item in queue["items"]}
        affected = frozenset(scenario.serials[label] for label in MISSED)
        expected = {
            affected: ("incident", "carrier_outage", "carrier", "high"),
            frozenset([scenario.serials["power"]]): ("device", "power_loss", "technician", "high"),
            frozenset([scenario.serials["camera"]]): ("device", "camera_fault", "support", "medium"),
            frozenset([scenario.serials["account"]]): ("device", "plan_paused", "support", "low"),
            frozenset([scenario.serials["tag"]]): ("device", "battery_low", "technician", "medium"),
        }
        self.assertEqual({
            members: (item["kind"], item["likely_cause"], item["who_acts"], item["priority"])
            for members, item in items.items()
        }, expected)
        self.assertEqual(set(items[affected]["asset_ids"]), {scenario.assets[label] for label in MISSED})
        keys = {scenario.ids[label] for label in (*MISSED, *(f"{label}-360" for label in CONTROLS))}
        self.assertTrue(keys.issubset(items[affected]["evidence"]))
        for label in MISSED:
            self.assertEqual((statuses[label]["state"], statuses[label]["likely_cause"]), ("needs_action", "carrier_outage"))
            self.assertEqual(statuses[label]["last_heard_at"], scenario.at(0))
        for label, key in (("power", "harness"), ("camera", "video-error"), ("account", "ending"), ("tag", "bx-low")):
            item = items[frozenset([scenario.serials[label]])]
            self.assertIn(scenario.ids[key], item["evidence"])
            self.assertEqual(statuses[label]["likely_cause"], item["likely_cause"])
        self.assertEqual(statuses["power"]["last_heard_at"], scenario.at(690))
        self.assertEqual(statuses["camera"]["last_heard_at"], scenario.at(90))
        self.assertIsNone(statuses["account"]["last_heard_at"])
        self.assertEqual((statuses["spare"]["asset_id"], statuses["spare"]["evidence"]), (None, []))

    def test_renamed_relocated_repartitioned_and_retried_fleet_keeps_its_meaning(self):
        original = FleetScenario(self.root / "before")
        original_client = self.client(original)
        initial = original.initial()
        full = list(islice(cycle(initial), 5000))
        self.post(original_client, full)
        baseline = original.snapshot(original_client, CUT)
        self.assert_baseline(original, baseline)
        self.post(original_client, full)
        self.assertEqual(original.snapshot(original_client, CUT), baseline)

        retries = []
        for frame in initial:
            receipt = datetime.fromisoformat(frame["received_at"]) + timedelta(seconds=10)
            alias = frame | {"event_id": f"retry:{frame['event_id']}", "received_at": receipt.isoformat()}
            field = "raw" if "raw" in alias else "payload"
            data = json.loads(alias[field]) if field == "raw" else alias[field]
            reordered = dict(reversed(list(data.items())))
            retries.append(alias | {field: json.dumps(reordered) if field == "raw" else reordered})
        permuted = [*full, *retries]
        random.Random(729).shuffle(permuted)
        other_client = self.client(original)
        for partition in batched(permuted, 137):
            self.post(other_client, partition)
        self.assertEqual(original.snapshot(other_client, CUT), baseline)
        with patch("time.time", return_value=2_200_000_000):
            self.assertEqual(original.snapshot(other_client, CUT), baseline)

        relocated = FleetScenario(self.root / "after", relocated=True)
        relocated_client = self.client(relocated)
        for partition in batched(list(reversed(relocated.initial())), 3):
            self.post(relocated_client, partition)
        transformed = relocated.snapshot(relocated_client, CUT)
        self.assert_baseline(relocated, transformed)
        self.assertEqual(relocated.logical_view(transformed), original.logical_view(baseline))
        # Both jobs end at local 06:15 on a Sunday. Toronto is on EST after the fall-back.
        for scenario, snapshot, local_offset in ((original, baseline, "-05:00"), (relocated, transformed, "-06:00")):
            power, = [item for item in snapshot[1]["items"] if item["serials"] == [scenario.serials["power"]]]
            self.assertIn(f"06:15:00{local_offset}", " ".join(power["reasons"]))

    def test_ingested_future_receipts_leave_the_entire_view_unchanged_until_eligible(self):
        scenario = FleetScenario(self.root / "references")
        initial = scenario.initial()
        client = self.client(scenario)
        self.post(client, initial)
        baseline = scenario.snapshot(client, CUT)
        self.assert_baseline(scenario, baseline)
        self.post(client, scenario.later_receipts(initial[0]))
        self.assertEqual(scenario.snapshot(client, CUT), baseline)

        queue_after_gap = scenario.snapshot(client, 721)[1]["items"]
        self.assertFalse(any(item["kind"] == "incident" for item in queue_after_gap))
        expected_at_receipt = (
            (721, MISSED[0], "reporting", "none", "back-online-miss-0"),
            (722, "camera", "reporting", "none", "video-restored"),
            (724, "tag", "reporting", "none", "charged"),
            (725, "power", "reporting", "none", "restored-harness"),
            (730, "spare", "needs_action", "device_swapped", "stock-vin"),
        )
        for receipt, label, state, cause, key in expected_at_receipt:
            with self.subTest(label=label):
                status = scenario.snapshot(client, receipt)[0][label]
                self.assertEqual((status["state"], status["likely_cause"]), (state, cause), status)
                self.assertIn(scenario.ids[key], status["evidence"])
        at_resume = scenario.snapshot(client, 730)
        self.assertEqual(at_resume[0]["spare"]["asset_id"], scenario.assets[MISSED[0]])
        self.assertNotIn("plan_paused", {item["likely_cause"] for item in at_resume[1]["items"]})

        # New knowledge with a genuinely eligible receipt can change the old checkpoint.
        self.post(client, [scenario.frame("earlier-repair", "power", "power_restore", 640, {}, received=719)])
        status, queue = scenario.snapshot(client, CUT)
        self.assertEqual({label: status[label] for label in LABELS if label != "power"},
                         {label: baseline[0][label] for label in LABELS if label != "power"})
        self.assertEqual((status["power"]["state"], status["power"]["likely_cause"]), ("reporting", "none"))
        self.assertEqual(queue["items"],
                         [item for item in baseline[1]["items"] if item["serials"] != [scenario.serials["power"]]])

        # Each later arrival is older in observation time than the real recovery.
        self.post(client, [
            scenario.frame("old-disconnect", "power", "power_disconnect", 60, {}, received=750),
            scenario.frame("old-camera-error", "camera", "camera_status", 59, {"status": "storage_error"}, received=751),
            scenario.frame("old-bx-low", "tag", "bx_raw", 61, {"b": 550, "s": 0x02}, received=752),
        ])
        after_backfill, queue = scenario.snapshot(client, 752)
        for label in ("power", "camera", "tag"):
            self.assertEqual(after_backfill[label]["likely_cause"], "none")
            self.assertFalse(any(scenario.serials[label] in item["serials"] for item in queue["items"]))

    def test_reference_cases_and_plan_rows_do_not_leak_current_diagnosis(self):
        clean = FleetScenario(self.root / "clean")
        poisoned = FleetScenario(self.root / "extra-history")
        poisoned.append("plan_changes", (poisoned.serials["account"], poisoned.at(130), "data", "active",
                                        "reference only", "csv-resume-id"))
        poisoned.append("plan_changes", (poisoned.serials[CONTROLS[0]], poisoned.at(360), "data", "paused",
                                        "reference only", "csv-pause-id"))
        poisoned.append("support_cases", (
            "csv-improper-closure", poisoned.at(50), poisoned.at(650), poisoned.depot, poisoned.assets["camera"],
            poisoned.serials["camera"], "support", "future repair", "camera_fault", "technician_visit",
            "resolved", "case outcome unavailable through ingest",
        ))
        poisoned.append("support_cases", (
            "csv-future-fault", poisoned.at(1000), poisoned.at(1100), poisoned.depot, poisoned.assets[CONTROLS[1]],
            poisoned.serials[CONTROLS[1]], "support", "future disconnect", "power_loss", "technician_visit",
            "resolved", "no contemporaneous fault",
        ))
        clean_client, poisoned_client = self.client(clean), self.client(poisoned)
        self.post(clean_client, clean.initial())
        self.post(poisoned_client, poisoned.initial())
        baseline = clean.snapshot(clean_client, CUT)
        self.assert_baseline(clean, baseline)
        self.assertEqual(poisoned.snapshot(poisoned_client, CUT), baseline)

    def test_mixed_wire_elements_cannot_corrupt_valid_neighbors_or_add_a_catalog_device(self):
        scenario = FleetScenario(self.root / "references")
        client = self.client(scenario)
        label = MISSED[0]
        opening = scenario.frame("on", label, "ignition_on", 0, {"vin": scenario.vin(scenario.assets[label])})
        parked = scenario.frame("parked", label, "ignition_off", 18, {})
        invalid = [
            True, None, [], {"event_id": "ordinary-bad-element"},
            scenario.frame("bool-lat", label, "position", 40, FIX | {"lat": True}),
            scenario.frame("overflow", label, "position", 40, FIX | {"speed_kmh": "decimal-overflow"}),
            scenario.frame("device-without-zone", label, "ignition_off", 45, {}) | {"device_time": "2026-10-04T11:00:45"},
            scenario.frame("bool-time", label, "power_disconnect", 50, {}) | {"device_time": False},
            opening | {"type": "power_disconnect", "payload": {}},
        ]
        frames = [
            opening, *invalid,
            {"type": "reserved_message", "event_id": "unused-message", "received_at": scenario.at(55)},
            scenario.frame("non-catalog", label, "position", 58, FIX) | {"serial": "unregistered-tracker"},
            scenario.frame("clock-ahead", label, "power_disconnect", 400, {}, received=30),
            parked,
        ]
        payload = json.dumps({"events": frames}).replace('"decimal-overflow"', '1e309')
        response = client.post("/ingest", content=payload, headers={"Content-Type": "application/json"})
        self.assertEqual((response.status_code, response.json()), (200, {"accepted": 5}))
        self.assertEqual(client.get("/devices/unregistered-tracker/status", params={"at": scenario.at(60)}).status_code, 404)
        self.assertEqual(client.app.state.runtime.store.counts().conflicts, 1)
        for checkpoint in (60, 420):
            body = scenario.snapshot(client, checkpoint)[0][label]
            self.assertEqual((body["state"], body["likely_cause"]), ("quiet_expected", "parked_normal"))
            self.assertEqual(body["last_heard_at"], scenario.at(30))
            self.assertIn(scenario.ids["parked"], body["evidence"])


class EpisodeAdversarialTest(fixture.ReportingFixture):
    def item(self, client, serial, second):
        response = client.get("/triage", params={"at": fixture.instant(second)})
        self.assertEqual(response.status_code, 200, response.text)
        return next((item for item in response.json()["items"] if item["serials"] == [serial]), None)

    def test_coincident_counterevidence_does_not_restart_an_open_episode(self):
        tag, tracker, camera = fixture.TAG, fixture.TRACKER, fixture.CAMERA
        a_report = {"battery_pct": 8, "lat": 44, "lng": -79, "temp_c": 5}
        event = fixture.event
        initial = [
            event("initial-low", tag, "check_in", 0, a_report),
            event("initial-power", tracker, "power_disconnect", 0, {}),
            event("initial-storage", camera, "camera_status", 0, {"status": "storage_error"}),
        ]
        pairs = [
            (tag, "check_in", a_report | {"battery_pct": 9}, "check_in", a_report | {"battery_pct": 40}, "battery_low"),
            (tracker, "power_disconnect", {}, "power_restore", {}, "power_loss"),
            (camera, "camera_status", {"status": "storage_error"}, "camera_status", {"status": "recording"}, "camera_fault"),
        ]
        for fault_id, clear_id in (("a-fault", "z-clear"), ("z-fault", "a-clear")):
            with self.subTest(fault_id=fault_id):
                client = self.client()
                self.ingest(client, *initial)
                for serial, bad_kind, bad, good_kind, good, cause in pairs:
                    with self.subTest(cause=cause):
                        start = self.item(client, serial, 59)
                        self.assertEqual(start["likely_cause"], cause)
                        evidence = {row["event_id"] for row in initial if row["serial"] == serial}
                        self.ingest(
                            client, event(f"{clear_id}-{serial}", serial, good_kind, 60, good),
                            event(f"{fault_id}-{serial}", serial, bad_kind, 60, bad),
                        )
                        contested = self.item(client, serial, 60)
                        self.assertEqual(contested["likely_cause"], cause)
                        self.assertEqual(contested["item_id"], start["item_id"])
                        self.assertTrue(evidence <= set(contested["evidence"]))
                        self.ingest(client, event(f"real-clear-{serial}", serial, good_kind, 61, good))
                        self.assertIsNone(self.item(client, serial, 61))

    def test_coincident_plan_activation_does_not_lift_a_hold(self):
        event, tracker = fixture.event, fixture.TRACKER
        for hold_id, active_id in (("a-held", "z-active"), ("z-held", "a-active")):
            with self.subTest(hold_id=hold_id):
                client = self.client()
                self.ingest(client, event("opening-hold", tracker, "plan_change", 10,
                                          {"plan": "data", "status": "paused", "reason": "request"}))
                start = self.item(client, tracker, 59)
                self.assertEqual((start["likely_cause"], start["who_acts"]), ("plan_paused", "support"))
                self.ingest(
                    client,
                    event(hold_id, tracker, "plan_change", 60, {"plan": "data", "status": "ended", "reason": "closed"}),
                    event(active_id, tracker, "plan_change", 60, {"plan": "data", "status": "active", "reason": "approved"}),
                )
                retained = self.item(client, tracker, 60)
                self.assertIsNotNone(retained, "The plan is still held at the shared effective time.")
                self.assertEqual(retained["item_id"], start["item_id"])
                self.assertTrue({"opening-hold", hold_id} <= set(retained["evidence"]))
                self.ingest(client, event("later-active", tracker, "plan_change", 61,
                                          {"plan": "data", "status": "active", "reason": "confirmed"}))
                self.assertIsNone(self.item(client, tracker, 61))

    def test_stale_ignition_cannot_turn_reboots_into_failed_awake_trials(self):
        client = self.client()
        event = fixture.event
        tracker, camera = fixture.TRACKER, fixture.CAMERA
        self.ingest(
            client, event("on-then-silent", tracker, "ignition_on", 0, {"vin": fixture.VIN}),
            event("known-fault", camera, "camera_status", 10, {"status": "storage_error"}),
            event("reboot-with-stale-ignition", camera, "command", 700, REBOOT),
            event("second-with-stale-ignition", camera, "command", 1400, REBOOT),
        )
        issue = self.item(client, camera, 2000)
        self.assertEqual((issue["likely_cause"], issue["who_acts"]), ("camera_fault", "support"))
        self.assertIn("known-fault", issue["evidence"])
        self.assertNotIn("second-with-stale-ignition", issue["evidence"])

    def test_restored_tracker_power_does_not_erase_a_trial_interruption(self):
        client = self.client()
        event = fixture.event
        tracker, camera = fixture.TRACKER, fixture.CAMERA
        self.ingest(
            client, event("stable-on", tracker, "ignition_on", 0, {"vin": fixture.VIN}),
            event("persistent-fault", camera, "camera_status", 10, {"status": "storage_error"}),
            event("interrupted-trial", camera, "command", 100, REBOOT),
            event("mid-trial-power-out", tracker, "power_disconnect", 300, {}),
            event("mid-trial-power-return", tracker, "power_restore", 500, {}),
            event("first-complete-trial", camera, "command", 800, REBOOT),
            event("second-complete-trial", camera, "command", 1500, REBOOT),
            *[fixture.position(f"awake-{t}", tracker, t) for t in range(120, 2101, 120)],
        )
        self.assertEqual(self.item(client, camera, 1400)["who_acts"], "support")
        self.assertEqual(self.item(client, camera, 2099)["who_acts"], "support")
        finished = self.item(client, camera, 2100)
        self.assertEqual(finished["who_acts"], "technician")
        self.assertNotIn("interrupted-trial", finished["evidence"])
        self.assertTrue({"persistent-fault", "first-complete-trial", "second-complete-trial"} <= set(finished["evidence"]))

    def test_repeated_credible_ignition_on_can_confirm_awake_trials(self):
        client = self.client()
        tracker, camera = fixture.TRACKER, fixture.CAMERA
        self.ingest(
            client, fixture.event("awake-trial-fault", camera, "camera_status", 10, {"status": "storage_error"}),
            fixture.event("awake-trial-first", camera, "command", 100, REBOOT),
            fixture.event("awake-trial-second", camera, "command", 800, REBOOT),
            *[fixture.event(f"steady-on-{t}", tracker, "ignition_on", t, {"vin": fixture.VIN})
              for t in range(0, 1401, 200)],
        )
        self.assertEqual(self.item(client, camera, 1399)["who_acts"], "support")
        completed = self.item(client, camera, 1400)
        self.assertEqual(completed["who_acts"], "technician")
        self.assertTrue({"awake-trial-fault", "awake-trial-first", "awake-trial-second"} <= set(completed["evidence"]))

    def test_late_ignition_off_invalidates_a_trial_only_after_its_receipt(self):
        client = self.client()
        tracker, camera = fixture.TRACKER, fixture.CAMERA
        self.ingest(
            client, fixture.event("unrepaired-storage", camera, "camera_status", 20, {"status": "storage_error"}),
            fixture.event("first-reboot", camera, "command", 100, REBOOT),
            fixture.event("second-reboot", camera, "command", 800, REBOOT),
            *[fixture.position(f"on-{t}", tracker, t) for t in range(0, 1441, 120)],
        )
        completed = self.item(client, camera, 1400)
        self.assertEqual(completed["who_acts"], "technician")
        self.ingest(client, fixture.event("buffered-ignition-off", tracker, "ignition_off", 610, {}, received=1450))
        self.assertEqual(self.item(client, camera, 1400), completed)
        revised = self.item(client, camera, 1450)
        self.assertEqual((revised["item_id"], revised["who_acts"]), (completed["item_id"], "support"))
        self.assertIn("second-reboot", revised["evidence"])
        self.assertNotIn("first-reboot", revised["evidence"])

    def test_landscaping_stop_without_confirmed_policy_remains_uncertain(self):
        trailing = "TR-SEASONAL"
        tag = "A-SEASONAL"
        self.append_csv("assets", (trailing, "equipment", "MSS", "landscaping", "Test Trailer", "2024", "", "active"))
        self.add_device(tag, "A", trailing)
        client = self.client()
        reading = {"lat": 44, "lng": -79, "battery_pct": 80, "temp_c": 8}
        self.ingest(client, *[fixture.event(f"landscaping-{day}", tag, "check_in", day * 86400, reading)
                              for day in range(4)])
        body = self.status(client, tag, 6 * 86400, "unknown")
        self.assertIn("landscaping-3", body["evidence"])
        self.assertIsNone(self.item(client, tag, 6 * 86400))
