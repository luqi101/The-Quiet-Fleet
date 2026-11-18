# Project status

## P00 · Source review and local setup

The materials folder had no Git metadata. The candidate selected a new child checkout. The verified fetch and push URL is `https://github.com/luqi101/The-Quiet-Fleet.git`. The checkout uses `main`. The upstream contained no commits at setup.

- Read the complete six-page candidate brief, required kit documents, pack README, contract, primer, practice notes and scenario, full runner, BX README, and CSV headers and examples. Restored the missing Form 3 worksheet from the original kit and verified the kit manifest.
- Validated the data ZIP member paths, file types and CRCs before extraction. Verified all 43 extracted files and their copies against the ZIP. The six tracked reference CSVs contain 251 assets, 360 devices, 8,957 jobs, 62 weather rows, 22 plan changes, and 179 cases. The 28 local replay files contain 640,419 envelopes, including 313 BX frames.
- Verified the nine preserved vendor sources with `shasum -a 256 -c SHA256SUMS` from `vendor/quiet-fleet/`. `git check-ignore -v` confirmed the exclusions for original inputs, extraction, telemetry, environments, databases, caches, and bulk outputs. The vendored Python runner's help command executed under Python 3.12.2.
- Reviewed the 30-file staged inventory and authored diff. All 23 supplied blobs in the index matched their archive entries exactly. The staged whitespace check passed with `git -c core.whitespace=cr-at-eol diff --cached --check` to allow the supplied CSV line endings.
- Recorded the source discrepancies, execution order, future modules, and verification scenarios. The service, official preflight and practice results, and release tests are pending. [Execution plan](../docs/decisions.md) · [Requirements](../docs/requirements.md) · [AI usage](../docs/ai-usage.md)

## Decisions and open facts

- At P00, support and false-alarm aversion were provisional because the Form 1 and ops records were unavailable. P01 settled the persona and trade-off from the supplied Form 1.
- The unresolved operational facts are approved seasonal downtime scope and effective dates, and Larchmont’s high-priority deadline around the 06:00 local shift. Form 2 usage is unverified. The original kit retains its candidate topics, and new drafts depend on confirmed allowance.
- Python 3.12.2, pip 25.0.1, Git 2.50.1, SQLite 3.45.1, both depot time zones, and local PDF and ZIP tools were available. Docker and other checked local container tools were unavailable. Ubuntu 24.04 offline execution remains a P13 verification dependency.

## P01 · Offline data audit and calibration

- The supplied Form 1 confirms **support, false-alarm aversion, and one consolidated customer alert for major outages**. Preserved the exact record and carried forward the source contract's readiness endpoint alongside the planned user endpoints. [Form 1 record](form1.md)
- Ran both offline tools over 28 JSONL files and the six reference CSVs. Observed 640,419 envelopes, 635,066 distinct IDs, 632,810 logical observations, 2,256 new-ID aliases, 252 legacy numeric-clock envelopes, 313 BX frames and no conflicting IDs in the pack. Three original BX portal anchors matched. The report preserves the excluded negative case duration and documents the percentile convention difference. [Data quality](../docs/data-quality.md) · [Audit report](../reports/data-audit.json)
- The October 4–24 development cohort selected the 360 s tracker, 600 s recording, 26 h A/BX and 8 s routine receipt-lag bounds. Separate October 25–31 validation showed zero healthy daily intervals crossing 26 h. Carrier onset was detected on both labeled cases, with a held-out persistence limitation and no observed background groups across 40,169 unguarded minute probes. Provisional policy and open operational facts remain explicit. [Calibration](../docs/calibration.md) · [Threshold register](../config/rules.json)
- The focused offline tests passed with `python3.12 -B -m unittest discover -s tests -v`. Service behavior, official preflight and practice, and Ubuntu offline startup remain pending. [Requirement matrix](../docs/requirements.md)
- Regenerated both reports, both generated docs, and both config files using an absolute `--data` and temporary output directories. All six outputs matched byte for byte. The full calibration command took 69 seconds on the development host.

## P02 · Runnable HTTP foundation

- `python -m quiet_fleet` starts a single Uvicorn worker on localhost:8080. Startup validates the checked-in rules and all six reference CSVs before readiness, opens a fresh temporary SQLite database, and closes and removes it on shutdown. The support-case duration anomaly remains flagged in its typed reference row.
- The four routes expose readiness, envelope validation, known-device status and triage. Invalid requests return JSON 400. Unknown serials and unsupported paths return 404. Known devices currently return `unknown` with null last contact and empty evidence. Triage is empty. Valid ingest envelopes currently return `accepted: 0` because this phase processes zero entries. Event normalization, storage, replay and diagnosis remain future work. [README](../README.md)
- A fresh runtime-only install with the pinned requirements passed `pip check` under Python 3.12.2 on macOS. The real entrypoint passed loopback HTTP smoke checks with the packaged references and with only six alternate CSVs under a Python outbound socket guard. Python 3.12 Linux x86-64 wheels resolved for all runtime pins. Ubuntu runtime verification remains pending.
- `.venv/bin/python -B -m unittest discover -s tests -v` passed all 16 tests, including 10 HTTP foundation tests. The checks covered readiness, database recreation, a guarded telemetry directory, 400/404 responses, UTC normalization and response shapes. Official preflight, practice and full replay remain pending. [Requirement matrix](../docs/requirements.md)

## P03 · Receipt-aware ingestion and immutable facts

- Per-event validation isolates malformed items. Valid retries and well-formed unused types count as accepted, and conflicting reuses preserve the original binding. SQLite separates logical messages, original IDs and their receipts. The first receipt determines contact and evidence. Credible observation order determines the fact timeline. Each batch commits under a process-local lock that also guards snapshot copies. [Ingestion and time model](../docs/ingestion.md)
- `.venv/bin/python -B -m unittest discover -s tests -v` passed all 29 tests. The added checks cover both time cutoffs, exact and semantic replay, clock-ahead uncertainty, no-data states, platform exclusion, chronological fault recovery, concurrent snapshots, and rollback. The restart test inserts real telemetry and verifies it is absent on the next lifespan. [Requirement matrix](../docs/requirements.md)
- The preliminary full-corpus HTTP replay accepted all 640,419 envelopes in 129 requests, including 128 full ones. On macOS with Python 3.12.2, replay took 206.07 s, maximum request time was 2.585 s, and server peak RSS was 64.574 MiB. All requests finished under 10 s.
- Device status reports contact and eligible original evidence, while its state remains `unknown`. Triage is empty. BX frames are preserved as opaque receipts. Family rules, BX decoding, final exam results and Ubuntu offline verification remain pending.

## Next phase

**P04 · Implement correct normal behavior for T, C, and A families.** Use as-of facts, effective asset context, and the validated threshold register to distinguish reporting, expected quiet, and uncertainty. [P04 prompt](02_CODEX_PROMPTS.md#p04-implement-correct-normal-behavior-for-t-c-and-a-families)
