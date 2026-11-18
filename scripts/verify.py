"""Run one release check against a fresh local Quiet Fleet process."""

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "quiet-fleet"
RUNNER = VENDOR / "exam" / "qf_exam.py"
HOST, PORT = "127.0.0.1", 8080
BATCH_LIMIT = 5_000
HTTP_LIMIT = 10
MODES = ("preflight", "practice", "offline")
BOUND_LOG = f"Uvicorn running on http://{HOST}:{PORT}"
GUARD_LOG = "Quiet Fleet verification denied external socket, DNS and corpus probes"
INGEST_LOG = re.compile(
    r"^Ingest batch: accepted=(\d+) inserted=(\d+) retries=(\d+) ignored=(\d+) malformed=(\d+) conflicts=(\d+)$",
    re.MULTILINE,
)
MAC_PROFILE = '(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote ip "localhost:*"))'


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_vendor():
    hashes = {}
    for entry in (VENDOR / "SHA256SUMS").read_text().splitlines():
        expected, name = entry.split(maxsplit=1)
        require(sha256(VENDOR / name) == expected, f"Vendor SHA-256 mismatch for {name}")
        hashes[name] = expected
    require({"exam/qf_exam.py", "exam/practice.json"} <= hashes.keys(), "Vendor manifest omits the exam sources")
    return hashes


def runtime_digest():
    paths = sorted((ROOT / "quiet_fleet").glob("**/*.py")) + [ROOT / "config/rules.json", ROOT / "requirements.txt"]
    fingerprints = "".join(f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n" for path in paths)
    return hashlib.sha256(fingerprints.encode()).hexdigest()


def request(method, path, *, body=None, timeout=5):
    with closing(HTTPConnection(HOST, PORT, timeout=timeout)) as connection:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        with connection.getresponse() as response:
            return response.status, json.load(response)


def check_port():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, PORT))
        except OSError as exc:
            raise VerificationError(f"Cannot reserve {HOST}:{PORT}. Existing listeners are left alone. {exc}") from exc


def wait_ready(server, log, deadline):
    while server.poll() is None and (remaining := deadline - time.monotonic()) > 0:
        # Uvicorn logs this only after this child binds the port. If a separate
        # process wins the bind race, never send it a verification request.
        if BOUND_LOG in log.read_text():
            try:
                if request("GET", "/health", timeout=min(1, remaining)) == (200, {"status": "ok"}):
                    require(server.poll() is None, "The service exited during readiness")
                    return
            except OSError:
                pass
        time.sleep(min(0.05, remaining))
    raise VerificationError(f"Service failed to reach readiness. See {log}")


def stop_service(server, result):
    # wait4 measures this particular child on macOS/Linux, independent of the
    # exam client or previous children started by the same verifier.
    if server.returncode is None:
        server.send_signal(signal.SIGINT)
    deadline = time.monotonic() + 8
    while server.returncode is None:
        pid, status, usage = os.wait4(server.pid, os.WNOHANG)
        if pid:
            server.returncode = os.waitstatus_to_exitcode(status)
            unit = 1024 ** 2 if sys.platform == "darwin" else 1024
            result["peak_rss_mib"] = round(usage.ru_maxrss / unit, 3)
            break
        if time.monotonic() >= deadline:
            result["forced_stop"] = True
            server.kill()
            server.wait(timeout=5)
            break
        time.sleep(0.05)
    result["exit_code"] = server.returncode


def child_environment(run, hook, **variables):
    hook_path = run / hook
    hook_path.mkdir()
    (hook_path / "sitecustomize.py").write_text(
        f"from scripts.verify_hooks import {hook}\n{hook}()\n", encoding="utf-8",
    )
    return os.environ | variables | {"PYTHONPATH": os.pathsep.join((str(hook_path), str(ROOT)))}


def database_connection(store_dir):
    paths = list(store_dir.glob("quiet-fleet-*/telemetry.sqlite3"))
    require(len(paths) == 1, f"Expected one owned temporary database in {store_dir}")
    return closing(sqlite3.connect(f"{paths[0].as_uri()}?mode=ro", uri=True))


def store_counts(db):
    total = db.execute(
        """SELECT (SELECT COUNT(*) FROM messages),
                  (SELECT COUNT(*) FROM event_ids), (SELECT COUNT(*) FROM receipts)"""
    ).fetchone()
    return dict(zip(("logical_messages", "original_event_ids", "stored_id_receipts"), total))


@contextmanager
def service(run, data, startup_timeout, result, *, offline=False, prefix=()):
    check_port()
    command = [*prefix, sys.executable, "-B", "-m", "quiet_fleet"]
    log = run / "service.log"
    with tempfile.TemporaryDirectory(dir=run, prefix="store-") as directory, log.open("xb") as logfile:
        env = child_environment(run, "install_service_hooks", QF_VERIFY_STORE_DIR=directory, QF_DATA_DIR=str(data))
        if offline:
            env["QF_VERIFY_BLOCKED_FILES"] = json.dumps([str(data / "telemetry"), str(ROOT / "data" / "telemetry")])
        started = time.monotonic()
        result["command"] = command
        with subprocess.Popen(command, cwd=ROOT, env=env, stdout=logfile, stderr=subprocess.STDOUT) as server:
            result["pid"] = server.pid
            try:
                wait_ready(server, log, started + startup_timeout)
                result["startup_seconds"] = round(time.monotonic() - started, 6)
                if offline:
                    require(GUARD_LOG in log.read_text(), "The service did not verify its Python offline guard")
                with database_connection(Path(directory)) as db:
                    result["initial_store"] = store_counts(db)
                    require(not any(result["initial_store"].values()), "New service started with telemetry")
                    yield db
                require(server.poll() is None, f"Service exited unexpectedly with code {server.returncode}")
            finally:
                stop_service(server, result)
    require(not result.get("forced_stop") and result["exit_code"] in (0, -signal.SIGINT),
            f"Service shutdown returned {result['exit_code']}. See {log}")


def durations(timings):
    ordered = sorted(timings)
    return {
        **{f"p{p}": round(ordered[math.ceil(len(ordered) * p / 100) - 1], 6) for p in (50, 95, 99)},
        "max": round(ordered[-1], 6),
        "total": round(sum(ordered), 6),
    }


def summarize_http(records, log, db):
    requests = [row for row in records if "sent" in row]
    stats = [tuple(map(int, fields)) for fields in INGEST_LOG.findall(log)]
    require(len(requests) == len(stats) and requests, "HTTP requests and service ingest logs did not reconcile")
    for row, (accepted, inserted, retries, ignored, malformed, conflicts) in zip(requests, stats):
        require(row["status"] == 200 and type(row["accepted"]) is int and row["accepted"] == accepted
                and accepted == inserted + retries + ignored and row["sent"] == accepted + malformed + conflicts,
                "An ingest request did not reconcile with its service counters")
    names = ("accepted", "inserted", "retries", "ignored", "malformed", "conflicts")
    counters = dict(zip(names, map(sum, zip(*stats))))
    stored = store_counts(db)
    require(counters["inserted"] == stored["logical_messages"], "Insert counters disagree with the database")
    total_events = sum(row["sent"] for row in requests)
    known = counters["inserted"] + counters["retries"]
    stored["repeated_event_ids"] = known - stored["original_event_ids"]
    stored["new_id_aliases"] = stored["original_event_ids"] - stored["logical_messages"]
    stored["clock_ahead_messages"] = db.execute(
        "SELECT COUNT(*) FROM messages WHERE time_quality = 'clock_ahead'"
    ).fetchone()[0]
    stored["bx_messages"] = db.execute("SELECT COUNT(*) FROM messages WHERE raw_type = 'bx_raw'").fetchone()[0]
    return {
        "envelopes": total_events,
        "batches": len(requests),
        "batch_sizes": dict(sorted(Counter(row["sent"] for row in requests).items())),
        "batch_counters": counters,
        "store": stored,
        "ingest_http_seconds": durations([row["seconds"] for row in requests]),
        "batches_at_or_above_10_seconds": sum(row["seconds"] >= HTTP_LIMIT for row in requests),
        "queries": [
            {**row, "seconds": round(row["seconds"], 6)}
            for row in records if row["method"] == "GET" and row["path"] != "/health"
        ],
    }


def audit_evidence(run, db):
    count = 0
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for path in sorted(run.glob("*.json")):
        body = json.loads(path.read_text())
        if not isinstance(body, dict) or "at" not in body:
            continue
        cutoff = (datetime.fromisoformat(body["at"]) - epoch) // timedelta(microseconds=1)
        for item in body.get("items", [body]):
            for event_id in item["evidence"]:
                eligible = db.execute(
                    "SELECT 1 FROM receipts WHERE event_id = ? AND received_us <= ? LIMIT 1",
                    (event_id, cutoff),
                ).fetchone()
                require(eligible, f"{path.name} cites an ineligible receipt: {event_id}")
                count += 1
    return count


def run_exam(mode, args, run, result):
    result["vendor_sha256"] = verify_vendor()
    if not any((args.data / "telemetry").glob("*.jsonl")):
        raise VerificationError("The vendor exam requires telemetry/*.jsonl under --data")
    server_result = result["service"] = {}
    request_log = run / "requests.jsonl"
    exam_log = run / "exam.log"
    with service(run, args.data, args.startup_timeout, server_result) as db:
        env = child_environment(
            run, "install_exam_observer", QF_VERIFY_EXAM_SOURCE=str(RUNNER), QF_VERIFY_REQUEST_LOG=str(request_log),
            NO_PROXY="localhost,127.0.0.1", no_proxy="localhost,127.0.0.1",
        )
        command = [
            sys.executable, "-B", "-u", str(RUNNER), mode,
            "--data", str(args.data), "--persona", args.persona, "--out", str(run),
            "--url", f"http://{HOST}:{PORT}", "--batch", str(BATCH_LIMIT),
        ]
        result["exam_command"] = command
        started = time.monotonic()
        with exam_log.open("xb") as stream, subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
        ) as exam:
            try:
                result["exam_exit_code"] = exam.wait(timeout=args.exam_timeout)
            except subprocess.TimeoutExpired:
                exam.kill()
                result.update(exam_exit_code=exam.wait(), exam_timed_out=True)
            finally:
                if exam.poll() is None:
                    exam.kill()
                    result["exam_exit_code"] = exam.wait()
        result["exam_wall_seconds"] = round(time.monotonic() - started, 6)
        log = exam_log.read_text(errors="replace")
        result["checks"] = dict(zip(("passed", "total"), map(int, match.groups()))) if (
            match := re.search(r"(?m)^(\d+)/(\d+) checks passed", log)
        ) else None
        result["warnings"] = [line.strip()[6:] for line in log.splitlines() if line.strip().startswith("WARN  ")]
        result["failures"] = [line.strip()[6:] for line in log.splitlines() if line.strip().startswith("FAIL  ")]
        if request_log.exists():
            records = [json.loads(line) for line in request_log.read_text().splitlines()]
            result["http"] = summarize_http(records, (run / "service.log").read_text(), db)
        if result["exam_exit_code"] == 0:
            require(result.get("http") is not None and result["checks"] is not None, "The exam did not yield complete metrics")
            if mode == "practice":
                streamed = re.search(r"(?m)^Streamed ([\d,]+) events in (\d+)s\.", log)
                require(streamed and int(streamed[1].replace(",", "")) == result["http"]["envelopes"],
                        "The vendor's replay total did not match the recorded requests")
                result["vendor_stream_seconds"] = int(streamed[2])
            result["eligible_evidence_ids"] = audit_evidence(run, db)
    require(verify_vendor() == result["vendor_sha256"], "Vendor sources changed during the run")
    if result["exam_exit_code"]:
        return result["exam_exit_code"]
    require(result["http"]["batches_at_or_above_10_seconds"] == 0, "An ingest batch reached the 10-second limit")
    return 0


def write_smoke_references(source, destination):
    destination.mkdir()
    rows = {
        "assets": dict(asset_id="SMOKE-ASSET", type="van", depot="MSS", use="test", make_model="Test Vehicle",
                       year="2024", vin="1FTBW1X80RKA12345", status="active"),
        "devices": dict(serial="T-OFFLINE-VERIFY", family="T", model="T-series", firmware="1.0.0",
                        carrier="Test Carrier", asset_id="SMOKE-ASSET", status="active", installed_at="2024-01-01"),
        "schedule": None, "weather": None, "plan_changes": None, "support_cases": None,
    }
    for table, row in rows.items():
        name = f"{table}.csv"
        with (source / name).open(newline="", encoding="utf-8") as stream:
            columns = next(csv.reader(stream))
        with (destination / name).open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            if row is not None:
                writer.writerow(row)


def native_isolation(run, result):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        result["isolation"] = "Python socket and DNS audit guard"
        return ()
    profile = run / "loopback.sb"
    profile.write_text(MAC_PROFILE + "\n", encoding="utf-8")
    prefix = ("/usr/bin/sandbox-exec", "-f", str(profile))
    probe_code = """
import errno, socket, sys
with socket.socket() as client:
    client.settimeout(0.5)
    sys.exit(0 if client.connect_ex(("192.0.2.1", 443)) in (errno.EPERM, errno.EACCES) else 1)
"""
    with (run / "sandbox-probe.log").open("xb") as stream:
        probe = subprocess.run(
            [*prefix, sys.executable, "-I", "-c", probe_code],
            stdout=stream, stderr=subprocess.STDOUT, timeout=5, cwd=ROOT,
        )
    result["native_probe_exit_code"] = probe.returncode
    if probe.returncode == 0:
        result["isolation"] = "macOS OS outbound sandbox and Python socket and DNS audit guard"
        return prefix
    result["isolation"] = "Python socket and DNS audit guard (macOS sandbox probe failed)"
    return ()


def run_offline(args, run, result):
    references = run / "references"
    write_smoke_references(args.data, references)
    prefix = native_isolation(run, result)
    at = "2026-11-01T15:00:00Z"
    query = urlencode({"at": at})
    serial = "T-OFFLINE-VERIFY"
    status_path, queue_path = f"/devices/{serial}/status?{query}", f"/triage?{query}"
    reset = (200, {"at": at, "items": []})
    result["services"] = []
    first = None
    for stage in ("initial", "restarted"):
        child = run / stage
        child.mkdir()
        details = {}
        result["services"].append(details)
        with service(child, references, args.startup_timeout, details, offline=True, prefix=prefix):
            code, status = request("GET", status_path)
            require(code == 200 and status["asset_id"] == "SMOKE-ASSET"
                    and status["state"] == "unknown" and status["last_heard_at"] is None and not status["evidence"],
                    f"Unexpected initial status on {stage}")
            require(request("GET", queue_path) == reset, f"Triage was not empty on {stage}")
            if stage == "restarted":
                require(status == first, "Restarted process preserved ingest state")
                continue
            first = status
            for path, expected in (("/openapi.json", 200), ("/docs", 404), ("/redoc", 404)):
                require(request("GET", path)[0] == expected, f"Unexpected offline response on {path}")
            event_id = "verification-power-loss"
            event = {"event_id": event_id, "type": "power_disconnect", "serial": serial,
                     "device_time": at, "received_at": at, "payload": {}}
            require(request("POST", "/ingest", body={"events": [event]}) == (200, {"accepted": 1}), "Smoke ingest failed")
            code, observed = request("GET", status_path)
            require(code == 200 and observed["state"] == "needs_action" and observed["likely_cause"] == "power_loss"
                    and observed["last_heard_at"] == at and observed["evidence"] == [event_id],
                    "Ingest did not update the renamed device")
            code, queue = request("GET", queue_path)
            require(code == 200 and len(queue["items"]) == 1, "Offline triage should contain one item")
            item = queue["items"][0]
            require((item["serials"], item["who_acts"], item["evidence"]) == ([serial], "technician", [event_id]),
                    "Offline triage did not contain the expected technician item")
    require(result["services"][0]["pid"] != result["services"][1]["pid"], "Restart did not create a new process")
    return 0


def verify(mode, args):
    parent = args.out.resolve() / mode
    parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    print(f"{mode} verification logs in {run}", flush=True)
    digest = runtime_digest()
    result = {
        "mode": mode, "persona": args.persona, "data": str(args.data), "runtime_sha256": digest,
        "environment": {"python": platform.python_version(), "os": platform.platform(),
                        "macos": platform.mac_ver()[0] or None, "sqlite": sqlite3.sqlite_version},
        "exit_code": 1,
    }
    try:
        result["exit_code"] = run_offline(args, run, result) if mode == "offline" else run_exam(mode, args, run, result)
        require(runtime_digest() == digest, "Runtime source changed during verification")
    except (VerificationError, OSError, HTTPException, json.JSONDecodeError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
        result["exit_code"] = result.get("exam_exit_code") or 1
        print(str(exc), file=sys.stderr)
    finally:
        (run / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{mode} exit {result['exit_code']}", flush=True)
    return result["exit_code"], run


def add_arguments(parser):
    parser.add_argument("--data", type=lambda path: Path(path).resolve(), default=ROOT / "data",
                        help="Six reference CSVs, plus telemetry/ for vendor commands (default: checkout data/).")
    parser.add_argument("--persona", choices=("support",), default="support", help="Vendor persona (default: support).")
    parser.add_argument("--out", type=Path, default=ROOT / "reports",
                        help="Report root. Each check creates a fresh run directory (default: checkout reports/).")
    parser.add_argument("--startup-timeout", type=positive_seconds, default=15,
                        help="Readiness deadline in seconds (default: 15).")
    parser.add_argument("--exam-timeout", type=positive_seconds, default=900,
                        help="Vendor child deadline in seconds (default: 900).")


def positive_seconds(text):
    value = float(text)
    if value <= 0 or not math.isfinite(value):
        raise argparse.ArgumentTypeError("must be a finite positive number of seconds")
    return value


def process_exit(code):
    return code if code >= 0 else 128 - code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=MODES)
    add_arguments(parser)
    args = parser.parse_args()
    code, _ = verify(args.mode, args)
    return process_exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
