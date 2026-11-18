import csv
import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from scripts.audit_data import _case_audit, decode_bx, open_dataset, parse_time
from scripts.battery_analysis import Reading, credible_recoveries, latest_available, select_daily, stale_opportunities
from scripts.outage_analysis import evaluation_labels, onset_windows


class OfflineAnalysisTest(unittest.TestCase):
    def test_timestamp_offsets_and_epoch_units(self):
        instant = parse_time("2026-10-12T14:30:00Z")[0]
        self.assertEqual(parse_time("2026-10-12T10:30:00-04:00")[0], instant)
        self.assertEqual(parse_time(int(instant), allow_epoch=True), (instant, "epoch_seconds"))
        for invalid in (True, "2026-10-12T14:30:00", float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_time(invalid, allow_epoch=True)

    def test_bx_anchor_and_unknown_bits(self):
        wire = {"u": "BX40471", "t": "6ADA16E0", "b": 3094, "s": 12, "p": "5042719,-10456695"}
        unit, observed, decoded = decode_bx(json.dumps(wire))
        self.assertEqual(unit, "BX40471")
        self.assertEqual(datetime.fromtimestamp(observed, UTC).isoformat(), "2026-10-22T14:00:00+00:00")
        self.assertEqual(round(decoded["battery_pct"]), 76)
        self.assertEqual((decoded["lat"], decoded["lng"]), (50.42719, -104.56695))
        self.assertTrue(decoded["gps_fix"])
        self.assertFalse(decoded["low_battery"])
        self.assertEqual(decoded["unknown_flags"], 4)
        with self.assertRaises(ValueError):
            decode_bx(json.dumps(wire | {"b": True}))

    def test_audit_deduplicates_and_preserves_earliest_original_receipt(self):
        real_data = Path(__file__).resolve().parents[1] / "data"
        with (real_data / "devices.csv").open(encoding="utf-8", newline="") as source:
            serial = next(row["serial"] for row in csv.DictReader(source) if row["family"] == "T")
        with tempfile.TemporaryDirectory() as scratch:
            data = Path(scratch)
            for source in real_data.glob("*.csv"):
                shutil.copyfile(source, data / source.name)
            (data / "telemetry").mkdir()
            first = {
                "event_id": "qf-first-id",
                "serial": serial,
                "type": "position",
                "received_at": "2026-10-04T12:09:00Z",
                "device_time": "2026-10-04T12:00:00Z",
                "payload": {"lat": 50.1, "lng": -104.5, "speed_kmh": 10, "ignition": True},
            }
            alias = first | {
                "event_id": "qf-earlier-alias",
                "received_at": "2026-10-04T12:00:03Z",
                "device_time": "2026-10-04T08:00:00-04:00",
                "payload": dict(reversed(list(first["payload"].items()))),
            }
            conflict = first | {"payload": first["payload"] | {"ignition": False}}
            next_reading = first | {
                "event_id": "qf-next-reading",
                "device_time": "2026-10-04T12:02:00Z",
                "received_at": "2026-10-04T12:02:02Z",
            }
            path = data / "telemetry" / "2026-10-04.jsonl"
            path.write_text(
                "\n".join(map(json.dumps, (first, first, alias, conflict, {}, next_reading))) + "\n",
                encoding="utf-8",
            )
            with open_dataset(data) as (conn, _, report):
                audit = report["telemetry"]
                self.assertEqual(audit["malformed_envelopes"], 1)
                self.assertEqual(audit["duplicates"]["logical_observations"], 2)
                self.assertEqual(audit["duplicates"]["semantic_retry_excess"], 2)
                self.assertEqual(audit["duplicates"]["new_id_alias_excess"], 1)
                self.assertEqual(audit["duplicates"]["conflicting_event_id_envelopes"], 1)
                rows = conn.execute("SELECT event_id, payload, received FROM events ORDER BY observed").fetchall()
                self.assertEqual([row["event_id"] for row in rows], ["qf-earlier-alias", "qf-next-reading"])
                self.assertTrue(json.loads(rows[0]["payload"])["ignition"])
                self.assertEqual(rows[0]["received"], parse_time(alias["received_at"])[0])

    def test_delayed_battery_recovery_is_an_outcome_only(self):
        low = Reading(100, 102, 10)
        stale_low = Reading(90, 120, 8)
        recovery = Reading(200, 300, 55)
        reopening_replay = Reading(150, 350, 5)
        self.assertEqual(latest_available([stale_low, low, recovery], 250), low)
        self.assertEqual(list(stale_opportunities([low, recovery], 150, 400)), [(low, 250, recovery), (recovery, 350, None)])
        observed, still_open = credible_recoveries(
            [low, stale_low, recovery, reopening_replay], lambda row: row.percent <= 10,
            lambda row: row.percent >= 20,
        )
        self.assertEqual(observed, [(low, recovery)])
        self.assertEqual(still_open, 0)

    def test_daily_selection_uses_jitter_and_fails_open_when_sample_is_empty(self):
        deadline, evidence = select_daily([86_400, 88_800])
        self.assertEqual(deadline, 93_600)
        self.assertIn("development", evidence)
        self.assertIn("provisional", select_daily([])[1])

    def test_outage_onset_window_requires_clustered_distinct_reporters(self):
        onsets = [0, 10, 20, 30, 240, 1000]
        self.assertEqual(onset_windows(onsets, 240), [(5, 0, 240)])
        self.assertEqual(onset_windows(onsets, 239), [])

    def test_negative_case_duration_stays_visible_and_is_excluded_from_duration_labels(self):
        case = {
            "case_id": "valid-case", "serial": "T-fake", "depot": "REG", "root_cause": "carrier_outage",
            "action": "carrier_referral", "outcome": "closed", "notes": "Orchard Mobile interruption",
            "opened_at": "2026-11-01T05:30:00Z", "closed_at": "2026-11-01T06:00:00Z",
        }
        invalid = case | {"case_id": "backwards-case", "closed_at": "2026-11-01T05:15:00Z"}
        rows = [case, invalid]
        report = _case_audit(rows, {})
        self.assertEqual(report["invalid_durations"], [{
            "case_id": "backwards-case", "opened_at": "2026-11-01T05:30:00Z",
            "closed_at": "2026-11-01T05:15:00Z", "duration_seconds": -900,
        }])
        self.assertEqual(report["by_cause"], {"carrier_outage": 2})
        label, = evaluation_labels({"support_cases": rows}, {"Orchard Mobile"})
        self.assertEqual((label.case_id, label.end - label.start), ("valid-case", 1800))


if __name__ == "__main__":
    unittest.main()
