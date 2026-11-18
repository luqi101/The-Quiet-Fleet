import csv
import json
import math
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from evidence_client import AuditedClient as TestClient

from quiet_fleet.api import create_app
from quiet_fleet.bx import BX_REPORT, decode_bx
from quiet_fleet.config import load_config
from quiet_fleet.projection import project_device
from quiet_fleet.time_utils import from_epoch_us, to_epoch_us, utc_text
from test_http_foundation import RULES, TRACKER, write_references


ROOT = Path(__file__).resolve().parents[1]
HARDWARE = ROOT / "vendor/quiet-fleet/new_hardware"
RULES_CONFIG = load_config(RULES)
WIRE = RULES_CONFIG.wire_format_constants
UNIT = "BX70361"
BASE = datetime(2026, 11, 18, 14, tzinfo=UTC)


def at(seconds):
    return BASE + timedelta(seconds=seconds)


def payload(second, *, serial=UNIT, battery=3100, flags=8, point="5091234,-10471234"):
    return {"u": serial, "t": f"{int(at(second).timestamp()):X}", "b": battery, "s": flags, "p": point}


def envelope(event_id, observed, *, received=None, **fields):
    return {
        "event_id": event_id,
        "type": "bx_raw",
        "received_at": utc_text(at(observed if received is None else received)),
        "raw": json.dumps(payload(observed, **fields)),
    }


class DecodeBXTest(unittest.TestCase):
    def test_three_exact_portal_anchors_and_regina_time(self):
        anchors = (
            ("BX40471", "6ADA16E0", 3094, 8, "2026-10-22T14:00:00Z", 76, False, False, True, 50.42719, -104.56695),
            ("BX41085", "6AD8D76C", 2583, 9, "2026-10-21T15:17:00Z", 63, True, False, True, 50.43083, -104.66817),
            ("BX47068", "6AE4B4B0", 573, 10, "2026-10-30T15:16:00Z", 14, False, True, True, 50.46073, -104.67404),
        )
        with (HARDWARE / "portal_readout.csv").open(newline="") as file:
            portal = {row["unit"]: row for row in csv.DictReader(file)}
        with (HARDWARE / "bx_raw_messages.txt").open() as file:
            raw_messages = [json.loads(line) for line in file]
        self.assertEqual((len(raw_messages), len(portal)), (300, 3))
        zone = ZoneInfo("America/Regina")
        for serial, clock, b, flags, expected_utc, display, moving, low, gps, lat, lng in anchors:
            with self.subTest(serial=serial):
                raw, = [row for row in raw_messages if (row["u"], row["t"]) == (serial, clock)]
                self.assertEqual((raw["b"], raw["s"]), (b, flags))
                decoded = decode_bx(json.dumps(raw), WIRE)
                self.assertEqual((decoded.serial, decoded.clock_hex), (serial, clock))
                self.assertEqual(utc_text(from_epoch_us(decoded.observed_us)), expected_utc)
                self.assertEqual(decoded.payload["battery_pct"], 100 * b / 4095)
                self.assertEqual(math.floor(decoded.payload["battery_pct"] + 0.5), display)
                self.assertEqual(
                    tuple(decoded.payload[key] for key in ("moving", "low_battery", "gps_fix", "lat", "lng")),
                    (moving, low, gps, lat, lng),
                )
                local = from_epoch_us(decoded.observed_us).astimezone(zone)
                self.assertEqual(local.utcoffset(), timedelta(hours=-6))
                row = portal[serial]
                self.assertEqual(local.strftime("%Y-%m-%d %H:%M:%S"), row["last_report_portal_time"])
                self.assertEqual(f"{display}%", row["battery"])
                self.assertEqual(tuple(row[key] == "Yes" for key in ("moving", "low_battery", "gps_fix")), (moving, low, gps))
                self.assertEqual((float(row["latitude"]), float(row["longitude"])), (lat, lng))

    def test_independent_flags_unknown_bits_no_fix_and_inclusive_bounds(self):
        combinations = (
            (0, False, False, False, 0),
            (1, True, False, False, 0),
            (8, False, False, True, 0),
            (9, True, False, True, 0),
            (10, False, True, True, 0),
            (11, True, True, True, 0),
            (12, False, False, True, 4),
            (7, True, True, False, 4),
            (32 + 8 + 2, False, True, True, 32),
            ((1 << 65) + 4, False, False, False, (1 << 65) + 4),
        )
        for flags, moving, low, fix, unknown in combinations:
            with self.subTest(flags=flags):
                values = decode_bx(json.dumps(payload(0, battery=0, flags=flags, point="-9000000,+18000000")), WIRE).payload
                self.assertEqual(
                    tuple(values[key] for key in ("moving", "low_battery", "gps_fix", "unknown_flags", "flags")),
                    (moving, low, fix, unknown, flags),
                )
                self.assertEqual(values["coordinate_codes"], [-9_000_000, 18_000_000])
                self.assertEqual((values["lat"], values["lng"]), (-90.0, 180.0) if fix else (None, None))
                self.assertEqual(values["battery_pct"], 0)
        extended = decode_bx(json.dumps(payload(0, battery=4095) | {"revision_hint": {"new": True}}), WIRE).payload
        self.assertEqual(extended["battery_pct"], 100)
        self.assertEqual(extended["extra"], {"revision_hint": {"new": True}})


class BXHttpTest(unittest.TestCase):
    def setUp(self):
        self.data = Path(self.enterContext(tempfile.TemporaryDirectory())) / "data"
        write_references(self.data)
        self.add_unit(UNIT)

    def append(self, file, fields):
        with (self.data / f"{file}.csv").open("a", newline="") as output:
            csv.writer(output).writerow(fields)

    def add_unit(self, serial, *, installed="2026-11-17", status="active"):
        asset = f"Asset-{serial}"
        self.append("assets", (asset, "trailer", "REG", "service", "Trailer", "2025", "", "active"))
        self.append("devices", (serial, "BX", "BX-1", "fixture", "Driftwood", asset, status, installed))
        return asset

    def client(self, config=RULES):
        return self.enterContext(TestClient(create_app(self.data, config)))

    def post(self, client, *events, accepted=None):
        response = client.post("/ingest", json={"events": events})
        self.assertEqual((response.status_code, response.json()), (200, {"accepted": len(events) if accepted is None else accepted}))

    def status(self, client, second, state, cause, *, serial=UNIT):
        response = client.get(f"/devices/{serial}/status", params={"at": utc_text(at(second))})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["state"], body["likely_cause"]), (state, cause), body)
        return body

    def triage(self, client, second):
        response = client.get("/triage", params={"at": utc_text(at(second))})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def test_malformed_packets_and_unknown_or_wrong_family_serials_are_isolated(self):
        valid = payload(0)
        invalid_fields = {
            "u": [True, "", " BX70361", UNIT.lower(), "BX29999", TRACKER],
            "t": [False, 1, "bad-time", f"0x{valid['t']}", "1A", "FFFFFFFFFFFF", "6AD23_111", ""],
            "b": [False, -1, 4096, 15.5, "573", float("nan"), float("inf")],
            "s": [True, -1, 8.0, "8", float("inf")],
            "p": [False, [50, -104], "1", "1,2,3", "1,2.3", "1,NaN", "1_00,2", "-9000001,0", "0,18000001"],
        }
        invalid_payloads = [valid | {field: item} for field, items in invalid_fields.items() for item in items]
        invalid_payloads.extend({field: item for field, item in valid.items() if field != excluded} for excluded in valid)
        invalid_raw = [json.dumps(data) for data in invalid_payloads]
        invalid_raw.extend([
            [], {"u": UNIT}, None, "", "[]", "null", "{incomplete",
            json.dumps(valid)[:-1] + ', "b": 780}',
            json.dumps(valid)[:-1] + ', "extra": 1e10000}',
            json.dumps(valid | {"p": "9000001,0", "s": 0}),
        ])
        client = self.client()
        for index, raw in enumerate(invalid_raw):
            with self.subTest(raw=str(raw)[:80]):
                self.post(client, envelope(f"bad-{index}", 0) | {"raw": raw}, accepted=0)

        unknown = {"event_id": "unknown-kind", "type": "later_wire_kind", "received_at": utc_text(at(20))}
        tracker = {
            "event_id": "t-neighbor", "serial": TRACKER, "type": "position",
            "received_at": utc_text(at(20)), "device_time": utc_text(at(19)),
            "payload": {"lat": 51, "lng": -104, "speed_kmh": 2, "ignition": True},
        }
        self.post(
            client, envelope("wrong-outer-time", 1) | {"received_at": "no clock"},
            tracker, envelope("unparsable", 0) | {"raw": "{"},
            envelope("accepted-bx", 15), envelope("missing-raw", 0) | {"raw": None}, unknown,
            accepted=3,
        )
        self.assertEqual(client.app.state.runtime.store.counts().messages, 2)
        self.assertEqual(self.status(client, 20, "reporting", "none")["evidence"], ["accepted-bx"])
        self.assertEqual(self.status(client, 20, "reporting", "none", serial=TRACKER)["evidence"], ["t-neighbor"])
        self.assertEqual(client.get("/devices/BX29999/status", params={"at": utc_text(at(20))}).status_code, 404)

    def test_new_bx_frame_opens_a_real_issue_and_a_semantic_retry_cannot_refresh_it(self):
        client = self.client()
        self.assertIsNone(self.status(client, 0, "unknown", "unknown")["last_heard_at"])
        self.assertEqual(self.triage(client, 0), [])
        first = envelope("new-bx-flag", 10, received=15, battery=573, flags=0x46)
        self.post(client, first)
        self.assertEqual(self.status(client, 14, "unknown", "unknown")["evidence"], [])
        self.assertEqual(self.triage(client, 14), [])
        changed = self.status(client, 15, "needs_action", "battery_low")
        self.assertEqual((changed["asset_id"], changed["last_heard_at"], changed["evidence"]),
                         (f"Asset-{UNIT}", utc_text(at(15)), ["new-bx-flag"]))
        item, = self.triage(client, 15)
        self.assertEqual((item["serials"], item["likely_cause"], item["who_acts"], item["evidence"]),
                         ([UNIT], "battery_low", "technician", ["new-bx-flag"]))
        baseline = self.status(client, 1000, "needs_action", "battery_low")
        baseline_queue = self.triage(client, 1000)

        wire = json.loads(first["raw"])
        wire["t"] = "00" + wire["t"].lower()
        wire["p"] = "  +5091234, -10471234 "
        alias = first | {"event_id": "future-retry", "received_at": utc_text(at(900)),
                         "raw": json.dumps(dict(reversed(wire.items())), indent=1)}
        self.post(client, first, alias)
        self.assertEqual(self.status(client, 1000, "needs_action", "battery_low"), baseline)
        self.assertEqual(self.triage(client, 1000), baseline_queue)
        self.assertNotIn("future-retry", self.status(client, 600, "needs_action", "battery_low")["evidence"])
        store = client.app.state.runtime.store
        self.assertEqual(store.counts().messages, 1)
        event, = store.snapshot(to_epoch_us(at(1000)), UNIT)
        self.assertEqual((event.raw_type, event.kind, event.observed_us, event.time_quality),
                         ("bx_raw", BX_REPORT, to_epoch_us(at(10)), "credible"))
        self.assertEqual(json.loads(event.raw_device_time_json), json.loads(first["raw"])["t"])
        self.assertEqual(json.loads(event.payload_json)["unknown_flags"], 0x44)
        receipts = store.receipts_for("new-bx-flag", to_epoch_us(at(1000)))
        self.assertEqual([receipt.event_id for receipt in receipts], ["new-bx-flag", "future-retry"])
        self.assertEqual(json.loads(receipts[1].raw_device_time_json), wire["t"])
        self.post(client, first | {"raw": json.dumps(wire | {"s": 2})}, accepted=0)
        self.assertEqual(store.counts().conflicts, 1)
        self.assertEqual(self.triage(client, 1000), baseline_queue)

    def test_daily_bx_allowance_and_fresh_receipt_without_a_fix(self):
        deadline = RULES_CONFIG.calibrated_parameters.bx_daily_overdue.value
        prolonged = deadline + RULES_CONFIG.calibrated_parameters.bx_checkin_interval.value
        self.append("schedule", (
            "BX-use", f"Asset-{UNIT}", "REG", utc_text(at(prolonged + 600)), utc_text(at(prolonged + 1800)), "inspection",
        ))
        client = self.client()
        self.post(client, envelope("earlier-gps", -3600), envelope("no-fix-daily", 0, battery=164, flags=1))
        latest = self.status(client, 0, "reporting", "none")
        self.assertEqual(latest["last_heard_at"], utc_text(at(0)))
        self.assertIn("lacks a valid GPS fix", " ".join(latest["reasons"]))
        self.assertEqual(latest["evidence"], ["no-fix-daily", "earlier-gps"])
        store = client.app.state.runtime.store
        snapshot = store.snapshot(to_epoch_us(at(0)), UNIT)
        facts = project_device(to_epoch_us(at(0)), snapshot)
        self.assertEqual(facts.bx_valid_fix.event_id, "earlier-gps")
        self.assertEqual(facts.bx_report.event_id, "no-fix-daily")
        self.assertIsNone(json.loads(facts.bx_report.payload_json)["lat"])
        self.status(client, deadline, "reporting", "none")
        self.status(client, deadline + 1, "unknown", "unknown")
        self.assertEqual(self.triage(client, prolonged), [])
        item, = self.triage(client, prolonged + 1)
        self.assertEqual((item["likely_cause"], item["who_acts"], item["priority"]), ("unknown", "support", "medium"))
        self.status(client, prolonged + 1, "needs_action", "unknown")

    def test_battery_recovery_needs_a_strictly_later_clear_flag_and_threshold(self):
        client = self.client()
        self.post(
            client,
            envelope("first-low", 10, battery=573, flags=10),
            envelope("older-healthy-late", -60, received=800),
            envelope("clear-below-recovery", 600, battery=818, flags=8),
            envelope("same-time-clear", 900, battery=3000, flags=8),
            envelope("still-flagged", 900, received=904, battery=1000, flags=11),
            envelope("exact-recovery", 1000, received=1010, battery=819, flags=0),
            envelope("later-episode", 1200, battery=555, flags=2),
        )
        original, = self.triage(client, 10)
        below, = self.triage(client, 800)
        self.assertEqual(original["item_id"], below["item_id"])
        self.assertIn("clear-below-recovery", below["evidence"])
        self.assertIn("first-low", below["evidence"])
        self.assertEqual(self.status(client, 800, "needs_action", "battery_low")["last_heard_at"], utc_text(at(800)))
        self.status(client, 902, "reporting", "none")
        renewed, = self.triage(client, 904)
        self.assertEqual(renewed["item_id"], original["item_id"])
        almost = self.status(client, 1009, "needs_action", "battery_low")
        self.assertIn("still-flagged", almost["evidence"])
        self.assertNotIn("exact-recovery", almost["evidence"])
        recovered = self.status(client, 1010, "reporting", "none")
        self.assertEqual(self.triage(client, 1010), [])
        self.assertIn("lacks a valid GPS fix", " ".join(recovered["reasons"]))
        self.assertIn("exact-recovery", recovered["evidence"])
        again, = self.triage(client, 1200)
        self.assertNotEqual(again["item_id"], original["item_id"])

    def test_stock_and_preinstallation_receipts_do_not_open_in_service_faults(self):
        stock, future = "BX78022", "BX71227"
        self.add_unit(stock, status="stock")
        future_asset = self.add_unit(future, installed=utc_text(at(240)))
        client = self.client()
        self.post(
            client,
            envelope("stock-report", 30, serial=stock, battery=500, flags=2),
            envelope("preinstall-report", 20, received=120, serial=future, battery=573, flags=2),
            envelope("installed-report", 240, received=245, serial=future),
        )
        self.assertEqual(self.triage(client, 239), [])
        self.assertIsNone(self.status(client, 239, "unknown", "unknown", serial=stock)["asset_id"])
        before = self.status(client, 239, "unknown", "unknown", serial=future)
        self.assertEqual((before["asset_id"], before["last_heard_at"]), (None, utc_text(at(120))))
        after = self.status(client, 240, "unknown", "unknown", serial=future)
        self.assertEqual(after["asset_id"], future_asset)
        self.assertIn("before the recorded installation", " ".join(after["reasons"]))
        self.assertEqual(self.triage(client, 244), [])
        self.assertEqual(
            self.status(client, 245, "reporting", "none", serial=future)["evidence"],
            ["installed-report"],
        )

    def test_bx_observation_cutoff_and_untrusted_clock(self):
        client = self.client()
        ahead = envelope("future-clock", 100, received=99, flags=10, battery=573)
        self.post(client, ahead)
        first = self.status(client, 99, "unknown", "unknown")
        self.assertIn("clock ahead", " ".join(first["reasons"]))
        self.post(client, ahead | {"event_id": "clock-later-copy", "received_at": utc_text(at(130))})
        self.assertEqual(self.status(client, 130, "unknown", "unknown")["last_heard_at"], utc_text(at(99)))
        self.assertEqual(self.triage(client, 130), [])
        config = json.loads(RULES.read_text())
        config["defensive_limits"]["clock_ahead_tolerance"]["value"] = 1
        config_path = self.data.parent / "rules.json"
        config_path.write_text(json.dumps(config))
        permitting = self.client(config_path)
        self.post(permitting, ahead)
        self.status(permitting, 99, "unknown", "unknown")
        self.status(permitting, 100, "needs_action", "battery_low")
        self.assertEqual(self.triage(permitting, 99), [])
        self.assertEqual(self.triage(permitting, 100)[0]["evidence"], ["future-clock"])
