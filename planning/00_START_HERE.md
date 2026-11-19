# The Quiet Fleet: execution guide

Prepared for `https://github.com/luqi101/The-Quiet-Fleet.git` from the supplied six-page brief, the complete data pack, and its actual exam runner. Repository inspected: public, empty, default branch `main`.

This is a plan and a prompt kit, not an implemented or tested service. The hidden exam is unavailable. A perfect score cannot be guaranteed; the release gates below are designed to catch the avoidable failures before submission.

## 1. The product to build

Build **the support-agent service** with Python 3.12, FastAPI, a small SQLite event store, deterministic diagnosis rules, and a properly integrated BX decoder. Expose `/health`, `/ingest`, `/devices/{serial}/status`, and `/triage`. The API and the quality of its decisions are the product. Make the README, reasons, evidence, and demo excellent. A small offline dashboard is optional and comes after correctness.

Support is a recommendation, not a claim about what you submitted in Form 1. Your earlier discussion recommended support, but the actual submitted persona and false-alarm/miss choice were not available in the supplied materials. Before persona-specific implementation, put your real Form 1 answers in `planning/form1.md`. If you chose another persona, use the adaptation prompt at the end of the prompt book. Explain any deliberate change in Form 3.

Recommended support trade-off: **false alarms are worse**, because alert fatigue and unnecessary site visits consume trust and scarce capacity. Direct fault evidence and job risk must still trigger action. Express this through suppression of normal sleep/parking, grouped outages, remote camera recovery first, and an honest unknown state rather than invented diagnoses.

## 2. What to download and where to put it

Download this kit and keep all of its files together. Create `planning/` inside your repository and copy these files into it:

| Kit file | Purpose |
|---|---|
| `00_START_HERE.md` | Exact execution order and commands |
| `01_IMPLEMENTATION_PLAN.md` | Architecture, data findings, rules, calibration, and requirements |
| `02_CODEX_PROMPTS.md` | Copy-ready prompts, P00 through P14 |
| `03_ACCEPTANCE_TEST_MATRIX.md` | Required behavioral and release checks |
| `AGENTS.template.md` | Concise persistent instructions, copied to root `AGENTS.md` by P00 |
| `data_findings.json` | Measured pack findings, useful for independent reproduction |

Keep the original brief and ZIP locally. Do not put your entire personal Downloads folder in the repository.

## 3. Set up the repository in VS Code

These terminal commands use Bash, appropriate for macOS, Linux, or Ubuntu in WSL. If using Windows, open the project in WSL so development matches the grader more closely.

```bash
git clone https://github.com/luqi101/The-Quiet-Fleet.git
cd The-Quiet-Fleet
git switch -c main
git remote -v
git status --short
python3.12 --version
```

For the initially empty repository, Git may already place you on an unborn `main` branch. If `git switch -c main` reports that `main` already exists, run `git switch main` instead. Do not recreate or overwrite an existing checkout if you have already started work. Verify that the remote points to the exact repository above.

Open this directory in VS Code, using **File > Open Folder** or `code .` if the command is installed. Open the Codex extension while this repository is the active folder. Use a local workspace session with file editing and terminal execution available. P00 is a planning task that may organize inputs and write planning documents, so run it in a mode that permits those writes. Its text explicitly forbids application implementation. You do not need to rely on a version-specific mode selector.

If Python 3.12 is unavailable, install Python 3.12 before the implementation phases and reopen the terminal. The grader has Python 3.12; do not accidentally develop against an unsupported Python-only feature from a later version. Node is unnecessary for the recommended service.

Create `inputs/` and `planning/` through VS Code. Copy the two original attachments into `inputs/` with these names:

```text
inputs/candidate-brief.pdf
inputs/quiet-fleet-data-pack.zip
```

Copy the kit files into `planning/`. Add your actual Form 1 answers to `planning/form1.md`. If you do not have the exact text, write what you know and clearly mark the missing portions; never reconstruct an earlier submission as if it were a verbatim record. Put real ops-lead replies in `planning/ops-answers.md`, with their dates and exact wording. An empty file should say that no replies have been received.

Paste P00 from the prompt book into Codex. It will check existing instructions, read the supplied sources, organize the local data, create the project plan, and stop before application implementation. Review its requirement matrix and assumptions before moving on.

## 4. How to work through the prompts

Send **one phase prompt at a time**. Let Codex finish that phase, execute its checks, and update `planning/STATUS.md`. Inspect the diff in VS Code. Continue when its gate passes. If it reports a failure, use the remediation prompt in the prompt book, then repeat that phase's relevant checks.

| Order | Prompt | Required result |
|---:|---|---|
| 0 | P00: read and plan | Source-grounded plan, traceability matrix, explicit persona assumption |
| 1 | P01: reproduce the data audit | Measured findings and a provisional threshold register |
| 2 | P02: service skeleton | Offline one-command startup, health, request/response schemas, 400/404 handling |
| 3 | P03: ingestion and temporal store | Per-event isolation, semantic deduplication, historical query correctness |
| 4 | P04: normal family behavior | Correct T/C/A normal states and cross-device ignition context |
| 5 | P05: individual causes | Power, camera escalation, plans, swaps, battery, cold, downtime, coverage |
| 6 | P06: shared incidents | Generalized carrier diagnosis, no duplicate triage ownership |
| 7 | P07: support decisions | Correct owner, priority, reasons, evidence, and stable output |
| 8 | P08: BX integration | Decoder matches all three anchors and changes real status/triage behavior |
| 9 | P09: adversarial verification | Boundary, replay, noninterference, and identity tests |
| 10 | P10: official exam and performance | Clean preflight and practice from separate fresh processes |
| 11 | P11: presentation | Clear output and docs; optional fully local dashboard |
| 12 | P12: submission evidence | Actual end-of-history actions, honest AI log, Form 3 draft |
| 13 | P13: release audit | Fresh-environment and offline release gates pass |
| 14 | P14: final publication | Push only when you are actually submitting |

Do not treat a green practice run as proof that hidden scenarios pass. There are only three practice checkpoints. The independent tests in `03_ACCEPTANCE_TEST_MATRIX.md` are essential.

Each completed phase should produce a meaningful local commit. Do not alter commit timestamps or claim a shorter build time. The brief explicitly asks you to commit during development and **push only when submitting**. Until P14, the work remains local even though the target repository is public.

## 5. Expected repository layout after P00-P02

The following paths are a concrete recommended layout. Codex may make small changes if it preserves the interfaces and updates every command and reference consistently.

```text
AGENTS.md
README.md
requirements.txt
requirements-dev.txt
pyproject.toml
config/rules.json
config/calibration.json
quiet_fleet/__init__.py
quiet_fleet/__main__.py
quiet_fleet/api.py
quiet_fleet/models.py
quiet_fleet/config.py
quiet_fleet/reference.py
quiet_fleet/time_utils.py
quiet_fleet/store.py
quiet_fleet/normalize.py
quiet_fleet/projection.py
quiet_fleet/diagnosis.py
quiet_fleet/incidents.py
quiet_fleet/triage.py
quiet_fleet/bx.py
scripts/audit_data.py
scripts/calibrate.py
scripts/verify.py
scripts/release_check.py
scripts/capture_end_state.py
scripts/offline_smoke.py
tests/
docs/requirements.md
docs/architecture.md
docs/calibration.md
docs/decisions.md
docs/data-quality.md
docs/bx-decoding.md
docs/ai-usage.md
reports/
data/assets.csv
data/devices.csv
data/schedule.csv
data/weather.csv
data/plan_changes.csv
data/support_cases.csv
vendor/quiet-fleet/docs/CONTRACT.md
vendor/quiet-fleet/docs/PRIMER.md
vendor/quiet-fleet/exam/qf_exam.py
vendor/quiet-fleet/exam/practice.json
vendor/quiet-fleet/exam/PRACTICE.md
vendor/quiet-fleet/new_hardware/
planning/
```

Local-only paths: `inputs/`, `.local/`, `data/telemetry/`, `.venv/`, temporary databases, caches, and generated bulk replay results. Preserve original vendor files and record their hashes. Do not modify the exam tool or practice expectations to make tests pass.

The six reference CSVs are small enough to include for default startup and reproducible inspection. The telemetry corpus is unnecessary for grading startup and should be ignored by Git. The grader supplies a new `QF_DATA_DIR`; the service must use that directory and ingest telemetry only through HTTP.

## 6. Install and run commands the finished project must support

These are **target commands for the implementation**, not a claim that the currently empty repository supports them. P02 must make them real.

From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m quiet_fleet
```

The last line must start the service at `http://localhost:8080` with an empty telemetry store. It must not install anything, download anything, load historical JSONL, perform calibration, invoke an AI model, or run a frontend build. It must work after networking has been disabled. Reference files resolve from `QF_DATA_DIR`, defaulting to `./data`.

To run your own development checks, install the separate development requirements during the online install step:

```bash
python -m pip install -r requirements-dev.txt
python scripts/verify.py
```

In a second terminal with the same virtual environment active, against a running service:

```bash
python vendor/quiet-fleet/exam/qf_exam.py preflight --data data --persona support --out reports/preflight
```

Stop the service with Ctrl+C, then start it again:

```bash
python -m quiet_fleet
```

Run practice from the second terminal:

```bash
python vendor/quiet-fleet/exam/qf_exam.py practice --data data --persona support --out reports/practice
```

The local `data/telemetry/` directory must contain the extracted history for these exam-tool commands. The service itself must never read it. The `--data` flag is explicit because the copied tool's original default points to a different relative directory.

If the service cannot start because a previous process holds port 8080, identify and stop that specific process. Do not start a second worker or change the grader's port to conceal the issue.

## 7. The five most costly mistakes to prevent

1. **Loading telemetry on startup.** The exam streams it. An already populated database breaks empty-state and historical semantics.
2. **Using last arrival as current device state.** Buffered old data must not undo newer ignition, recovery, or fault evidence.
3. **Deduplicating only by event ID.** There are retries with new IDs. They must not refresh freshness, multiply incidents, or count as extra reboot attempts.
4. **Treating the inventory CSV as a complete historical assignment log.** An end-of-history `removed` tracker is present in the earlier outage checkpoint; a `stock` tracker with no asset assignment actually transmits VIN-bearing telemetry.
5. **Clearing a fault on any newer message.** The power-loss practice tracker continues sending positions from backup power for approximately 19 minutes after disconnection. It remains a power-loss problem until recovery is supported.

## 8. Final submission sequence

Run P13 and require all release gates to be green. Review `docs/form3-draft.md` in your own words. Check that the AI disclosure accurately includes this planning help and Codex's implementation work. Check that the top three actions were captured at exactly `2026-10-31T23:59:00Z`.

When you are actually ready to submit, paste P14. It should verify the clean local tree and exact Git remote, create any final honest local commit, and push to `main` without force. Verify the repository opens publicly and includes working setup instructions. Then submit Form 3 through the link in the pack. This plan does not authorize sending emails or forms on your behalf.

After submission, freeze decision logic. The brief permits a setup-only fix if their service startup fails and they contact you; logic changes after submission do not count. Keep the exact submitted commit SHA in your notes.

## 9. What you should personally understand before the call

Explain the difference between observation time and receipt time, why a duplicate cannot make a device healthier, how a carrier incident is detected without hardcoded IDs, why a camera gets a remote reboot before a visit, how a VIN can reveal stale assignments, and how all three BX portal rows validate the decoder.

Be able to change one threshold in config, run a focused test, and explain the changed behavior. Be able to point to an actual AI mistake or a documented independent check. You do not need to memorize every line, but you must own the decisions you submit.
