# The Quiet Fleet working agreement

Build the support-agent service described by the supplied brief and the unmodified vendor API contract. Read `planning/01_IMPLEMENTATION_PLAN.md`, `planning/STATUS.md`, `planning/form1.md`, and relevant ops answers before a phase. The source brief and contract take precedence over a mistaken plan; record discrepancies and fix the plan.

Use Python 3.12. The finished one-command entrypoint is `python -m quiet_fleet`, on localhost:8080. Honor `QF_DATA_DIR` (default `./data`). Start with empty telemetry every normal process start. Read the six reference CSVs but never load telemetry JSONL, BX sample messages, or calibration notebooks at runtime. Use one application worker and no reload.

No outbound calls, AI APIs, dependency installation, CDN assets, or network-dependent documentation at runtime. Resolve and pin tested dependencies during the install phase. Keep development-only dependencies separate.

Every decision uses explicit query `at`, only ingested receipts available by that time, and correctly ordered normalized observation times. Never use the host clock for business decisions. Preserve raw timestamps and original evidence IDs. MSS uses America/Toronto; REG uses America/Regina. Test the November 1 DST transition.

Ingestion isolates malformed individual events, ignores unknown event types safely, and deduplicates both repeated event IDs and identical readings with new IDs. Retries do not refresh health or count as new reboot attempts. Platform commands and plan changes are not device contact. Handle legacy A Unix-second times and serial-less BX envelopes explicitly.

Keep fault episodes and recoveries cause-specific. Backup-power positions do not resolve a disconnect; booting/commands do not prove camera recording. Static inventory status is not a historical assignment log. Use VIN evidence carefully. Do not use individual support-case labels as an answer lookup.

One engine supplies status and triage. All thresholds and operational cutoffs belong in validated config with units, provenance, comparator, and tests. Causes, states, owners, and priorities must use contract values. A triage serial appears at most once. Reasons must explain the decision; evidence must cite available original event IDs.

Return 400 for missing/invalid parameters and bad envelopes, 404 for unknown catalog serials. Do not rely on FastAPI's default 422. Do not reject an entire mixed batch because one element is invalid. Implement only the chosen persona endpoint; unsupported personas return 404.

Do not hardcode practice serials, asset IDs, event IDs, dates, answers, or portal rows in production rules. Preserve vendor exam/contract files byte-for-byte. Practice passes are necessary but not proof of hidden correctness. Never weaken a legitimate test to match a bug.

At the end of every phase, run the relevant checks, inspect the diff, record actual commands/results and remaining assumptions in `planning/STATUS.md`, update requirement traceability and the AI log, and make a meaningful local commit if the checks pass. Do not invent measurements, checks, AI mistakes, or prior form answers.

Preserve user work. Do not use destructive Git cleanup, force-push, amend published history, fabricate dates, send communications, or submit forms. Keep development commits local. Push only when the user executes the final submission prompt. Keep large telemetry, inputs, virtual environments, runtime databases, and secrets out of Git.

Work one requested phase at a time. Complete its implementation and verification before reporting it done. Use reasonable reversible implementation decisions without repeated permission requests. Ask only for a materially missing business decision or an action outside the requested phase, while continuing independent work.
