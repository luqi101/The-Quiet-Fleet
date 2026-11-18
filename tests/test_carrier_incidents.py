import csv
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from quiet_fleet.api import create_app
from test_http_foundation import RULES, STOCK_TRACKER, write_references


class CarrierIncidentTest(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2027, 2, 3, 16, tzinfo=UTC)
        self.data = Path(self.enterContext(tempfile.TemporaryDirectory())) / "data"
        write_references(self.data)
        self.assets = {}
        self.north = "Granite Relay"
        self.south = "Field Ember"

    def at(self, second):
        return (self.base + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")

    def append(self, table, row):
        with (self.data / f"{table}.csv").open("a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(row)

    def device(self, serial, carrier, *, depot="REG", family="T", firmware="9.6", asset=None, status="active"):
        if asset is None:
            asset = f"Unit-{serial}"
            kind = "equipment" if family == "A" else "van"
            self.append("assets", (asset, kind, depot, "service", "Utility", "2026", f"VIN-{serial}", "active"))
        self.assets[serial] = asset
        self.append("devices", (serial, family, f"{family}-model", firmware, carrier, asset, status, "2025-01-01"))
        return serial

    def cohort(self, name, count, carrier, **kwargs):
        return [self.device(f"{name}-{index}", carrier, **kwargs) for index in range(count)]

    def frame(self, serial, kind, second, payload, *, received=None, suffix=""):
        return {
            "serial": serial,
            "event_id": f"{serial}:{kind}:{second}{suffix}",
            "type": kind,
            "device_time": self.at(second),
            "received_at": self.at(second if received is None else received),
            "payload": payload,
        }

    def fix(self, serial, second, *, received=None):
        return self.frame(
            serial, "position", second, {"ignition": True, "lat": 51, "lng": -108, "speed_kmh": 10}, received=received,
        )

    def video(self, serial, second, status="recording"):
        return self.frame(serial, "camera_status", second, {"status": status})

    def client(self):
        return self.enterContext(TestClient(create_app(data_dir=self.data, config_path=RULES)))

    def ingest(self, client, events):
        response = client.post("/ingest", json={"events": events})
        self.assertEqual((response.status_code, response.json()), (200, {"accepted": len(events)}))

    def triage(self, client, second):
        response = client.get("/triage", params={"at": self.at(second)})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        serials = [serial for item in items for serial in item["serials"]]
        self.assertEqual(len(serials), len(set(serials)))
        return items

    def groups(self, client, second):
        return [item for item in self.triage(client, second) if item["kind"] == "incident"]

    def status(self, client, serial, second):
        response = client.get(f"/devices/{serial}/status", params={"at": self.at(second)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_renamed_rescheduled_carriers_both_depots_and_ineligible_devices(self):
        for depot, carrier, date in (("REG", self.north, 3), ("MSS", self.south, 11)):
            with self.subTest(depot=depot):
                self.base = self.base.replace(day=date)
                other = self.south if carrier == self.north else self.north
                lost = self.cohort(f"{depot}-Missed", 5, carrier, depot=depot)
                healthy = self.cohort(f"{depot}-Live", 3, other, depot=depot)
                same_carrier = self.device(f"{depot}-StillReporting", carrier, depot=depot)
                parked = self.cohort(f"{depot}-Parked", 7, carrier, depot=depot)
                parked_camera = self.device(f"{depot}-Sleeping", carrier, depot=depot, family="C", asset=self.assets[parked[0]])
                tag = self.device(f"{depot}-Daily", carrier, depot=depot, family="A")
                silent_stock = self.device(f"{depot}-Stock", carrier, depot=depot, status="stock")
                no_data = self.device(f"{depot}-NoData", carrier, depot=depot)
                client = self.client()
                self.ingest(client, [
                    *[self.fix(serial, 0) for serial in lost + parked],
                    *[self.fix(serial, 360) for serial in healthy + [same_carrier]],
                    *[self.frame(serial, "ignition_off", 60, {}) for serial in parked],
                    self.video(parked_camera, 120, "sleeping"),
                    self.frame(tag, "check_in", 1, {"battery_pct": 60, "lat": 51, "lng": -108, "temp_c": 6}),
                ])
                self.assertEqual(self.groups(client, 360), [])
                group, = self.groups(client, 420)
                self.assertEqual(group["serials"], sorted(lost))
                self.assertTrue({f"{serial}:position:360" for serial in healthy} <= set(group["evidence"]))
                self.assertEqual(set(group["asset_ids"]), {self.assets[serial] for serial in lost})
                self.assertEqual((group["likely_cause"], group["who_acts"], group["priority"]), ("carrier_outage", "carrier", "high"))
                self.assertIn(carrier, group["reasons"][0])
                self.assertIn(depot, group["reasons"][0])
                self.assertIn("5 of 6", group["reasons"][0])
                status = self.status(client, lost[0], 420)
                self.assertEqual((status["state"], status["likely_cause"]), ("needs_action", group["likely_cause"]))
                self.assertEqual(status["last_heard_at"], self.at(0))
                self.assertTrue(set(group["evidence"]) <= set(status["evidence"]))
                for serial in [tag, parked_camera, parked[0], no_data, silent_stock, STOCK_TRACKER, same_carrier]:
                    self.assertNotEqual(self.status(client, serial, 420)["likely_cause"], "carrier_outage")
                self.assertEqual(self.groups(client, 420), [group])

    def test_shift_ending_cancels_expected_location_and_video(self):
        trackers = self.cohort("LateShift", 8, self.north)
        cameras = [self.device(f"Video-{serial}", self.north, family="C", asset=self.assets[serial]) for serial in trackers]
        controls = self.cohort("NextShift", 3, self.south)
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in trackers],
            *[self.video(serial, 30) for serial in cameras],
            *[self.frame(serial, "ignition_off", 120, {}) for serial in trackers],
            *[self.video(serial, 1020, "sleeping") for serial in cameras],
            *[self.fix(serial, 1080) for serial in controls],
        ])
        self.assertEqual(self.triage(client, 1200), [])
        self.assertEqual(self.status(client, cameras[0], 1200)["likely_cause"], "sleeping_by_design")

    def test_physical_and_plan_faults_stay_separate_during_carrier_loss(self):
        lost = self.cohort("Stopped", 5, self.north)
        live = self.cohort("Control", 3, self.south)
        power, paused = self.cohort("OtherReason", 2, self.north)
        camera = self.device("KnownStorage", self.north, family="C", asset=self.assets[lost[0]])
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in lost + [power, paused]],
            *[self.fix(serial, 360) for serial in live],
            self.frame(power, "power_disconnect", 60, {}),
            self.frame(power, "low_voltage", 70, {"volts": 3.2, "source": "backup_battery"}),
            self.frame(paused, "plan_change", 180, {"plan": "connection", "status": "paused", "reason": "account"}),
            self.video(camera, 100, "storage_error"),
        ])
        items = self.triage(client, 720)
        group, = [item for item in items if item["kind"] == "incident"]
        self.assertEqual(group["serials"], sorted(lost))
        causes = {item["serials"][0]: (item["likely_cause"], item["who_acts"]) for item in items if item["kind"] == "device"}
        self.assertEqual(causes, {
            power: ("power_loss", "technician"), paused: ("plan_paused", "support"), camera: ("camera_fault", "support"),
        })
        self.assertEqual(self.status(client, power, 720)["likely_cause"], "power_loss")
        self.assertEqual(self.status(client, camera, 720)["likely_cause"], "camera_fault")

    def test_unrelated_reported_faults_do_not_supply_a_quorum(self):
        disconnected = self.cohort("Harness", 5, self.north)
        controls = self.cohort("OnTime", 3, self.south)
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in disconnected],
            *[self.fix(serial, 360) for serial in controls],
            *[self.frame(serial, "power_disconnect", 180, {}) for serial in disconnected],
        ])
        items = self.triage(client, 480)
        self.assertEqual(len(items), len(disconnected))
        self.assertTrue(all((item["kind"], item["likely_cause"]) == ("device", "power_loss") for item in items))

    def test_shared_outage_across_carriers_routes_to_support(self):
        left = self.cohort("EastPark", 5, self.north)
        right = self.cohort("WestPark", 4, self.south)
        client = self.client()
        self.ingest(client, [self.fix(serial, 0) for serial in left + right])
        group, = self.groups(client, 480)
        self.assertEqual(group["serials"], sorted(left + right))
        self.assertEqual((group["likely_cause"], group["who_acts"], group["priority"]), ("unknown", "support", "medium"))
        status = self.status(client, left[0], 480)
        self.assertEqual((status["state"], status["likely_cause"]), ("needs_action", "unknown"))
        self.assertLess(status["confidence"], 0.9)

    def test_one_firmware_across_carriers_is_a_competing_hypothesis(self):
        left = self.cohort("Rev6North", 5, self.north, firmware="6.4")
        right = self.cohort("Rev6South", 2, self.south, firmware="6.4")
        unaffected = self.cohort("Rev8North", 2, self.north, firmware="8.2") + self.cohort(
            "Rev8South", 4, self.south, firmware="8.2",
        )
        client = self.client()
        self.ingest(client, [*[self.fix(serial, 0) for serial in left + right], *[self.fix(serial, 360) for serial in unaffected]])
        group, = self.groups(client, 480)
        self.assertEqual(group["serials"], sorted(left + right))
        self.assertEqual((group["likely_cause"], group["who_acts"]), ("unknown", "support"))
        self.assertIn("firmware 6.4", group["reasons"][0])

    def test_later_cross_carrier_evidence_can_change_ownership_of_a_compatible_seed(self):
        left = self.cohort("EarlierRadio", 5, self.north, firmware="6.4")
        right = self.cohort("LaterRadio", 2, self.south, firmware="6.4")
        unaffected = self.cohort("OtherVersion", 4, self.south, firmware="8.2")
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in left],
            *[self.fix(serial, 360) for serial in right + unaffected],
            *[self.fix(serial, 720) for serial in unaffected],
        ])
        early, = self.groups(client, 420)
        self.assertEqual((early["likely_cause"], early["serials"]), ("carrier_outage", sorted(left)))
        joint, = self.groups(client, 780)
        self.assertEqual((joint["likely_cause"], joint["who_acts"], joint["serials"]),
                         ("unknown", "support", sorted(left + right)))
        self.assertIn("firmware 6.4", joint["reasons"][0])
        self.assertEqual(self.groups(client, 420), [early])

    def test_live_cameras_are_a_separate_cohort(self):
        trackers = self.cohort("VanTrack", 8, self.north)
        lost = [self.device(f"Video-{serial}", self.north, asset=self.assets[serial], family="C") for serial in trackers[:5]]
        live = [self.device(f"Video-{serial}", self.south, asset=self.assets[serial], family="C") for serial in trackers[5:]]
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, second) for serial in trackers for second in (0, 300, 600, 900)],
            *[self.video(serial, 100) for serial in lost + live],
            *[self.video(serial, 650) for serial in live],
        ])
        self.assertEqual(self.groups(client, 700), [])
        group, = self.groups(client, 900)
        self.assertEqual(group["serials"], sorted(lost))
        self.assertEqual(group["likely_cause"], "carrier_outage")
        self.assertIn("awake camera", group["reasons"][0])
        self.assertTrue({f"{serial}:camera_status:650" for serial in live} <= set(group["evidence"]))

    def test_compatible_camera_joins_tracker_incident_only_once_its_own_report_is_due(self):
        lost = self.cohort("Road", 5, self.north)
        live = self.cohort("Controller", 3, self.south)
        camera = self.device("RoadVideo", self.north, family="C", asset=self.assets[lost[0]])
        unrelated = self.device("OtherVideo", self.north, family="C", asset=self.assets[live[0]])
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in lost + live],
            *[self.fix(serial, 360) for serial in live],
            self.video(camera, 10), self.video(unrelated, 540),
        ])
        early, = self.groups(client, 420)
        self.assertEqual(early["serials"], sorted(lost))
        group, = self.groups(client, 660)
        self.assertEqual(group["item_id"], early["item_id"])
        self.assertEqual(group["serials"], sorted([*lost, camera]))
        self.assertEqual(group["asset_ids"], early["asset_ids"])
        self.assertEqual(self.status(client, camera, 660)["likely_cause"], "carrier_outage")

    def test_long_gap_partial_recovery_full_closure_and_later_episode(self):
        lost = self.cohort("OldFleet", 5, self.north)
        live = self.cohort("Probes", 3, self.south)
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in lost],
            *[self.fix(serial, 240, received=420) for serial in live],
        ])
        self.assertEqual(self.groups(client, 419), [])
        initial, = self.groups(client, 420)
        alias = self.fix(lost[0], 0, received=780) | {"event_id": "late-retry"}
        self.ingest(client, [
            alias, *[self.frame(serial, "ignition_off", 480, {}) for serial in live],
            self.fix(lost[0], 600, received=3600),
        ])
        late, = self.groups(client, 18_000)
        self.assertEqual(late, initial)
        status = self.status(client, lost[0], 18_000)
        self.assertEqual(status["last_heard_at"], self.at(3600))
        self.assertNotIn("late-retry", status["evidence"])
        self.assertEqual(status["likely_cause"], "carrier_outage")
        self.assertNotIn(f"{lost[0]}:position:600", self.status(client, lost[0], 420)["evidence"])

        self.ingest(client, [
            *[self.fix(serial, 18_000, received=18_050) for serial in lost[:3]],
            self.fix(lost[3], 18_001, received=18_051),
        ])
        self.assertEqual(self.groups(client, 18_049), [initial])
        partial, = self.groups(client, 18_050)
        self.assertEqual(partial["serials"], sorted(lost[3:]))
        self.assertEqual(partial["item_id"], initial["item_id"])
        self.assertEqual(self.status(client, lost[0], 18_050)["state"], "reporting")
        self.assertEqual(self.groups(client, 18_051), [])

        # The last straggler may still be overdue. It cannot be absorbed into a
        # new outage until it actually recovers and misses a new opportunity.
        self.ingest(client, [
            *[self.fix(serial, 20_000) for serial in lost[:4] + live],
            *[self.fix(serial, 20_360) for serial in live],
        ])
        self.assertEqual(self.groups(client, 20_420), [])
        self.ingest(client, [
            *[self.fix(serial, 21_000) for serial in lost + live],
            *[self.fix(serial, 21_360) for serial in live],
        ])
        self.assertEqual(self.groups(client, 21_300), [])
        later, = self.groups(client, 21_420)
        self.assertEqual(later["serials"], initial["serials"])
        self.assertNotEqual(later["item_id"], initial["item_id"])
        self.assertEqual(self.groups(client, 420), [initial])

    def test_isolated_buffering_and_retries_remain_individual(self):
        affected = self.cohort("Few", 3, self.north)
        controls = self.cohort("Routine", 3, self.south)
        client = self.client()
        original = self.fix(affected[0], 0)
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in affected],
            *[original | {"event_id": f"retransmission-{index}", "received_at": self.at(500 + index)} for index in range(40)],
            self.fix(affected[0], 120, received=800),
            self.fix(affected[0], 900),
            self.frame(affected[0], "heartbeat", 910, {"battery_v": 12, "signal": 0, "vin": f"VIN-{affected[0]}"}),
            *[self.fix(serial, 1200) for serial in controls],
        ])
        item, = self.triage(client, 1320)
        self.assertEqual((item["kind"], item["serials"], item["likely_cause"], item["who_acts"]),
                         ("device", affected[:1], "coverage_gap", "support"))

    def test_population_share_and_synchronization_gates(self):
        affected = self.cohort("Drift", 10, self.north)
        steady = self.cohort("Steady", 6, self.north)
        controls = self.cohort("Comparable", 3, self.south)
        client = self.client()
        self.ingest(client, [
            *[self.fix(serial, 0) for serial in affected[:5]],
            *[self.fix(serial, 300) for serial in steady + controls + affected[5:]],
            *[self.fix(serial, 600) for serial in steady + controls + affected[5:]],
            *[self.fix(serial, 900) for serial in steady + controls + affected[5:]],
            *[self.fix(serial, 1200) for serial in steady + controls],
        ])
        self.assertEqual(self.groups(client, 420), [])
        self.assertEqual(self.groups(client, 1320), [])
