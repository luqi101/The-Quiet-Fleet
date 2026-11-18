"""Exercise the documented entrypoint over a real loopback connection."""

import errno
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode

from test_http_foundation import ROOT, TRACKER, write_references


PORT = 8080
GUARD = """
import ipaddress
import socket
import sys

def check_host(host):
    if host is None or host == "localhost":
        return
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise PermissionError("external Python network access denied in smoke test")

def guard(event, args):
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        sock, address = args[:2]
        if sock.family in (socket.AF_INET, socket.AF_INET6) and address is not None:
            check_host(address[0])
    elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"):
        host = args[0][0] if event == "socket.getnameinfo" else args[0]
        check_host(host)

sys.addaudithook(guard)
try:
    socket.getaddrinfo("example.invalid", 443)
except PermissionError:
    print("Smoke test Python network guard active", flush=True)
else:
    raise RuntimeError("Smoke test network guard is inactive")
"""


def request(method, path, payload=None):
    connection = HTTPConnection("127.0.0.1", PORT, timeout=1)
    try:
        data = None if payload is None else json.dumps(payload)
        connection.request(method, path, body=data, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


class ProcessLifecycleTest(unittest.TestCase):
    def setUp(self):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", PORT))
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise
                self.skipTest("The documented loopback port 8080 is already in use.")

        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        data = self.root / "references"
        write_references(data)
        (self.root / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
        self.env = os.environ | {"QF_DATA_DIR": str(data), "PYTHONPATH": str(self.root)}

    @contextmanager
    def running_service(self, label):
        log = self.root / f"{label}.log"
        with log.open("wb") as output, subprocess.Popen(
            [sys.executable, "-B", "-m", "quiet_fleet"], cwd=ROOT, env=self.env,
            stdout=output, stderr=subprocess.STDOUT,
        ) as process:
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        if request("GET", "/health") == (200, {"status": "ok"}):
                            break
                    except OSError:
                        pass
                    time.sleep(0.05)
                else:
                    self.fail(f"Service did not become ready.\n{log.read_text()}")
                self.assertIn("Smoke test Python network guard active", log.read_text())
                self.assertIsNone(process.poll())
                yield
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def test_entrypoint_uses_reference_only_directory_and_restarts_empty_with_egress_denied(self):
        at = "2026-11-01T15:00:00Z"
        query = "?" + urlencode({"at": at})
        status = f"/devices/{TRACKER}/status{query}"
        triage = f"/triage{query}"
        with self.running_service("first"):
            self.assertEqual(request("GET", "/health"), (200, {"status": "ok"}))
            self.assertEqual(request("GET", "/docs")[0], 404)
            self.assertEqual(request("GET", "/redoc")[0], 404)
            self.assertEqual(request("GET", "/openapi.json")[0], 200)
            code, first = request("GET", status)
            self.assertEqual((code, first["state"], first["last_heard_at"], first["evidence"]), (200, "unknown", None, []))
            self.assertEqual(request("GET", triage), (200, {"at": at, "items": []}))
            event = {
                "event_id": "loopback-power-disconnect", "type": "power_disconnect", "serial": TRACKER,
                "device_time": at, "received_at": at, "payload": {},
            }
            self.assertEqual(request("POST", "/ingest", {"events": [event]}), (200, {"accepted": 1}))
            code, after = request("GET", status)
            self.assertEqual((code, after["state"], after["likely_cause"], after["last_heard_at"], after["evidence"]),
                             (200, "needs_action", "power_loss", at, ["loopback-power-disconnect"]))
            code, queue = request("GET", triage)
            self.assertEqual(code, 200)
            item, = queue["items"]
            self.assertEqual((item["serials"], item["who_acts"], item["evidence"]),
                             ([TRACKER], "technician", ["loopback-power-disconnect"]))

        with self.running_service("restarted"):
            self.assertEqual(request("GET", status), (200, first))
            self.assertEqual(request("GET", triage), (200, {"at": at, "items": []}))
