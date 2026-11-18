# The Quiet Fleet: data pack

Everything here is fictional: Larchmont Field Services, its people, its
assets, the carriers Northwave and Lakeline, and every event.

Read the candidate brief first. The rules are in the brief, not in the data.

## What's in the pack

```
README.md                  this file
docs/CONTRACT.md           the API your service must expose, and the allowed values
docs/PRIMER.md             one page on how fleet devices report
data/assets.csv            251 assets: type, depot, use
data/devices.csv           360 devices: family, firmware, carrier, which asset
data/schedule.csv          8,957 jobs, Oct 4 to Nov 3 (the last 3 days are the exam window)
data/weather.csv           daily low and high at each depot, Oct 4 to Nov 3
data/plan_changes.csv      data plan pauses and resumes in the history
data/support_cases.csv     179 resolved support cases with root cause and fix
data/telemetry/*.jsonl     about 640,000 events, Oct 4 to 31, one file per received day
new_hardware/              the BX-series puzzle (optional, see its README)
exam/qf_exam.py            the exam tool: preflight, practice exam
exam/practice.json         the 3 practice checkpoints
exam/PRACTICE.md           what the practice exam expects, and why
```

## The data

All times are UTC, written like `2026-10-12T14:05:12Z`.

**assets.csv**: `asset_id`, `type` (`van`, `pickup`, `trailer`, `equipment`),
`depot` (`MSS` Mississauga, `REG` Regina), `use`, `make_model`, `year`, `vin`,
`status`.

**devices.csv**: `serial`, `family` (`T` tracker, `C` camera, `A` battery tag,
`BX` new hardware), `model`, `firmware`, `carrier`, `asset_id` (blank for
spares), `status` (`active`, `stock`, `removed`), `installed_at`. This is what
the records say, which isn't always what's on the vehicle.

**schedule.csv**: `job_id`, `asset_id`, `depot`, `start`, `end`, `job_type`.
Jobs run on vans and pickups.

**weather.csv**: `date` (local), `depot`, `low_c`, `high_c`.

**plan_changes.csv**: `serial`, `time`, `plan`, `status`, `reason`,
`event_id`. A copy of the `plan_change` events in the telemetry.

**support_cases.csv**: `case_id`, `opened_at`, `closed_at`, `depot`,
`asset_id`, `serial`, `reported_by`, `symptom`, `root_cause`, `action`,
`outcome`, `notes`. `root_cause` uses the same values as `likely_cause` in the
contract.

**telemetry/YYYY-MM-DD.jsonl**: one event per line, filed by the day it was
received. Event types and payloads are in `docs/CONTRACT.md`.

## Running the exam tool

You need Python 3.10 or newer. The tool uses only the standard library.

1. Start your service on `localhost:8080`.
2. `python exam/qf_exam.py preflight` checks your service against the contract.
3. Restart your service so it starts empty.
4. `python exam/qf_exam.py practice` streams the full history and runs the
   3 practice checkpoints. It takes a few minutes, depending on your service.

Options: `--url` if your service isn't on port 8080, `--persona support|fleet|scheduler`
if it exposes more than one persona endpoint, `--data` if you moved the data
folder. Responses are saved in `exam/results/`.

## How we'll run your service

- **Machine:** Ubuntu 24.04 with Python 3.12 and Node.js 22. For anything
  else, include a Dockerfile.
- **Install step:** allowed. If your README has one (`pip install -r
  requirements.txt`, `npm ci` and so on), we run it first, with internet.
- **Start:** we then run your one start command with networking switched off.
- **Data:** we set `QF_DATA_DIR` to a folder with the same CSV files as
  `data/` here. Telemetry arrives only through `/ingest`.
- **Then:** we run the hidden exam the same way the practice exam runs: the
  full history first, then the exam window, with checkpoints along the way.

## Forms

- Form 2 · Ask the ops lead (at most 2 questions): https://forms.gle/hQ8yiZwHoh9RH75D8
- Form 3 · Final submission: https://forms.gle/bVLrgoNBWsLsedYn8

Questions about access, setup or the deadline: reply to your invitation email.
