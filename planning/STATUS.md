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
- Python 3.12.2, pip 25.0.1, Git 2.50.1, SQLite 3.45.1, both depot time zones, and local PDF and ZIP tools were available. The pinned FastAPI, Uvicorn, and pytest environment belongs to P02. Docker and other checked local container tools were unavailable. Ubuntu 24.04 offline execution remains a P13 verification dependency.

## P01 · Offline data audit and calibration

- The supplied Form 1 confirms **support, false-alarm aversion, and one consolidated customer alert for major outages**. Preserved the exact record and carried forward the source contract's readiness endpoint alongside the planned user endpoints. [Form 1 record](form1.md)
- Ran both offline tools over 28 JSONL files and the six reference CSVs. Observed 640,419 envelopes, 635,066 distinct IDs, 632,810 logical observations, 2,256 new-ID aliases, 252 legacy numeric-clock envelopes, 313 BX frames and no conflicting IDs in the pack. Three original BX portal anchors matched. The report preserves the excluded negative case duration and documents the percentile convention difference. [Data quality](../docs/data-quality.md) · [Audit report](../reports/data-audit.json)
- The October 4–24 development cohort selected the 360 s tracker, 600 s recording, 26 h A/BX and 8 s routine receipt-lag bounds. Separate October 25–31 validation showed zero healthy daily intervals crossing 26 h. Carrier onset was detected on both labeled cases, with a held-out persistence limitation and no observed background groups across 40,169 unguarded minute probes. Provisional policy and open operational facts remain explicit. [Calibration](../docs/calibration.md) · [Threshold register](../config/rules.json)
- The focused offline tests passed with `python3.12 -B -m unittest discover -s tests -v`. Service behavior, official preflight and practice, and Ubuntu offline startup remain pending. [Requirement matrix](../docs/requirements.md)
- Regenerated both reports, both generated docs, and both config files using an absolute `--data` and temporary output directories. All six outputs matched byte for byte. The full calibration command took 69 seconds on the development host.

## Next phase

**P02 · Build the minimal runnable service and exact HTTP contract.** Pin Python 3.12 dependencies, validate configuration and six CSVs at startup, and implement readiness and the strict HTTP boundary before adding event storage and diagnosis. [P02 prompt](02_CODEX_PROMPTS.md#p02-build-the-minimal-runnable-service-and-exact-http-contract)
