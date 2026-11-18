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

The support application distinguishes normal reporting, expected quiet, individual faults, and uncertainty for T trackers, C cameras, and A tags. `GET /devices/{serial}/status?at=…` explains the selected cause, applicable secondary constraints, and the suggested action. It returns original evidence IDs and the latest eligible unique device receipt as `last_heard_at`. Reporting deadlines use observation time. Devices without contact have a null `last_heard_at`. Both status and triage require an ISO timestamp with an explicit offset and output UTC with `Z`. Shared incidents and triage items are later phases.

`POST /ingest` accepts an `events` array of up to 5,000 entries. `accepted` counts valid entries processed, including retries and well-formed unused event types. Malformed items and conflicting ID reuses are excluded. An empty array returns zero. Invalid query parameters and invalid batch envelopes return JSON 400. An unknown serial or unsupported persona route returns 404.

[API contract](vendor/quiet-fleet/docs/CONTRACT.md) · [Ingestion and time model](docs/ingestion.md) · [Individual diagnosis decisions](docs/decisions.md#p05-individual-diagnosis) · [Current phase](planning/STATUS.md)

## Development checks

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```
