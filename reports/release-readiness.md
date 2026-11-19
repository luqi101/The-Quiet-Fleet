# The Quiet Fleet release audit

**Release verification passed.** The audited runtime passed the full suite, both official checks, and offline restart on Ubuntu 24.04.5 with Linux network isolation. All ten Ubuntu checkpoint responses matched the earlier macOS run.

## Ubuntu release gate

The tested public source was `b36af02865c31f6050e183025b99efa85750fc37`. It matched the macOS runtime digest below. The subsequent release record changes documentation only.

A fresh [Ubuntu Base 24.04.5 amd64](https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/) root filesystem ran in a local Linux VM. The VM used an x86-64 Linux 6.18.60 kernel. Ubuntu supplied CPython 3.12.3, SQLite 3.45.1, and glibc 2.39. The official base archive matched SHA-256 `e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86`.

The runtime and test requirements installed into separate fresh virtual environments. After installation, `unshare --net` created a new Linux network namespace and `ip link set dev lo up` enabled loopback. The namespace had only loopback, no external route, and an external TCP probe returned `ENETUNREACH`. The source and data mounts were read-only. The suite and release commands ran unprivileged. The verifier used its default port 8080 and started the documented `python -m quiet_fleet` entrypoint for both official checks and both offline smoke phases.

| Ubuntu check | Result |
| --- | --- |
| Fresh installs and `pip check` | Both pinned environments passed |
| Full suite | 96 passed in 11.068 s, zero failures, errors, or skips |
| Original vendor preflight and practice | 10/10 and 14/14, exit 0 for both, zero warnings, all nine vendor hashes matched before and after |
| Offline smoke and process lifecycle | Exit 0. Health, ingest, status, triage, local assets and empty restart passed using renamed six-file references. All four owned service processes started empty and shut down with exit 0. |
| Replay size and elapsed time | 640,419 accepted of 640,419, across 132 requests with 127 full batches. Vendor wall time 128.512 s. |
| Ingest HTTP p50 / p95 / p99 / maximum | 0.705 / 0.809 / 0.873 / 0.879 s. Zero requests reached 10 s. |
| Practice readiness / peak service RSS | 0.737 s / 85.230 MiB |
| Slowest status / triage | 6.641 / 9.620 s |
| Evidence and identity | 405 eligible evidence references. Ten byte-identical checkpoint outputs compared with macOS, including the END digest. 632,810 logical messages and 7,609 retries. |

The commands inside the isolated Ubuntu environment were `python -B -m unittest discover -s tests -v` in the test venv and `python -B scripts/release_check.py --data /qf-data --persona support --out /tmp/qf-run` in the runtime venv. Runtime SQLite storage was in guest tmpfs, so these timings describe that environment. The Ubuntu logs and full checkpoint outputs are retained locally. The [Docker recipe](#reproduce-the-ubuntu-gate) provides an equivalent loopback-only setup.

## macOS source and environment

| Item | Verified identity |
| --- | --- |
| Runtime, tooling and tests | `bc1ca5e2e21a915f4bbefb94a4a4bfe1e8c1007d` |
| Runtime SHA-256 | `f92b7c285c69eb7de9e461e230600d2336fbdbecf8e22e5ca4a2650f1379fa24` |
| Original six-page brief SHA-256 | `3df2ab56f3c7ac4e97a6fb8dab97ba1c78d380407494c823acb7dbf88357d0d6` |
| Host | macOS 15.7.9, x86-64, quad-core 1.4 GHz Intel Core i5, 16 GB RAM |
| Runtime | CPython 3.12.2, SQLite 3.45.1, 15 installed runtime pins plus pip |
| Startup exercised in this audit | Same FastAPI app at `127.0.0.1:18080` with one Uvicorn worker and reload disabled. An existing listener on 8080 was left alone. The documented entrypoint uses port 8080. |

The runtime digest covers the Python package, dashboard assets, rules, and runtime requirements. The release summaries matched that digest. All nine vendor hashes matched the recorded sources before and after both exams. The final calibration regeneration compared the rules, calibration register, measured report and readable documentation with the checked-in artifacts. The calibration report retains 34 input hashes. [Vendor hash manifest](../vendor/quiet-fleet/SHA256SUMS) · [Contract](../vendor/quiet-fleet/docs/CONTRACT.md) · [Calibration evidence](calibration.json)

## Findings

| Consequence | Finding and disposition |
| --- | --- |
| Release gate, completed | The earlier macOS run left Ubuntu open. The new Linux VM run completed Ubuntu installation, default startup on 8080, official replay and offline verification under OS-level network isolation. |
| Behavioral defect, fixed | A syntactically valid batch containing a 4,301-digit integer returned 400 and discarded both valid neighbors. The regression reproduced that before the fix. Packet validation now rejects the oversize value locally. The HTTP test verifies both accepted neighbors and the real disconnect evidence. |
| Release and reproducibility defects, fixed | The packet date range and two coverage cutoffs had code defaults outside the public register. All three are now explicit with the original values and tests. The register includes the 640-digit defensive integer limit. The verifier now supports a dedicated loopback port and the lifecycle tests exercise startup even if 8080 is occupied. |
| Documentation gaps, fixed | Added the fresh Ubuntu venv prerequisite, corrected broken Markdown anchors, and prepared the candidate's local Form 3 draft from real END results. The product note is 192 words. The candidate keeps the draft and rehearsal notes locally. |

## Commands and observed results

Executed from the checkout root. The pre-existing interpreter bootstrapped independent virtual environments. All runtime and development dependencies installed successfully, and both environments passed `pip check`.

```bash
mkdir -p .local/p13
.venv/bin/python -m venv .local/p13/runtime
.local/p13/runtime/bin/python -m pip --disable-pip-version-check --retries 1 --timeout 10 install -r requirements.txt
.local/p13/runtime/bin/python -m pip check
.venv/bin/python -m venv .local/p13/tests
.local/p13/tests/bin/python -m pip --disable-pip-version-check --retries 1 --timeout 10 install -r requirements-dev.txt
.local/p13/tests/bin/python -m pip check
.local/p13/tests/bin/python -B -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX="$PWD/.local/p13/bytecode" .local/p13/tests/bin/python -m compileall -q quiet_fleet scripts tests
(cd vendor/quiet-fleet && shasum -a 256 -c SHA256SUMS)
.local/p13/runtime/bin/python -B scripts/release_check.py --data "$PWD/data" --persona support --port 18080 --out "$PWD/.local/p13/final"
.local/p13/runtime/bin/python -B scripts/calibrate.py --data "$PWD/data" --reports-dir .local/p13/regenerated/reports --docs-dir .local/p13/regenerated/docs --config-dir .local/p13/regenerated/config
git diff --check
```

| Check | Observed result |
| --- | --- |
| Full meaningful suite | 96 passed, 0 failures, 0 errors, 0 skips. 10.612 seconds. The repository configures no separate linter or type checker. |
| Official preflight | Exit 0, 10/10, zero warnings. Checked 605 envelopes, including mixed malformed and unknown entries. |
| Official practice | Exit 0, 14/14, zero warnings. P1 grouped the outage with carrier ownership and correct statuses. P2 recommended remote support for the faulty camera and excluded the sleeping camera. P3 retained the disconnected tracker's technician action. |
| Practice checkpoint integrity | Ten response files were byte-identical to P11. All 405 evidence references resolved to actual eligible receipts. The exact END checkpoint contained seven items and supplied the preserved top three. [END evidence](end-state-top-three.json) |
| Process lifecycle | Preflight, practice and both offline phases had separate process IDs, initial zero-message, zero-ID, zero-receipt stores, and graceful exit code 0. The owned service ports were released. |
| Offline smoke | Exit 0. macOS `sandbox-exec` blocked an external socket at the OS level and allowed loopback. The Python guard independently denied external sockets, DNS, and any reads of the corpus or BX samples. A renamed six-CSV directory served health, ingest, status, triage, OpenAPI and all local dashboard assets. Restart removed the ingested issue. |
| Browser under macOS egress restrictions | Exit 0. Chrome checked empty and malformed requests, Toronto and Regina clock displays, keyboard focus, and safe rendering of an HTML-like event ID. A real replay of 172,358 envelopes matched the carrier queue and device lookup to the official responses. Responsive layout and filters passed. The page issued only same-origin GETs. Development browser logs are under `.local/p13/browser/`. |

The verifier invoked the original tool with `preflight` and `practice`, `--data "$PWD/data"`, `--persona support`, `--url http://127.0.0.1:18080`, `--batch 5000`, and a separate `--out` directory for each. The request observer recorded timings without changing the runner or expectations. The logs, per-request timings, and full JSON responses are local under `.local/p13/final/`. Use the aggregate `release/run-*/summary.json` there to locate the matching preflight, practice and offline results.

## Replay timing and memory

| Measure | Observed |
| --- | ---: |
| Practice startup to health / peak service RSS | 0.726 s / 82.512 MiB |
| Streamed envelopes / accepted | 640,419 / 640,419 |
| Requests / full 5,000-event requests | 132 / 127 |
| Ingest HTTP p50 / p95 / p99 / maximum | 1.820 / 2.456 / 2.632 / 2.918 s |
| Total time in ingest requests / whole vendor invocation | 226.456 / 262.417 s |
| Ingest requests reaching 10 s | 0 |
| Slowest device status / slowest triage | 6.341 / 8.856 s |
| P1 / P2 / P3 / END triage | 1.696 / 5.140 / 7.796 / 8.856 s |

The runner reported 262 seconds from first replay through END and the last event. Timing percentiles use nearest ranks across all ingest requests. The verifier reaped the owned service process to measure peak RSS. SQLite stores history on disk under the process's temporary directory, with a bounded page cache and indexed, serialized as-of reads. Queue and cohort work still grow with the relevant history. P11's 11.227-second END query exceeded the runner's advisory query target on one prior run. The ten-second contract applies to ingest requests. [Earlier timing baseline](release-verification.json)

The store held 632,810 logical messages, 635,066 original IDs and 640,419 distinct ID-receipts. The 7,609 retries include 5,353 repeated IDs and 2,256 new-ID aliases. Practice reported zero malformed, ignored, conflicting, or clock-ahead events in the supplied stream. It decoded 308 distinct BX frames. The mixed preflight independently exercised three malformed events and one well-formed unused type. [Data audit](data-audit.json) · [BX proof and limits](../docs/bx-decoding.md)

## Requirements at the audited candidate

| Requirements | Status and verification |
| --- | --- |
| R01–R02 | Passed on Ubuntu 24.04.5 with Python 3.12.3 in an isolated Linux network namespace on the documented port 8080. Python 3.12.2 and native offline loopback also passed on macOS. |
| R03–R06 | Passed. Six-file default and alternate loads, renamed IDs, startup read guard, exact health and empty restart. |
| R07–R09, R28 | Passed. Real full-size timing, coherent batch commits, mixed-element isolation including oversize integers, valid unknown kinds, strict JSON 400s and serial and unsupported-route 404s. |
| R10–R13 | Passed. Independent observation order, inclusive receipt cutoffs, future aliases and unrelated future receipts, conflict handling, stale backfill, numeric A clocks, and equivalent replays across new IDs, names, dates, arrival orders and batch partitions. |
| R14–R17, R41 | Passed. T position and parked boundaries, camera sleep and wake, A daily jitter, true local shift previews, Toronto fall-back, and Regina's unchanged offset. |
| R18–R22 | Passed under the documented policy. Backup positions leave power loss active. Later recording resolves storage faults. Reboot trials require awake evidence. Account transitions and battery hysteresis respect observation time. Historical VIN and stock evidence support assignment or explicit ambiguity. Cold and weak-signal explanations are bounded. |
| R23 | Passed. Renamed and rescheduled cohort fixtures exercise both depots and carriers, healthy controls, ordinary shift ending, shared and firmware ambiguity, physical faults, quiet-device exclusion, partial recovery, closure, and recurrence. The support practice carrier case passed. |
| R24–R27, R39 | Passed. Status and queue share diagnosis, ownership follows cause, priorities use half-open jobs and local deadlines, each serial appears once, and responses use allowed enums, finite confidence and original IDs visible at the cutoff. |
| R29–R30 | Passed. Validated register covers 48 entries. The reproducible chronological calibration and the selected-case limitations are published. |
| R31 | Passed. All three exact portal anchors and 308 unique stream frames were checked. Synthetic HTTP covers flags, no-fix, late and malformed frames, battery recovery and retry idempotence. |
| R32 | Passed on Ubuntu and macOS. Both unmodified official commands ran from empty stores with verified vendor hashes and measured timings. |
| R33, R36, R38 | Passed. AI role and corrections are documented, vendor sources are intact, and the six reference CSVs are tracked. No remote history existed before the authorized release. |
| R34–R35, R45 | Draft and evidence verified. The top three use the official END output at `2026-10-31T23:59:00Z`. The 192-word note proposes pilot measures. Candidate review and eventual submission are separate. |
| R37 | Prepared. The local drill and focused grace-change example are reproducible. The candidate's live demo and code change are assessed on the call. |
| R40 | Passed. Ingested plans supply timing. Case outcomes never determine runtime causes. Static schedule and depot-local weather use their documented context. |
| R42–R43 | Outside the chosen support persona. Both alternative routes return 404. |
| R44, R46 | Trade-off and provided-data provenance verified. Ops replies and Form 2 usage were unavailable in the checkout. |

The code review traced the receipt condition through SQLite snapshots, projections, historical incident probes, and the revision-and-cutoff cache. It also checked process startup, the shared support evaluator, the single-owner partition and the frontend's same-origin API use. The runtime has no practice-specific identifier branches or per-device support-case lookup. Public-tree and reachable-blob checks found no telemetry corpus, venv, runtime databases, secret patterns, or personal paths. The largest reachable blob is the 707,616-byte reference schedule. [Detailed requirement matrix](../docs/requirements.md) · [Acceptance scenarios](../planning/03_ACCEPTANCE_TEST_MATRIX.md)

## Unresolved business facts

- The approved asset scope and dates for seasonal landscaping downtime remain unknown. Suppression stays disabled.
- The support deadline that defines high urgency around the local shift remains unconfirmed. The two-hour preparation horizon is provisional.
- The available Form 2 allowance could not be established from the local record.
- The three rounded portal anchors constrain the inferred BX scale. The 20% A and BX recovery cutoffs and the selected-case reboot policy carry documented uncertainty. The official practice suite covers its published scenarios. Hidden-exam performance remains unknown. [Open operating policy](../docs/decisions.md#open-operational-questions) · [Calibration](../docs/calibration.md)

## Reproduce the Ubuntu gate

On a Docker-capable host, use this checkout with the original local telemetry under `data/telemetry/`. The image installs dependencies at build time. The container then runs the unit suite and the three release modes at the documented loopback port with external networking disabled. Telemetry is mounted read-only for the original exam tool.

```bash
docker build -f Dockerfile.verify -t quiet-fleet-verify .
mkdir -p reports/release/ubuntu24
docker run --rm --network none \
  --mount "type=bind,src=$PWD/data,dst=/qf-data,readonly" \
  --mount "type=bind,src=$PWD/reports/release/ubuntu24,dst=/qf-results" \
  quiet-fleet-verify sh -ec '
    cat /etc/os-release
    python --version
    python -m pip check
    python -m unittest discover -s tests -v
    python scripts/release_check.py --data /qf-data --persona support --out /qf-results
  ' > reports/release/ubuntu24/validation.log 2>&1
```

Record Ubuntu and Python versions, the command's exit status, per-mode results and performance from `reports/release/ubuntu24/`. Match the runtime digest to the audited candidate. The observed release measurements above came from the Linux namespace run. [Verification image](../Dockerfile.verify) · [Image context allowlist](../Dockerfile.verify.dockerignore)
