# The Quiet Fleet working agreement

Use the candidate brief and the unmodified vendor contract as the source of truth. Read `planning/STATUS.md`, `docs/decisions.md`, and the relevant kit phase before working. Read the actual Form 1 and ops answers if available. Support and false-alarm aversion are provisional. If the submitted choice differs, update the persona plan and tests before building its endpoint.

Target Python 3.12 on Ubuntu 24.04. The grading entrypoint is `python -m quiet_fleet` on localhost:8080 with one worker and a fresh empty event store. Read the six reference CSVs from `QF_DATA_DIR` (default `./data`). Receive telemetry through HTTP. Install pinned dependencies separately. Runtime uses local assets and makes no outbound calls.

Use explicit query `at`, eligible original receipts, and observation order for facts. Keep receipt and observation time distinct. Deduplicate repeated IDs and semantic retries, including reboot commands. Platform events do not prove device contact. Handle legacy A epoch seconds and serial-less BX frames. Use `America/Toronto` for MSS and `America/Regina` for REG. Test the November 1 DST transition.

Keep recovery cause-specific. Backup transmissions do not resolve power loss, and booting does not prove recording. Use historical VIN evidence with the roster. Keep support-case labels out of current diagnoses. Put thresholds in validated config with units, comparators, and provenance.

Use one engine for status and the chosen persona endpoint. Follow the contract enums and provide reasons and eligible original event IDs. A support serial appears in at most one triage item. Return HTTP 400 for invalid parameters or envelopes and 404 for unknown catalog serials. Process valid neighbors in a mixed batch and safely ignore unknown event kinds.

Preserve vendor sources byte for byte. Keep production rules independent of practice IDs and dates. Run independent behavior tests and the unmodified exam from separate fresh processes, using an absolute `--data` path.

Work one authorized phase at a time. Preserve user changes, inspect the staged diff, update status, traceability and AI usage with actual results, and commit locally. Keep original inputs, telemetry, caches, databases, bulky outputs, and secrets out of Git. Publication, deployment, messages, and form submission require separate authorization.
