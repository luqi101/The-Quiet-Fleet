# The Quiet Fleet

## Install and start

From the checkout root, install the pinned dependencies once with Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Start the service from the same directory with the environment active.

```bash
python -m quiet_fleet
```

It serves HTTP on localhost:8080 with one worker. Startup uses the checked-in rules and six local reference CSVs. Each start creates a fresh empty temporary SQLite database.

```bash
curl -fsS http://localhost:8080/health
curl -fsS 'http://localhost:8080/triage?at=2026-10-12T14:05:12Z'
```

Set `QF_DATA_DIR` to read the references from another directory. The default is `./data`.

```bash
QF_DATA_DIR=/absolute/path/to/reference-data python -m quiet_fleet
```

The directory needs `assets.csv`, `devices.csv`, `schedule.csv`, `weather.csv`, `plan_changes.csv`, and `support_cases.csv`. Readiness follows successful validation. Telemetry arrives through `POST /ingest`. `/openapi.json` serves the schema locally.

## Current behavior

The support application distinguishes normal reporting, expected quiet, individual faults, and uncertainty across T trackers, C cameras, A tags, and BX trackers. BX check-ins use their decoded wire clock, battery flag, and valid-fix bit. `GET /devices/{serial}/status?at=…` explains the selected cause, applicable secondary constraints, and the suggested action. It returns original evidence IDs and the latest eligible unique device receipt as `last_heard_at`. Reporting deadlines use observation time. Devices without contact have a null `last_heard_at`. Both status and triage require an ISO timestamp with an explicit offset and output UTC with `Z`.

`GET /triage?at=…` groups synchronized reporting gaps by depot, carrier and reporting mode. Carrier-owned incidents recommend one consolidated customer update. A shared interruption with uncertain carrier ownership goes to support. Explicit physical and account faults remain individual items. Status and triage use the same diagnosis and action policy, and each serial appears at most once in triage. The queue prioritizes current work, actionable deadlines, and broad carrier incidents. It uses the next 06:00 depot-local shift when that shift has scheduled work and a provisional two-hour preparation window.

`POST /ingest` accepts an `events` array of up to 5,000 entries. `accepted` counts valid entries processed, including retries and well-formed unused event types. Malformed items and conflicting ID reuses are excluded. An empty array returns zero. Invalid query parameters and invalid batch envelopes return JSON 400. An unknown serial or unsupported persona route returns 404.

[API contract](vendor/quiet-fleet/docs/CONTRACT.md) · [Ingestion and time model](docs/ingestion.md) · [Support priority policy](docs/decisions.md#p07-support-queue) · [BX decoding](docs/bx-decoding.md) · [Current phase](planning/STATUS.md)

## Release verification

From the checkout root, with the pinned runtime installed and port 8080 free, run the original preflight and practice plus the offline restart check.

```bash
python scripts/release_check.py --data "$PWD/data" --persona support
```

For one check, use `scripts/verify.py` with `preflight`, `practice`, or `offline` as its first argument. For example, this command runs just the offline check.

```bash
python scripts/verify.py offline --data "$PWD/data"
```

Both scripts accept these arguments.

| Option | Meaning |
| --- | --- |
| `--data DIR` | Reference CSV directory. Preflight and practice also need the original `telemetry/*.jsonl` under it. The verifier resolves this to an absolute path for the vendored tool. |
| `--persona support` | Selects the support-agent practice checks. This is the default. |
| `--out DIR` | Report root, defaulting to `reports/`. Each run gets a new subdirectory under its check name. |
| `--startup-timeout SECONDS` | Maximum service readiness wait, defaulting to 15 seconds. |
| `--exam-timeout SECONDS` | Maximum time for each vendor invocation, defaulting to 900 seconds. |

Each vendor check starts a fresh `python -m quiet_fleet` child and confirms its empty store before ingest. A run keeps the official exit code, warnings, service log, request timings, and checkpoint responses. Practice uses 5,000-event batches with partial flushes at checkpoint boundaries. An ingest request reaching the 10-second contract limit fails verification. The offline check uses a renamed six-CSV fixture, blocks external sockets and DNS in the service, verifies the local OpenAPI route, and restarts the service to confirm ingest state reset. On macOS, the verifier also uses the OS outbound sandbox when its native denial probe succeeds. [Measured release run](reports/release-verification.json)

On macOS with Python 3.12.2, the official preflight passed 10/10 and practice passed 14/14, both with zero warnings. The complete 640,419-envelope replay took 251 seconds. The slowest ingest request took 2.57 seconds, and the service peaked at 82.6 MiB RSS. Ubuntu 24.04 verification remains a separate release gate. [Timings and replay counts](reports/release-verification.json)

## Development checks

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```
