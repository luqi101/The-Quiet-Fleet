"""Exercise the release verifier over real loopback HTTP."""

import json
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from scripts import verify
from test_http_foundation import TRACKER, write_references


class ProcessLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data = self.root / "data"
        write_references(self.data)
        with socket.socket() as probe:
            probe.bind((verify.HOST, 0))
            port = probe.getsockname()[1]
        self.args = SimpleNamespace(data=self.data, out=self.root / "reports", persona="support",
                                    startup_timeout=8, exam_timeout=20, port=port)

    def run_mode(self, mode):
        with redirect_stdout(StringIO()):
            code, run = verify.verify(mode, self.args)
        summary = json.loads((run / "summary.json").read_text())
        self.assertEqual(code, 0, summary)
        return run, summary

    def test_entrypoint_uses_reference_only_directory_and_restarts_empty_with_egress_denied(self):
        run, summary = self.run_mode("offline")
        self.assertEqual(len(list((run / "references").iterdir())), 6)
        self.assertEqual(len({service["pid"] for service in summary["services"]}), 2)
        self.assertIn("Python socket and DNS audit guard", summary["isolation"])
        for service in summary["services"]:
            self.assertTrue(service["initial_store"])
            self.assertFalse(any(service["initial_store"].values()))
            self.assertGreater(service["peak_rss_mib"], 0)

    def test_original_vendor_requests_and_anomaly_counters_reconcile(self):
        telemetry = self.data / "telemetry"
        telemetry.mkdir()
        at = "2026-10-04T12:00:00Z"
        event = {
            "event_id": "release-preflight-fixture", "serial": TRACKER, "type": "position",
            "received_at": at, "device_time": at,
            "payload": {"ignition": True, "lat": 43, "lng": -79, "speed_kmh": 25},
        }
        (telemetry / "test.jsonl").write_text(json.dumps(event) + "\n")
        run, summary = self.run_mode("preflight")
        self.assertEqual(summary["exam_exit_code"], 0)
        self.assertEqual(summary["checks"], {"passed": 10, "total": 10})
        self.assertEqual(summary["warnings"], [])
        self.assertEqual(summary["http"]["batch_counters"], {
            "accepted": 4, "inserted": 1, "retries": 2, "ignored": 1, "malformed": 3, "conflicts": 0,
        })
        rows = [json.loads(line) for line in (run / "requests.jsonl").read_text().splitlines()]
        self.assertTrue(any(row["path"] == "/ingest" and row["status"] == 400 for row in rows))

    def test_port_check_leaves_the_existing_listener_alive(self):
        with socket.socket() as listener:
            listener.bind((verify.HOST, 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(verify.VerificationError, "Existing listeners"):
                verify.check_port(port)
            with socket.create_connection((verify.HOST, port), timeout=1):
                self.assertEqual(listener.getsockname()[1], port)
