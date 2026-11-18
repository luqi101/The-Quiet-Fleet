# API contract

IDs in the examples are made up.

Your service listens on `http://localhost:8080`, speaks JSON, and uses UTC
timestamps in the form `2026-10-12T14:05:12Z`.

## Startup

- Start with **empty state**. The exam starts your service fresh, then streams
  every event to `POST /ingest`: the full history first (Oct 4 to 31), then the
  exam window.
- Read the reference files from the folder named in the environment variable
  `QF_DATA_DIR` (default `./data`): `assets.csv`, `devices.csv`,
  `schedule.csv`, `weather.csv`, `plan_changes.csv`, `support_cases.csv`.
  Don't load `data/telemetry/` at startup; those events reach you through
  `/ingest`. (`plan_changes.csv` is a copy of the history's `plan_change`
  events; new ones arrive through `/ingest`.)
  You can of course analyse the telemetry files offline while you build.
- No network calls and no AI or other external APIs while the service runs.

## `GET /health`

`200 {"status": "ok"}` once the service is ready.

## `POST /ingest`

Body: `{"events": [ ... ]}`, up to 5,000 events per request, in the order the
platform received them. Respond `200 {"accepted": <number>}` within 10 seconds.

- Events can be **duplicated** (sometimes with a new `event_id`), **late**, or
  **out of order**. Ingesting the same batch twice must not change any answer.
- Accept and ignore event types you don't use. Never fail a whole batch
  because of one bad event.

### Event shapes

Every event has `event_id` and `received_at` (when the platform got it).
Device events also have `serial`, `type`, `device_time` (the device's own
clock) and `payload`.

| `type` | Sent by | `payload` |
|---|---|---|
| `position` | T-series | `lat`, `lng`, `speed_kmh`, `ignition` |
| `heartbeat` | T-series | `battery_v` (vehicle battery), `signal` (0 to 5), `vin` |
| `ignition_on` | T-series | `vin` |
| `ignition_off` | T-series | (empty) |
| `power_disconnect`, `power_restore` | T-series | (empty) |
| `low_voltage` | T-series | `volts`, `source` |
| `camera_status` | C-series | `status`: `booting`, `recording`, `sleeping` or `storage_error`; sometimes `code` |
| `command` | Platform | `command` (for example `reboot`), `issued_by` |
| `plan_change` | Platform | `plan`, `status` (`active`, `paused`, `ended`), `reason` |
| `check_in` | A-series | `battery_pct`, `lat`, `lng`, `temp_c` |
| `bx_raw` | BX-series | No `serial`, `device_time` or `payload`: just `raw`, the undecoded message. See `new_hardware/`. |

`device_time` is usually a UTC string, but not always.

## `GET /devices/{serial}/status?at=<UTC time>`

Answer as of `at`, using only events received at or before `at`. `404` for
an unknown serial.

```json
{
  "serial": "C-2000",
  "asset_id": "V-100",
  "at": "2026-10-20T16:00:00Z",
  "state": "needs_action",
  "likely_cause": "camera_fault",
  "confidence": 0.8,
  "last_heard_at": "2026-10-20T15:12:40Z",
  "reasons": ["Camera reported storage_error at 15:12 while the vehicle kept driving"],
  "evidence": ["e00000001", "e00000002"]
}
```

## Errors

Return `400` for a missing or invalid parameter (for example `hours=500`) and
`404` for an unknown serial. Never crash.

## Persona endpoints

Build the one for your persona. All three take `at` and answer as of that
moment. Every item carries `reasons` (plain English your persona would read)
and `evidence` (event IDs).

### Support agent: `GET /triage?at=`

```json
{
  "at": "2026-10-12T14:45:00Z",
  "items": [
    {
      "item_id": "any string",
      "kind": "incident",
      "serials": ["T-50001", "T-50002"],
      "asset_ids": ["V-100", "K-00"],
      "likely_cause": "carrier_outage",
      "who_acts": "carrier",
      "next_action": "free text",
      "priority": "high",
      "reasons": ["..."],
      "evidence": ["..."]
    }
  ]
}
```

`kind` is `device` (one device) or `incident` (several devices, one cause).
Each device appears in at most one item. Include only things someone needs to
act on or follow up now.

### Fleet manager: `GET /job-cover?depot=MSS&at=&hours=24`

Covers jobs at that depot (`MSS` or `REG`) starting in `[at, at + hours)`,
with `hours` from 1 to 72. List only jobs whose asset can't be seen or
recorded.

```json
{
  "depot": "REG",
  "at": "2026-10-26T23:30:00Z",
  "hours": 24,
  "jobs": [
    {
      "job_id": "J-REG-1027-00000",
      "asset_id": "K-00",
      "problem": "no_location",
      "decision": "swap",
      "swap_to": "K-99",
      "manager_action": "free text",
      "reasons": ["..."],
      "evidence": ["..."]
    }
  ]
}
```

- `problem`: `no_location`, `no_video` or `both`.
- `decision`: `swap` (move the job to `swap_to`), `keep` (the problem won't stop
  the job) or `gap` (no asset can take it; `swap_to` is `null`).
- A swap must follow the brief's rule: same type, same depot, no other job
  during the whole slot, and the new asset itself can be seen and recorded.
  Don't give one asset two overlapping jobs.

### Field-tech scheduler: `GET /visits?at=&days=2`

Plans visits for the local day of `at` and the following `days − 1` days,
with `days` from 1 to 3.

```json
{
  "at": "2026-10-26T23:30:00Z",
  "days": 2,
  "visits": [
    {
      "visit_id": "any string",
      "depot": "REG",
      "asset_id": "K-00",
      "serials": ["T-50000"],
      "start": "2026-10-27T13:00:00Z",
      "end": "2026-10-27T14:00:00Z",
      "reason": "power_loss",
      "kit": "free text",
      "priority": "high",
      "reasons": ["..."],
      "evidence": ["..."]
    }
  ],
  "deferred": [
    {"asset_id": "TR-00", "reason": "battery_low", "why": "free text"}
  ]
}
```

Visits must start after `at`, and must start and end between 07:00 and 15:00
local time, Monday to Friday, with at most 6 per depot per local day. Anything
needing a visit that doesn't fit goes in `deferred`.

## Fixed values

| Field | Allowed values |
|---|---|
| `state` | `reporting`, `quiet_expected`, `needs_action`, `unknown` |
| `likely_cause` | `none`, `parked_normal`, `sleeping_by_design`, `cold_weather`, `planned_downtime`, `coverage_gap`, `carrier_outage`, `power_loss`, `camera_fault`, `plan_paused`, `device_swapped`, `battery_low`, `unknown` |
| `who_acts` | `customer`, `technician`, `carrier`, `support`, `none` |
| `priority` | `high`, `medium`, `low` |
| `problem` | `no_location`, `no_video`, `both` |
| `decision` | `swap`, `keep`, `gap` |
| `reason` (visits) | any `likely_cause` value |

- `state` meanings: `reporting` means heard from on schedule; `quiet_expected`
  means quiet and that's normal; `needs_action` means quiet or failing and
  someone (customer, technician, carrier or support) has to act or follow up;
  `unknown` means not enough evidence yet.
- Use `likely_cause: none` with `state: reporting`.

## How it's scored

The script reads the structured fields only: states, causes, `who_acts`,
priority, and which devices, jobs, swaps and visits you return, with their
times and evidence IDs. Reasons, next actions, manager actions and kit are free
text; reviewers read them. Any equally good answer scores the same: a different
valid swap, for example, or extra evidence IDs as long as the key ones are
there.
