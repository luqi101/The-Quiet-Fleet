# Project status

## P00 · Source review and local setup

The materials folder had no Git metadata. The candidate selected a new child checkout. The verified fetch and push URL is `https://github.com/luqi101/The-Quiet-Fleet.git`. The checkout uses `main`. The upstream contained no commits at setup.

- Read the complete six-page candidate brief, required kit documents, pack README, contract, primer, practice notes and scenario, full runner, BX README, and CSV headers and examples. Restored the missing Form 3 worksheet from the original kit and verified the kit manifest.
- Validated the data ZIP member paths, file types and CRCs before extraction. Verified all 43 extracted files and their copies against the ZIP. The six tracked reference CSVs contain 251 assets, 360 devices, 8,957 jobs, 62 weather rows, 22 plan changes, and 179 cases. The 28 local replay files contain 640,419 envelopes, including 313 BX frames.
- Verified the nine preserved vendor sources with `shasum -a 256 -c SHA256SUMS` from `vendor/quiet-fleet/`. `git check-ignore -v` confirmed the exclusions for original inputs, extraction, telemetry, environments, databases, caches, and bulk outputs. The vendored Python runner's help command executed under Python 3.12.2.
- Reviewed the 30-file staged inventory and authored diff. All 23 supplied blobs in the index matched their archive entries exactly. The staged whitespace check passed with `git -c core.whitespace=cr-at-eol diff --cached --check` to allow the supplied CSV line endings.
- Recorded the source discrepancies, execution order, future modules, and verification scenarios. The service, official preflight and practice results, and release tests are pending. [Execution plan](../docs/decisions.md) · [Requirements](../docs/requirements.md) · [AI usage](../docs/ai-usage.md)

## Decisions and open facts

- Support and false-alarm aversion are **provisional**. No submitted Form 1 text or ops answers were available. Shared work can proceed. Check the actual submission and revise persona-specific sections before implementing a different endpoint.
- The unresolved operational facts are approved seasonal downtime scope and effective dates, and Larchmont’s high-priority deadline around the 06:00 local shift. Form 2 usage is unverified. The original kit retains its candidate topics, and new drafts depend on confirmed allowance.
- Python 3.12.2, pip 25.0.1, Git 2.50.1, SQLite 3.45.1, both depot time zones, and local PDF and ZIP tools were available. The pinned FastAPI, Uvicorn, and pytest environment belongs to P02. Docker and other checked local container tools were unavailable. Ubuntu 24.04 offline execution remains a P13 verification dependency.

## Next phase

**P01 · Reproduce the data audit and establish the threshold register.** Use the ignored local replay, derive separate calibration and validation cohorts, and record reproducible findings and threshold provenance before creating the service in P02. [P01 prompt](02_CODEX_PROMPTS.md#p01-audit-the-data-and-establish-a-defensible-threshold-register)
