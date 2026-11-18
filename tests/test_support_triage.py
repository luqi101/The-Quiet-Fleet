import csv
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from evidence_client import AuditedClient as TestClient

from quiet_fleet.api import create_app
from test_http_foundation import RULES, STOCK_TRACKER, write_references


class SupportTriageTest(unittest.TestCase):
    def setUp(self):
        self.base = datetime(2026, 10, 31, 16, tzinfo=UTC)
        self.data = Path(self.enterContext(tempfile.TemporaryDirectory())) / "data"
        write_references(self.data)
        self.assets = {}
        self.receipts = {}

    def at(self, value):
        if isinstance(value, str):
            return value
        return (self.base + timedelta(seconds=value)).isoformat().replace("+00:00", "Z")

    def append(self, table, row):
        with (self.data / f"{table}.csv").open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerow(row)

    def device(self, serial, family="T", depot="MSS", *, carrier="Cloud Marsh", paired=None):
        asset = self.assets[paired][0] if paired else f"Asset-{serial}"
        if paired is None:
            kind = "equipment" if family == "A" else "van"
            self.append("assets", (asset, kind, depot, "service", "Utility", "2026", f"VIN-{serial}", "active"))
        self.assets[serial] = (asset, depot)
        self.append("devices", (serial, family, f"{family}-model", "7.5", carrier, asset, "active", "2025-08-01"))
        return serial

    def job(self, serial, start, end, job_type="service"):
        asset, depot = self.assets[serial]
        self.append("schedule", (f"Work-{serial}-{start}", asset, depot, self.at(start), self.at(end), job_type))

    def frame(self, serial, kind, when, payload=None, *, received=None, event_id=None):
        return {
            "event_id": event_id or f"{serial}/{kind}/{when}",
            "serial": serial,
            "type": kind,
            "device_time": self.at(when),
            "received_at": self.at(when if received is None else received),
            "payload": payload if payload is not None else {},
        }

    def fix(self, serial, when, *, ignition=True, received=None, event_id=None):
        return self.frame(
            serial, "position", when, {"lat": 50, "lng": -108, "speed_kmh": 0, "ignition": ignition},
            received=received, event_id=event_id,
        )

    def camera(self, serial, when, status, **receipt):
        return self.frame(serial, "camera_status", when, {"status": status}, **receipt)

    def tag(self, serial, when, pct):
        return self.frame(serial, "check_in", when, {"lat": 50, "lng": -108, "battery_pct": pct, "temp_c": 16})

    def plan(self, serial, when, status):
        return self.frame(serial, "plan_change", when, {"plan": "data", "status": status, "reason": "account review"})

    def client(self, *, config=RULES):
        return self.enterContext(TestClient(create_app(data_dir=self.data, config_path=config)))

    def ingest(self, client, *events):
        response = client.post("/ingest", json={"events": events})
        self.assertEqual((response.status_code, response.json()), (200, {"accepted": len(events)}))
        for event in events:
            receipt = datetime.fromisoformat(event["received_at"])
            key = event["event_id"]
            self.receipts[key] = min(self.receipts.get(key, receipt), receipt)

    def assert_evidence(self, evidence, cutoff):
        self.assertEqual(len(evidence), len(set(evidence)))
        for event_id in evidence:
            self.assertIs(type(event_id), str)
            self.assertIn(event_id, self.receipts)
            self.assertLessEqual(self.receipts[event_id], cutoff)

    def triage(self, client, when):
        response = client.get("/triage", params={"at": self.at(when)})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        cutoff = datetime.fromisoformat(self.at(when))
        self.assertEqual(set(result), {"at", "items"})
        self.assertEqual(result["at"], cutoff.astimezone(UTC).isoformat().replace("+00:00", "Z"))
        seen, ids = set(), set()
        for item in result["items"]:
            self.assertEqual(set(item), {
                "item_id", "kind", "serials", "asset_ids", "likely_cause", "who_acts", "next_action",
                "priority", "reasons", "evidence",
            })
            self.assertNotIn(item["item_id"], ids)
            ids.add(item["item_id"])
            self.assertIn(item["kind"], {"device", "incident"})
            if item["kind"] == "device":
                self.assertEqual(len(item["serials"]), 1)
            else:
                self.assertGreaterEqual(len(item["serials"]), 2)
            self.assertEqual(len(item["serials"]), len(set(item["serials"])))
            self.assertEqual(len(item["asset_ids"]), len(set(item["asset_ids"])))
            self.assertTrue(seen.isdisjoint(item["serials"]))
            seen.update(item["serials"])
            self.assertIn(item["who_acts"], {"support", "carrier", "technician"})
            self.assertIn(item["priority"], {"high", "medium", "low"})
            self.assertTrue(item["next_action"].strip())
            self.assertTrue(item["reasons"])
            self.assertTrue(all(isinstance(reason, str) and reason.strip() for reason in item["reasons"]))
            self.assertEqual(len(item["reasons"]), len(set(item["reasons"])))
            self.assertTrue(item["evidence"])
            self.assert_evidence(item["evidence"], cutoff)
        return result["items"]

    def status(self, client, when, serial, item=None):
        response = client.get(f"/devices/{serial}/status", params={"at": self.at(when)})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assert_evidence(result["evidence"], datetime.fromisoformat(self.at(when)))
        if item:
            self.assertEqual((result["state"], result["likely_cause"]), ("needs_action", item["likely_cause"]))
            self.assertEqual(result["reasons"], [*item["reasons"], item["next_action"]])
            self.assertTrue(set(item["evidence"]) <= set(result["evidence"]))
        return result

    def test_every_actionable_cause_has_one_owner_and_shared_evidence(self):
        harness = self.device("Wiring")
        tag = self.device("Daily", "A")
        trailer_tracker = self.device("Video-van")
        video = self.device("Video", "C", paired=trailer_tracker)
        account = self.device("Account")
        gap = self.device("Buffered")
        uncertain = self.device("Needs-telemetry")
        swapped_asset = self.device("Install-asset")
        missing = [self.device(f"Regional-{index}", depot="REG") for index in range(5)]
        live = [self.device(f"Control-{index}", depot="REG", carrier="Driftwood") for index in range(3)]
        self.job(uncertain, 1800, 2400)
        client = self.client()
        self.ingest(client,
            self.fix(harness, 0), self.frame(harness, "power_disconnect", 5),
            self.frame(harness, "low_voltage", 12, {"volts": 3.1, "source": "backup_battery"}),
            self.tag(tag, 30, 9),
            self.fix(trailer_tracker, 1270), self.camera(video, 300, "storage_error"),
            self.plan(account, 305, "ended"),
            self.fix(gap, 20, received=500), self.fix(gap, 920),
            self.frame(gap, "heartbeat", 890, {"battery_v": 12, "signal": 0, "vin": f"VIN-{gap}"}),
            self.fix(uncertain, 0),
            self.frame(STOCK_TRACKER, "ignition_on", 450, {"vin": f"VIN-{swapped_asset}"}),
            *[self.fix(serial, 900) for serial in missing], *[self.fix(serial, 1280) for serial in live],
        )
        items = self.triage(client, 1320)
        owners = {
            harness: ("power_loss", "technician", "harness"),
            tag: ("battery_low", "technician", "battery"),
            video: ("camera_fault", "support", "reboot"),
            account: ("plan_paused", "support", "account"),
            gap: ("coverage_gap", "support", "connectivity"),
            uncertain: ("unknown", "support", "dispatch"),
            STOCK_TRACKER: ("device_swapped", "support", "inventory"),
        }
        individual = {item["serials"][0]: item for item in items if item["kind"] == "device"}
        self.assertEqual(set(individual), set(owners))
        for serial, (cause, owner, step) in owners.items():
            with self.subTest(serial=serial):
                item = individual[serial]
                self.assertEqual((item["likely_cause"], item["who_acts"]), (cause, owner))
                self.assertIn(step, item["next_action"])
                self.status(client, 1320, serial, item)

        group, = [item for item in items if item["kind"] == "incident"]
        self.assertEqual((group["serials"], group["who_acts"], group["priority"]), (sorted(missing), "carrier", "high"))
        self.assertIn("Cloud Marsh", group["next_action"])
        self.assertIn("one consolidated", group["next_action"])
        for serial in missing:
            self.status(client, 1320, serial, group)

    def test_current_job_starts_and_ends_exactly_and_receipts_gate_urgency(self):
        tracker = self.device("Running-job")
        self.job(tracker, 600, 3000, "inspection")
        client = self.client()
        self.ingest(client, self.frame(tracker, "power_disconnect", 300, received=500, event_id="wire-cut"))
        self.assertEqual(self.triage(client, 499.999999), [])
        upcoming, = self.triage(client, 599.999999)
        active, = self.triage(client, 600)
        ending, = self.triage(client, 2999.999999)
        done, = self.triage(client, 3000)
        self.assertEqual([item["priority"] for item in (upcoming, active, ending, done)], ["high", "high", "high", "medium"])
        self.assertEqual({item["item_id"] for item in (upcoming, active, ending, done)}, {active["item_id"]})
        self.assertIn("scheduled", upcoming["reasons"][-1])
        self.assertIn("in progress", active["reasons"][-1])
        self.assertFalse(any("in progress" in reason for reason in done["reasons"]))
        self.assertIn(self.at(300), active["reasons"][0])
        self.assertEqual(active["evidence"], ["wire-cut"])
        self.status(client, 600, tracker, active)

    def test_sunday_shift_uses_actual_depot_time_zones_and_inclusive_horizon(self):
        mississauga = self.device("Eastern-job")
        regina = self.device("Prairie-job", depot="REG")
        for serial in (mississauga, regina):
            self.job(serial, "2026-11-01T18:00:00Z", "2026-11-01T19:00:00Z")
        client = self.client()
        self.ingest(client, self.frame(mississauga, "power_disconnect", 0), self.frame(regina, "power_disconnect", 0))

        probes = (
            ("2026-11-01T01:00:00Z", "medium", "medium"),
            ("2026-11-01T01:30:00-04:00", "medium", "medium"),
            ("2026-11-01T01:30:00-05:00", "medium", "medium"),
            ("2026-11-01T08:59:59.999999Z", "medium", "medium"),
            ("2026-11-01T09:00:00Z", "high", "medium"),
            ("2026-11-01T09:59:59.999999Z", "high", "medium"),
            ("2026-11-01T10:00:00Z", "high", "high"),
            ("2026-11-01T11:00:00Z", "high", "high"),
            ("2026-11-01T11:00:00.000001Z", "medium", "high"),
            ("2026-11-01T12:00:00Z", "medium", "high"),
            ("2026-11-01T12:00:00.000001Z", "medium", "medium"),
        )
        for instant, east_priority, west_priority in probes:
            with self.subTest(at=instant):
                items = {item["serials"][0]: item for item in self.triage(client, instant)}
                east, west = items[mississauga], items[regina]
                self.assertEqual((east["priority"], west["priority"]), (east_priority, west_priority))
                if datetime.fromisoformat(instant) <= datetime.fromisoformat("2026-11-01T11:00:00Z"):
                    self.assertIn("2026-11-01 06:00:00-05:00", east["reasons"][-1])
                    self.assertIn("2026-11-01 06:00:00-06:00", west["reasons"][-1])
                self.assertFalse(any("06:00:00-04:00" in reason for reason in east["reasons"]))

    def test_prolonged_uncertainty_targets_scheduled_use_and_stale_replay_cannot_clear_it(self):
        soon = self.device("Booked-fix")
        idle = self.device("Idle-fix")
        empty = self.device("Unseen")
        parked = self.device("Parked")
        for serial in (soon, empty, parked):
            self.job(serial, 2700, 3600)
        client = self.client()
        self.ingest(client,
            self.fix(soon, 0, event_id="credible-fix"), self.fix(idle, 0), self.fix(parked, 5, ignition=False),
            self.fix(soon, 100, received=800, event_id="old-buffered-fix"),
            self.fix(soon, 950, received=1000, event_id="new-fix"),
        )
        self.assertEqual(self.triage(client, 720), [])
        opened, = self.triage(client, 721)
        delayed, = self.triage(client, 800)
        self.assertEqual(opened["item_id"], delayed["item_id"])
        self.assertEqual((delayed["serials"], delayed["likely_cause"], delayed["who_acts"], delayed["priority"]),
                         ([soon], "unknown", "support", "medium"))
        self.assertTrue({"credible-fix", "old-buffered-fix"}.issubset(delayed["evidence"]))
        self.assertNotIn("new-fix", delayed["evidence"])
        self.status(client, 800, soon, delayed)
        self.assertEqual(self.status(client, 800, empty)["state"], "unknown")
        self.assertEqual(self.status(client, 800, parked)["likely_cause"], "parked_normal")
        self.assertEqual(self.triage(client, 1000), [])
        self.assertEqual(self.status(client, 1000, soon)["state"], "reporting")

    def test_prolonged_daily_and_camera_silence_follow_up_without_guessing_ignition(self):
        camera = self.device("Independent-video", "C")
        tag = self.device("Booked-tag", "A")
        no_work = self.device("Unbooked-tag", "A")
        sleeping = self.device("Known-asleep", "C")
        for serial in (camera, tag, sleeping):
            self.job(serial, 181_000, 184_000)
        client = self.client()
        self.ingest(client,
            self.tag(tag, 0, 64), self.tag(no_work, 0, 64),
            self.camera(camera, 178_800, "recording"), self.camera(camera, 179_400, "booting"),
            self.camera(sleeping, 178_800, "sleeping"),
        )
        self.assertEqual(self.triage(client, 180_000), [])
        results = {item["serials"][0]: item for item in self.triage(client, 180_001)}
        self.assertEqual(set(results), {tag, camera})
        for serial in results:
            item = results[serial]
            self.assertEqual((item["likely_cause"], item["who_acts"], item["priority"]), ("unknown", "support", "medium"))
            self.status(client, 180_001, serial, item)

    def test_remote_response_budget_recovery_and_recurrence(self):
        road = [self.device("Paired-fast"), self.device("Paired-slack")]
        early = self.device("Urgent-video", "C", paired=road[0])
        slack = self.device("Grace-video", "C", paired=road[1])
        self.job(early, 700, 1300)
        self.job(slack, 701, 1301)
        client = self.client()
        command = {"command": "reboot", "issued_by": "support"}
        first = self.frame(early, "command", 100, command, event_id="first-reboot")
        self.ingest(client,
            *[self.fix(serial, time) for serial in road for time in (0, 290, 585, 880, 1175, 1390)],
            self.camera(early, 50, "storage_error", event_id="original-storage"),
            self.camera(slack, 50, "storage_error"),
            first, first | {"event_id": "retry-only", "received_at": self.at(180)},
            self.frame(slack, "command", 100, command),
            self.frame(early, "command", 800, command, event_id="second-reboot"),
            self.camera(early, 1500, "recording", received=1510),
            self.camera(early, 1600, "storage_error"),
        )
        pending = {item["serials"][0]: item for item in self.triage(client, 501)}
        self.assertEqual((pending[early]["priority"], pending[slack]["priority"]), ("high", "medium"))
        self.assertEqual(pending[early]["who_acts"], "support")
        self.assertIn(self.at(700), pending[early]["reasons"][0])
        self.assertIn("response window", pending[early]["next_action"])
        changed = {item["serials"][0]: item for item in self.triage(client, 1400)}[early]
        self.assertEqual(changed["who_acts"], "technician")
        self.assertEqual(changed["item_id"], pending[early]["item_id"])
        self.assertTrue({"original-storage", "first-reboot", "second-reboot"}.issubset(changed["evidence"]))
        self.assertNotIn("retry-only", changed["evidence"])
        self.status(client, 1400, early, changed)
        self.assertFalse(any(early in item["serials"] for item in self.triage(client, 1510)))
        recurred = {item["serials"][0]: item for item in self.triage(client, 1600)}[early]
        self.assertEqual(recurred["who_acts"], "support")
        self.assertNotEqual(recurred["item_id"], changed["item_id"])

    def test_item_ids_survive_plan_updates_and_queue_orders_by_deadline_then_ties(self):
        later = self.device("A-later")
        earlier = self.device("Z-earlier")
        tie = self.device("Y-tie")
        unscheduled = self.device("Unscheduled")
        account = self.device("Account-only")
        for serial, start in ((later, 900), (earlier, 800), (tie, 800)):
            self.job(serial, start, 1400)
        client = self.client()
        events = [self.frame(serial, "power_disconnect", 8) for serial in (tie, unscheduled, earlier, later)]
        events.extend(self.plan(account, when, status) for when, status in ((0, "paused"), (19, "ended"), (30, "active"), (40, "paused")))
        self.ingest(client, *reversed(events))
        store = client.app.state.runtime.store
        original_counts = store.counts()
        first = self.triage(client, 18)
        self.assertEqual([item["serials"][0] for item in first], [tie, earlier, later, unscheduled, account])
        self.assertEqual([item["priority"] for item in first], ["high", "high", "high", "medium", "low"])
        self.assertEqual(self.triage(client, 18), first)
        self.assertEqual(store.counts(), original_counts)
        updated = self.triage(client, 19)[-1]
        self.assertEqual(updated["item_id"], first[-1]["item_id"])
        self.assertIn("ended", updated["reasons"][0])
        self.assertFalse(any(account in item["serials"] for item in self.triage(client, 30)))
        resumed = self.triage(client, 40)[-1]
        self.assertNotEqual(resumed["item_id"], updated["item_id"])
        self.assertEqual(self.triage(client, 18), first)

    def test_partial_carrier_recovery_recomputes_urgency_for_remaining_jobs(self):
        lost = [self.device(f"Route-{index}", depot="REG") for index in range(5)]
        live = [self.device(f"Probe-{index}", depot="REG", carrier="Driftwood") for index in range(3)]
        self.job(lost[-1], 600, 1400)
        client = self.client()
        self.ingest(client,
            *[self.fix(serial, 0) for serial in lost], *[self.fix(serial, 360) for serial in live],
            *[self.fix(serial, 560) for serial in lost[:3]],
            *[self.frame(serial, "ignition_off", 600) for serial in lost[:3] + live],
        )
        broad, = self.triage(client, 420)
        active, = self.triage(client, 600)
        ended, = self.triage(client, 1400)
        self.assertEqual((broad["priority"], active["priority"], ended["priority"]), ("high", "high", "medium"))
        self.assertEqual(broad["serials"], sorted(lost))
        self.assertEqual(active["serials"], sorted(lost[3:]))
        self.assertEqual({item["item_id"] for item in (broad, active, ended)}, {broad["item_id"]})
        self.assertIn("in progress", active["reasons"][-1])
        self.status(client, 600, lost[-1], active)

    def test_sleep_cold_parked_and_approved_downtime_are_suppressed_even_with_jobs(self):
        parked = self.device("Ignition-off")
        camera = self.device("Sleeping", "C", paired=parked)
        cold = self.device("Cold-battery", "A", "REG")
        downtime = self.device("Approved-idle", "A")
        self.append("weather", ("2026-11-01", "REG", "-14", "-3"))
        for serial in (parked, cold, downtime):
            self.job(serial, 97_200, 101_000)
        config = json.loads(RULES.read_text())
        config["operational_assumptions"]["seasonal_downtime_suppression_enabled"]["value"] = True
        config["site_policy"] = {"downtime": [{
            "asset_ids": [self.assets[downtime][0]], "depot": "MSS",
            "start_local": "2026-10-31", "end_local": "2026-11-03", "provenance": "Synthetic authorization",
        }]}
        path = self.data.parent / "rules.json"
        path.write_text(json.dumps(config))
        client = self.client(config=path)
        self.ingest(client,
            self.fix(parked, 95_000, ignition=False), self.camera(camera, 95_901, "sleeping"),
            self.tag(cold, 0, 71), self.tag(downtime, 0, 70),
        )
        self.assertEqual(self.triage(client, 97_200), [])
        for serial, cause in ((parked, "parked_normal"), (camera, "sleeping_by_design"),
                              (cold, "cold_weather"), (downtime, "planned_downtime")):
            state = self.status(client, 97_200, serial)
            self.assertEqual((state["state"], state["likely_cause"]), ("quiet_expected", cause))
