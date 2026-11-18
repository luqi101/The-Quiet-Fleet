"""Replay local JSONL files through a fresh Quiet Fleet process."""

import argparse
import itertools
import json
import math
import os
import platform
import resource
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = "127.0.0.1", 8080
BATCH_SIZE = 5_000


def input_lines(data_dir: Path):
    paths = sorted((data_dir / "telemetry").glob("*.jsonl"))
    if not paths:
        raise FileNotFoundError(f"No telemetry JSONL files in {data_dir / 'telemetry'}")
    for path in paths:
        with path.open("rb") as stream:
            for line in stream:
                if stripped := line.strip():
                    yield stripped


def request(opener, path, body=None):
    request = urllib.request.Request(
        f"http://{HOST}:{PORT}{path}", data=body, headers={"Content-Type": "application/json"}
    )
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def wait_for_health(server, opener):
    deadline = time.monotonic() + 15
    while server.poll() is None and time.monotonic() < deadline:
        try:
            if request(opener, "/health") == {"status": "ok"}:
                return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.05)
    raise RuntimeError("Benchmark server did not reach readiness")


def replay(data_dir, opener):
    timings = []
    accepted = sent = 0
    start = time.perf_counter()
    for batch in itertools.batched(input_lines(data_dir), BATCH_SIZE):
        body = b'{"events":[' + b",".join(batch) + b"]}"
        before = time.perf_counter()
        response = request(opener, "/ingest", body)
        timings.append(time.perf_counter() - before)
        count = response["accepted"]
        if type(count) is not int or not 0 <= count <= len(batch):
            raise ValueError(f"Invalid accepted count on request {len(timings)}: {count!r}")
        sent += len(batch)
        accepted += count
    if not timings:
        raise ValueError("The telemetry files contain no events")

    ordered = sorted(timings)
    return {
        "envelopes": sent,
        "accepted": accepted,
        "requests": len(timings),
        "full_requests": sent // BATCH_SIZE,
        "batch_size": BATCH_SIZE,
        "wall_seconds": round(time.perf_counter() - start, 6),
        "http_seconds": {
            **{f"p{pct}": round(ordered[math.ceil(len(ordered) * pct / 100) - 1], 6) for pct in (50, 95, 99)},
            "max": round(ordered[-1], 6),
        },
        "requests_at_or_above_10_seconds": sum(duration >= 10 for duration in timings),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="Optional JSON report destination.")
    args = parser.parse_args()
    data_dir = args.data.resolve()

    with socket.socket() as test:
        if test.connect_ex((HOST, PORT)) == 0:
            raise RuntimeError(f"Port {PORT} is in use. The benchmark did not start a process.")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    environment = dict(os.environ, QF_DATA_DIR=str(data_dir))
    with tempfile.TemporaryFile(mode="w+b") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "quiet_fleet"], cwd=ROOT, env=environment,
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            wait_for_health(server, opener)
            result = replay(data_dir, opener)
        except (OSError, RuntimeError, ValueError):
            log.seek(0)
            print(log.read().decode(errors="replace"), file=sys.stderr)
            raise
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()

    # macOS reports bytes. Linux reports KiB. The benchmark starts only the server child.
    rss_unit = 1024**2 if sys.platform == "darwin" else 1024
    result["server_peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / rss_unit, 3)
    result["python"] = platform.python_version()
    result["platform"] = platform.platform()
    report = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")
    return int(result["requests_at_or_above_10_seconds"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
