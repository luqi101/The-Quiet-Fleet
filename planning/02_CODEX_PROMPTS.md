# Copy-ready Codex prompts

Use these in order from the repository root. They assume this kit is copied to `planning/`, the original brief is `inputs/candidate-brief.pdf`, and the ZIP is `inputs/quiet-fleet-data-pack.zip`. Keep one phase per message. The source documents remain authoritative if a planning recommendation conflicts with them.

P00 is a planning-only task that also organizes files and writes planning documents. Use a workspace mode that permits those writes; it must not implement the application yet. The later prompts authorize their stated implementation work. No prompt before P14 authorizes a public push or form submission.

## P00. Read everything and create the executable plan

```text
You are working in my local checkout of https://github.com/luqi101/The-Quiet-Fleet.git in VS Code. Your task in this phase is source-grounded planning and local input organization only. Do not implement the application, push, deploy, submit a form, or send a message.

First inspect the working directory, Git status, branch, remote, existing files, and applicable AGENTS.md instructions. Preserve any user changes. Do not assume the repository is still empty. Confirm that the remote is the exact repository above. Read planning/00_START_HERE.md, planning/01_IMPLEMENTATION_PLAN.md, planning/03_ACCEPTANCE_TEST_MATRIX.md, planning/04_FORM3_AND_LIVE_CALL.md, and planning/AGENTS.template.md completely.

Read inputs/candidate-brief.pdf completely, extracting text locally if necessary. Inspect the ZIP safely before extraction: reject absolute paths, traversal, or escaping symlinks. Extract its complete quiet-fleet-data-pack directory under .local/. Read its README, docs/CONTRACT.md, docs/PRIMER.md, exam/PRACTICE.md, exam/practice.json, the entire exam/qf_exam.py, new_hardware/README.md, and all CSV headers and examples. Do not summarize a file you have not actually read. The source brief and contract override a mistaken planning assumption.

Read planning/form1.md and planning/ops-answers.md if present. Identify the actual chosen persona and false-alarm/miss choice. This plan recommends support and false-alarm aversion but must not pretend those were submitted. If the real persona differs, continue shared architecture planning and explicitly adapt the persona sections before implementing that endpoint. If the submitted text is missing, record the support choice as provisional, not historical fact.

Organize reproducible local inputs. Copy the six reference CSVs to data/. Copy telemetry locally to data/telemetry/ for development replay only. Preserve the supplied docs, exam tool/scenario, and new-hardware files under vendor/quiet-fleet/ with original contents. Record hashes of preserved vendor sources. Create .gitignore before staging anything, excluding inputs/, .local/, data/telemetry/, .venv/, runtime databases, caches, and bulk transient results. Keep the small six CSVs available for default startup. Do not commit or publish the original telemetry corpus.

Create a concise root AGENTS.md using the template, adjusted only for source-confirmed facts and the chosen persona. Do not paste the whole prompt book into AGENTS.md. Create planning/STATUS.md with current phase, decisions, assumptions, completed checks, next phase, and known blockers. Create docs/requirements.md with every requirement mapped to a future module and a meaningful test. Create docs/decisions.md and an honest initial docs/ai-usage.md that records both this planning kit and your role. Preserve any real Form 1 text; never fabricate missing answers.

Produce an execution plan with dependency order, file responsibilities, event and reference data models, receipt-versus-observation semantics, exact/semantic deduplication, fault episodes and recovery, VIN-based historical assignments, outage grouping, calibration methodology, BX integration, HTTP error behavior, offline packaging, and final release gates. Resolve conflicts with the supplied plan explicitly. List operational unknowns separately from engineering choices. Draft the two recommended ops questions only if the allowance is unused; do not submit them.

Check the tools and Python version available locally and explain any missing prerequisite. Make a planning-only local commit after inspecting the staged diff. Finish by reporting the chosen/provisional persona, source discrepancies, the requirement matrix location, the exact next phase, and any genuinely missing business fact. Do not claim the service exists or tests pass yet.
```

Gate: the brief and entire API/exam contract have been read; actual Form 1 differences are visible; inputs are safe and organized; no runtime code or public push occurred.

## P01. Audit the data and establish a defensible threshold register

```text
Implement the offline data-analysis phase of The Quiet Fleet. Read root AGENTS.md, planning/STATUS.md, planning/01_IMPLEMENTATION_PLAN.md sections B, E, J, K, the vendor contract and primer, and the actual CSVs and telemetry. Do not implement diagnosis by copying case labels or practice answers.

Create scripts/audit_data.py and scripts/calibrate.py as deterministic, reproducible development tools. They must accept a --data directory, handle all supplied records, and output machine-readable reports plus readable docs. Do not make service startup call these scripts. Prefer streaming/SQLite aggregation over retaining every decoded JSON object in memory. Record source hashes, methodology, cohort filters, units, sample sizes, invalid records, and definitions.

Reproduce the supplied findings independently: 251 assets, 360 devices, 8,957 jobs, 179 cases, 22 plan changes, 640,419 envelopes; family/status counts; repeated IDs; semantic retries with new IDs; numeric legacy A timestamps; BX messages with no outer serial/device_time; long buffering delays; camera case action counts and firmware sample sizes; the negative case duration; observed replacement transitions; the stock tracker that actually reports; the seasonal stop pattern. Differences must be investigated, not hidden by forcing counts.

Calculate normal timing in meaningful cohorts. Tracker position cadence must exclude ignition-off/overnight gaps and retries. Heartbeat statistics must not replace the brief's fixed 4 h / 4 h 30 min rules. Measure camera recording cadence, sleep timing, wake/boot/recording delay, and unique reboot outcomes. Measure healthy A/BX daily jitter, low-battery trends, cold-day misses, and recovery. Quantify receipt lag separately from observation gaps. Report both labeled outages and ordinary non-outage windows for false grouping. Inspect VIN transitions without treating end-state inventory status as historical truth.

Use support cases as selected labeled training/evaluation examples, with explicit limitations. Do not assert a fleet-wide accuracy rate from only those cases. Exclude invalid case durations; keep the anomaly visible. Do not use future case closure or the eventual recovery of a gap as a feature available before it happened.

Create config/rules.json and config/calibration.json with clear sections for given rules, wire-format constants, calibrated parameters, operational assumptions, and defensive limits. Every threshold needs value, unit, comparator, source/provenance, rationale, sample size where relevant, sensitivity range, and test name. Initial candidates in the plan are hypotheses, not final calibrated values. Keep currently unsupported business choices labeled provisional. Never scatter fallback magic numbers through the future runtime.

Create docs/data-quality.md and docs/calibration.md. Include a temporal development/validation split such as Oct 4-24 versus Oct 25-31, threshold sensitivity, uncertainty in small firmware cohorts, and the distinction between aggregate training priors and a forbidden per-device answer lookup. Save concise auditable reports under reports/ and ignore bulky intermediates.

Validate the scripts against the actual pack. Add only meaningful tests for parsing/calibration logic whose failure would change policy. Update STATUS, requirements, decisions, and AI usage with actual results; inspect the diff; make a local analysis commit. Finish with measured findings, final/provisional thresholds, unresolved operational facts, and exact commands to reproduce the report. Do not push.
```

Gate: measured findings are reproducible and every policy constant is classified honestly.

## P02. Build the minimal runnable service and exact HTTP contract

```text
Implement the Python 3.12 service foundation only, following AGENTS.md, planning/STATUS.md, the vendor API contract, and plan sections C-D. The target start command is python -m quiet_fleet on localhost:8080. Resolve and pin a compatible tested runtime dependency set under Python 3.12; keep dev dependencies separate. No runtime install, download, AI/API call, or dependency on Node is allowed.

Create the package, entrypoint, config loader, reference loader, typed response/domain models, and FastAPI application lifecycle. Read QF_DATA_DIR, default ./data, and load all six required CSVs. Use actual CSV schemas and validate IDs/time fields sensibly. Do not read any telemetry directory, BX sample file, or notebook at startup. Create a fresh empty telemetry store for each normal start. Use one Uvicorn worker and no reload. Ensure reference/config initialization completes before /health returns {"status":"ok"}.

Implement GET /health; POST /ingest envelope validation; GET /devices/{serial}/status?at=; and GET /triage?at=. At this phase unobserved known devices may return the valid unknown representation and triage may be empty because no diagnosis is implemented, but mark that incompleteness explicitly in STATUS. Do not claim the behavior phase is done. Unsupported persona endpoints return 404.

Implement required output fields and fixed enums exactly. Confidence must be finite and 0..1. Reasons are nonempty lists of readable strings; evidence is a list of original event-ID strings. Known devices with no observations have null last_heard_at and empty evidence, not invented telemetry. Unknown inventory serial returns 404. Validate required at as an explicit aware instant and output UTC Z format consistently.

Return 400, not FastAPI's default 422, for missing/invalid parameters, invalid JSON, bad envelope shapes, missing/non-list events, and batches over 5,000. A valid events list must not be validated atomically as strict event models, because malformed individual events must not fail their neighbors. Isolate per-event validation in the next phase. Define and document accepted-count semantics. Handle empty batches and unknown routes deliberately.

Avoid external assets in default API docs. Either disable CDN-based docs or provide local assets; keep /openapi.json available if helpful. Do not implement the optional dashboard yet. Write README install/start instructions at the top with the exact commands that actually work. Include alternate QF_DATA_DIR usage and empty-start behavior.

Add HTTP-level tests for startup, alternate CSV directory, no telemetry startup read, health, missing/invalid at, unknown serial, empty ingestion, invalid envelopes, and enum/schema correctness. Test a minimal directory containing only the six CSVs. Run the relevant checks in Python 3.12. Update STATUS/traceability/AI log, inspect changes, and make a local commit. Do not push and do not describe placeholder unknown diagnoses as a completed solution.
```

Gate: service starts from README, has exact HTTP behavior, and does not preload telemetry.

## P03. Implement the temporal event store and idempotent mixed ingestion

```text
Implement the ingestion/time/store/projection foundation. Read AGENTS.md, STATUS, the vendor contract, plan sections D2 and E-F, the current code, and calibration findings. This is the correctness-critical phase: receipts determine knowledge availability; normalized device times determine event order.

Design a canonical logical-message representation and a separate receipt/event-ID alias representation. Preserve original event IDs, raw device_time, raw envelope type, normalized observation time, first eligible receipt, canonical payload, serial, and time-quality information. Use stable cryptographic fingerprints, parameterized SQL, useful serial/type/time indexes, and per-batch transactions. Default storage must be empty every start and bounded for the full corpus. Implement a single-worker-safe connection/lock/snapshot strategy and test it.

Deduplicate repeated event IDs and semantic duplicates with new IDs. Exclude received_at and event_id from semantic identity; include enough observation/source/payload identity to avoid merging distinct readings. Canonicalize JSON key ordering deliberately. Keep alias receipt times so evidence cannot cite a future alias. Retry receipts must not advance freshness, multiply reboot attempts, change cohort counts, or duplicate incidents. A conflicting event ID with different substantive content must not overwrite a valid observation; record the conflict safely.

Implement robust time parsing for aware ISO UTC/offset timestamps and legacy numeric A Unix seconds. Reject bool-as-int, nonfinite numbers, invalid types, unreasonable ranges, and unknown naive time formats. Keep seconds/milliseconds support explicit if added. Preserve late real observations instead of converting every large receipt delay into fresh data. Make the uncertainty policy for corrupt future clocks explicit. Decode no BX details yet if the adapter is not implemented, but preserve valid bx_raw envelopes for P08 without treating their missing outer fields as malformed.

For valid mixed batches, process good events even when bad events are interleaved. Accept/ignore unknown event types without refreshing health. Distinguish device-origin telemetry from platform commands/plans. Catch known per-event parsing failures, but let test-visible programming errors surface rather than silently returning false success. Return the documented integer accepted count.

Build an as-of query interface that filters by ingested receipt <= at and returns immutable facts ordered by credible observation time with deterministic ties. No GET may mutate incidents, attempts, acknowledgements, or behavior. Last arrival must not overwrite latest real ignition/fault/recovery state. Reference plan CSV rows must not be inserted as telemetry at startup; individual support case labels must not enter current diagnoses. Cache only with time and store-revision keys if caching is necessary.

Write tests proving: same batch twice gives identical domain responses; new-ID retry gives no freshness refresh; duplicate command counts once; out-of-order on/off reconstructs correctly; newer receipt carrying older recording cannot resolve newer error; a future-received observation cannot affect an earlier query; future-only evidence IDs are absent; known-no-data remains unknown; platform command does not count as device contact; concurrent read/ingest obtains a coherent snapshot. Test before/at/after receipt and observation cutoffs.

Run a preliminary full-corpus ingestion benchmark without needing diagnosis yet, using 5,000-event requests. Measure batch time and memory; optimize indexes/transactions if necessary without weakening temporal guarantees. Update docs/STATUS/traceability and make a local commit after tests pass. Report the schema, identity policy, accepted semantics, and measured performance. Do not push.
```

Gate: temporal and replay invariants pass before adding business rules.

## P04. Implement correct normal behavior for T, C, and A families

```text
Implement normal reporting/expected quiet behavior using the existing as-of projection. Read AGENTS.md, STATUS, plan sections F-G4, source brief device rules, and the validated threshold config. All behavior must be pure with respect to explicit at and shared between status and future triage.

Build effective asset context from inventory hypotheses plus eligible observations. Reconstruct ignition using ignition_on/off and position.ignition; speed zero does not mean ignition off. Do not globally suppress removed devices or pre-install replacements retroactively. Stock/no-data devices should not create fictional failures. Keep known-no-data status unknown unless authoritative context supports a different state.

T-series: use the short calibrated position cadence while ignition is on. With ignition off use the given 4-hour heartbeat and late-after-4h30m rule, including its documented exact boundary. A lack of positions while parked is not a fault if heartbeat/contact is within tolerance. Unknown ignition is uncertainty, not permission to assume a drive from a future schedule. Separate latest contact from latest fresh measurement so backfill does not imply a live position.

C-series: use the effective tracker on the same asset to understand ignition. Allow the 15-minute post-off transition and expected sleep thereafter. Recent sleeping after ignition off becomes quiet_expected/sleeping_by_design. Expire the old sleep explanation on a new credible ignition_on and apply a measured boot/wake grace. Booting is not recording. Do not implement fault recovery using any recent camera contact. Missing tracker context must be handled explicitly.

A-series: use daily cadence and measured jitter allowance, not T/C timing. Where enough past data exists, a causal per-device reporting phase may help estimate missed opportunities; sparse devices use family defaults. Derive phase only from available observations. Distinguish not-yet-due from one missed check-in and prolonged missing history. Leave battery/cold/fault refinements to the next phase without inventing none/reporting for overdue devices.

Implement reusable reason/evidence construction for normal and unknown cases. A reporting state must have likely_cause none. Expected quiet reasons must cite relevant ignition/sleep/check-in observations when available. No evidence ID may be synthetic or future-only. Explain the chosen last_heard_at convention consistently.

Add focused tests for all family timing boundaries, first-seen sparse devices, ignition zero-speed, sleeping transition at 15 minutes, camera wake on next ignition, parked heartbeat at/beyond 270 minutes, integer A timestamps, daily jitter, old backfill, and missing/ambiguous associations. Use synthetic IDs/dates, not only practice examples. Run all earlier temporal/HTTP tests too. Update STATUS/requirements/decision log and commit locally. Do not push.
```

Gate: normal quiet is distinguished from insufficient evidence and overdue reporting.

## P05. Implement individual fault causes, identity, and recovery episodes

```text
Implement the individual diagnosis layer from plan sections G5-G11 and the current data findings. Read the source contract, AGENTS.md, STATUS, config, and existing normal/temporal code. Model current episodes and competing evidence rather than assuming the latest message is the answer. Return only permitted causes; shared outage classification comes in P06.

Power: latch an unresolved episode on power_disconnect, corroborate backup_battery low_voltage, and keep it active through subsequent positions/backup messages. Clear only from later credible power_restore or a documented equivalent that actually supports restored external power. Do not confuse ordinary vehicle voltage with backup battery. Include key fault IDs. Verify the known practice pattern through an independent renamed fixture.

Camera: storage_error or sustained lack of recording while awake opens a fault episode after normal/plan explanations are considered. Count unique reboot commands in the current episode only. Recommend remote support first, supported by the 28/40 selected-case action prior. Escalate to a technician only after the configured failed attempts and a meaningful awake response grace. A command or booting is not success; newer recording resolves. Sleeping can reduce urgency but cannot prove storage repaired. A firmware with three cases must not drive a deterministic physical-repair shortcut.

Plans: order ingested plan changes by effective observation time; paused and ended both map to plan_paused; later active removes that cause. Platform plan events do not refresh device contact. Never let future CSV resume rows affect a past query. Do not mutate accounts or send commands from this recommendation service.

Assignments: infer temporal associations using VIN-bearing evidence and commissioning/transition context. A tracker marked removed at the end can still be historically active. A known stock serial with matching VIN can be installed despite a blank asset_id. Detect stale record mismatches as device_swapped and route to support. Preserve ambiguity when two live serials claim one VIN. Do not infer assignment from proximity alone. Do not create endless duplicate tasks for an already documented removed device whose replacement registry is consistent.

Battery: detect A low-battery trends using validated thresholds; do not require complete silence. Recovery must be later in observation time and cross documented hysteresis/replacement criteria. Cold does not override depleted battery. BX policy remains separate until P08.

Cold/downtime: use correct depot local dates and bounded grace. Integrate real ops replies from planning/ops-answers.md, with effective dates and provenance in config. Without confirmation, the landscaping stop pattern is evidence of a hypothesis, not proof that all landscaping can be silently ignored. Schedule absence alone cannot prove planned downtime. Explicit faults outrank benign guesses.

Coverage: use known isolated buffering/weak-signal/route patterns supported by past observations. While a gap is ongoing, do not use future backfill to claim you knew it was harmless. After backfill, distinguish restored transport from current measurement. Bound suppression, and return unknown when evidence cannot distinguish coverage from a fault. Do not classify every isolated silent tracker as power_loss or coverage_gap.

Document competing-cause precedence and how you select one likely_cause while explaining secondary constraints. Confidence is an evidence-strength score, not a fake calibrated probability. Ensure status reasons are actionable and causally specific. Add episode-recovery, conflict, temporal ordering, low-battery-in-cold, swapped-inventory, failed-reboot retry, and plan-resume tests. Run all prior checks, update docs/STATUS, inspect changes, and commit locally. Do not push.
```

Gate: direct faults survive irrelevant messages, and only valid later recovery clears them.

## P06. Detect and group carrier incidents without hardcoding

```text
Implement generalized carrier incident detection and its status integration. Read AGENTS.md, STATUS, plan section H, the two carrier-outage cases as training evidence, calibration reports, and existing per-device diagnoses. Do not use practice serial lists, event IDs, dates, or expected output files in production logic.

Construct comparable eligible peer cohorts by depot/carrier and reporting mode/family. Devices must actually be expected to report: ignition-on T trackers, awake cameras, or other independently due families with their own timing. Do not inflate denominators with sleeping cameras, parked heartbeat devices, daily tags not due, stock/no-data units, paused plans, confirmed swaps, or explicit physical faults.

Represent gap episodes so the cohort does not disappear merely because silence lasts longer than a recent-event lookback. Use last credible activity, missing deadlines, synchronized gap onset, independent-device count, affected eligible fraction, other-carrier live comparison, and optionally geographic spread. Keep thresholds in config with measured support. Detect both carriers and both depots. An end-of-shift quieting pattern or both-carrier interruption must not automatically become a particular carrier_outage.

Preserve stronger unrelated diagnoses. A power-disconnected tracker during a broad carrier issue must still have its own correct physical cause and owner. If a device is already explained by a compatible carrier incident, status should show the same cause as triage. Choose a clear needs_action/unknown policy and confidence from the available evidence.

Build deterministic incident objects with compatible members, correct carrier owner, meaningful reasons, affected assets, and original evidence IDs. Include key last pre-gap reports and useful live control reports; silence itself has no invented ID. Recover members only when evidence supports recovery. Test partial recovery, long incidents, recurrence, and group closure. The same query cannot mutate membership or create a new ID on every call.

Use only candidate members that need current action/follow-up. Do not absorb every device on the carrier. One final triage serial must belong to at most one item; preserve a provable partition. If evidence supports a shared interruption but not a specific carrier, retain honest uncertainty and proportionate support ownership rather than inventing carrier certainty.

Create renamed, rescheduled synthetic scenarios covering: a one-carrier mass stop with healthy peers; normal shift ending; multiple unrelated individual faults; an isolated coverage gap; both-carrier loss; one firmware across carriers; a physical failure during an outage; long duration; partial/full recovery; and a second later incident. Calibrate against ordinary windows as well as the two labeled outages. Run all earlier tests, update docs/STATUS and local commit. Do not push.
```

Gate: one true outage becomes one actionable group, with negative controls and no unrelated absorption.

## P07. Complete support triage, priority, evidence, and user-facing reasons

```text
Complete the support-agent product. Read AGENTS.md, STATUS, the chosen Form 1 policy and ops replies, plan section I, and the source contract. Use the same diagnosis engine for /status and /triage; do not implement independent endpoint-specific rules.

Implement the owner/action table: carrier incidents to carrier; power and depleted batteries to technician; new camera faults to support for remote recovery; meaningful failed remote attempts to technician; plan/account and unresolved record mismatches to support; uncertain prolonged operational risk to proportionate support follow-up. Normal parked/sleeping/confirmed downtime is suppressed. An item must explain what someone should do or follow up now.

Implement a single explicit high/medium/low priority policy using current jobs, upcoming deadlines, extent of impact, and actual time available to recover. Ask no new question if the ops reply already supplies it. Where the business meaning is still unknown, use the documented provisional horizon and mark it as an assumption in docs, not as a fact discovered in data. All numeric cutoffs go in config. Jobs use half-open [start,end) intervals.

Use America/Toronto for MSS and America/Regina for REG. Compute the next 06:00 shift from the local date and time; do not use fixed October offsets or make all shifts weekday-only just because technician visits are weekday-only. Test the Nov 1, 2026 DST fall-back and Regina's unchanged offset.

Construct one immutable evaluation context per request, build shared incidents first, then remaining actionable device items, and validate the final serial ownership partition. Device items contain exactly one serial; incidents contain multiple compatible devices. Sort deterministically by priority, operational deadline, and stable ties. Generate item IDs from logical issue identity, not wall time or randomness.

Improve reason strings: state the observation, UTC/local timing when useful, the missing expectation, competing explanation, and operational consequence. Next actions name a specific owner and step. Do not claim an action was executed. Evidence must include the key causal ID and relevant supporting device/asset/peer IDs, all ingested and received by at. Do not put CSV row numbers, case IDs, internal hashes, or invented outage IDs in evidence. Avoid huge unfiltered event dumps.

Add strict API tests for every owner/cause combination, priority timing boundaries, normal exclusions, repeated GET stability, status/triage agreement, incident and device uniqueness, deterministic ordering, and evidence referential validity. Confirm default response fields and allowed enums match the vendor contract. Run all relevant checks, update STATUS/docs/AI log, and commit locally. Do not push.
```

Gate: every emitted item is useful, correctly owned, unique, and evidence-backed.

## P08. Decode BX and prove it works through the real API

```text
Implement the optional BX work completely, because it is worth 10 points and the format is tractable. Read AGENTS.md, STATUS, plan section K, all 300 raw sample lines, all 3 portal rows, the 20 BX inventory entries, and actual bx_raw telemetry envelopes. The task is an inferred decoder, not a lookup table.

Verify this mapping independently: u is the exact inventory serial; t is hexadecimal Unix seconds in UTC; battery percentage is consistent with 100*b/4095; s bit 0x01 means moving, bit 0x02 low battery, bit 0x08 GPS fix; p is signed lat,lng integers divided by 100000. Preserve unknown bits, including 0x04, without inventing semantics. Three rounded battery anchors support this model but do not uniquely prove the vendor's full battery transfer function; document that limit. Do not call b millivolts.

Write exact tests for the three anchors: BX40471 / 6ADA16E0 / 3094 / 8 -> 2026-10-22T14:00:00Z, 76%, false,false,true, 50.42719,-104.56695; BX41085 / 6AD8D76C / 2583 / 9 -> 2026-10-21T15:17:00Z, 63%, true,false,true, 50.43083,-104.66817; BX47068 / 6AE4B4B0 / 573 / 10 -> 2026-10-30T15:16:00Z, 14%, false,true,true, 50.46073,-104.67404. Compare portal local time using America/Regina, UTC-6 year-round. Keep full battery precision internally and round only for display comparison.

Integrate the special envelope shape: bx_raw has only event_id, received_at, type, and raw; no outer serial, device_time, or payload. Decode the JSON string in raw, resolve u, and produce the internal battery/position observation retaining the original outer evidence ID. Process both normal and malformed BX events inside mixed batches without dropping valid neighbors.

Validate missing/bad fields, JSON types, finite ranges, battery bounds, flags as integers rather than booleans, hexadecimal timestamps, exactly two signed coordinate values, coordinate bounds, unknown serials, and GPS validity. A false fix bit means the coordinates cannot be claimed as a fresh valid fix. Unknown bits do not invalidate known meanings. Test combinations 0,1,8,9,10,11,12 and new valid combinations rather than a flag-value lookup.

Use the decoded daily reports in real /status and /triage decisions. Give BX its own daily-grace/low-battery policy; the low flag on a 14% unit cannot be missed by reusing A's below-10% rule. Handle stock/install timing, late/duplicate frames, unknown future bits, battery recovery, and no-fix reports. Never preload the 300 sample lines or portal answers at runtime. The stream contains more distinct frames, so verify those too.

Create docs/bx-decoding.md with mapping, exact anchor comparisons, inference limits, and regeneration commands. Add end-to-end tests that ingest a new valid frame and assert changed status/triage, plus new-ID retry idempotence. Run the full suite and replay-relevant checks, update STATUS/requirements, and make a local commit. Do not push.
```

Gate: all portal anchors match, and unseen valid frames affect the real service correctly.

## P09. Attack the implementation with independent behavioral tests

```text
Act as a skeptical verifier of the current implementation. Read AGENTS.md, STATUS, source brief/contract, the full acceptance matrix, and current code/tests. Do not assume a green existing test suite proves correctness. Do not spawn separate agents; perform a focused independent review in this session.

Implement any missing meaningful tests in planning/03_ACCEPTANCE_TEST_MATRIX.md and map them to requirements. Expected answers must come from the source rules and explicit scenario reasoning, not from calling the same production helper to calculate the expectation. Prioritize temporal noninterference, deduplication, causal recovery, historical inventory, competing causes, shared incident grouping, and BX integration.

Add metamorphic checks: renaming serials/assets while preserving references; changing event IDs; moving equivalent scenarios to other dates and carriers/depots while preserving local-time meaning; varying batch partitions up to 5,000; duplicating full batches; introducing new-ID aliases; permuting arrival order while keeping the final eligible receipt set equivalent; repeated GET requests. Domain results should preserve the relevant meaning, and evidence should map to the renamed eligible source IDs.

For as-of tests, ingest future-received events before querying an earlier at and prove they cannot influence state, cause, owner, priority, grouping, assignment, recovery, or evidence. Test a future alias of an old observation too. Contrast this with a newly ingested event whose received_at is genuinely earlier than at: that may legitimately add knowledge once ingested. Include old backfill arriving after newer faults and recovery.

Test malformed JSON/envelopes, bad elements between valid events, invalid/naive/future device times, booleans and nonfinite numeric fields, unknown event types/serials, same-ID conflicts, missing reference associations, and a clean directory containing only the six CSVs. Test precise threshold boundaries and Nov 1 DST behavior. Verify no unsupported enum or nonfinite confidence can escape serialization.

Audit every evidence ID in every synthetic response against eligible receipts. Verify key causal evidence survives deduplication. Check no serial appears in two triage items and no resolved episode remains permanently actionable. Assert commands do not become contact and the backup-power position sequence does not falsely repair power.

Review production code for practice-ID/date branches, per-device case-label lookups, wall-clock use, broad exception swallowing, unbounded runtime scans, multiple workers, future-sensitive caches, scattered thresholds, and startup corpus reads. Fix genuine defects with the smallest coherent change and add a regression test before calling them fixed. Never weaken a source-derived assertion simply to get green.

Run the meaningful full suite, lint/type checks configured by the repo, and report exact pass/failure counts and remaining concerns. Update traceability/STATUS/AI log with actual discoveries and commit locally only after relevant checks pass. Do not push. If a business ambiguity remains, document its effect rather than inventing an authoritative answer.
```

Gate: independent tests exercise the ways a plausible-looking solution could be wrong.

## P10. Run official preflight/practice and measure performance

```text
Run and harden the real service using the original vendor exam tool. Read AGENTS.md, STATUS, README, the vendor runner and practice notes, and the release requirements. Preserve the tool and practice JSON byte-for-byte and verify their recorded hashes before running. Never patch expectations, validators, or checkpoints to improve results.

Implement scripts/verify.py and scripts/release_check.py if not already present. They should report real command exit codes, start/stop only processes they own, wait for readiness with bounded polling, preserve diagnostic logs on failure, and prevent port collisions. Do not remove user files or kill unrelated processes. Document their arguments.

Start a fresh service and run: python vendor/quiet-fleet/exam/qf_exam.py preflight --data data --persona support --out reports/preflight. Capture exit status and warnings. Stop that process completely. Start a different fresh service with empty telemetry, then run: python vendor/quiet-fleet/exam/qf_exam.py practice --data data --persona support --out reports/practice. The explicit --data is required by our vendor layout. Do not run practice on the preflight-mutated store.

Investigate every failure and warning. Practice must get P1 carrier statuses/grouping, P2 camera fault/support reboot and sleeping-camera exclusion, and P3 latched power-loss/technician behavior correct. Root-cause failures in the generalized engine; never branch on practice identifiers. After a logic fix run focused regression tests and rerun the affected integration checks from a clean state. A final full practice run must use the final relevant logic.

Instrument real ingest request durations across the complete 640k-envelope corpus, with 5,000-event batches. Report maximum, percentiles, total replay time, query times, startup time, peak memory, and the test environment. The hard per-batch limit is 10 seconds; keep a practical internal margin. Check semantic duplicate counts and anomaly accounting. Optimize transactions/indexes/snapshot queries only where measured, preserving time and evidence semantics.

Test QF_DATA_DIR pointing to an alternate folder with renamed synthetic reference IDs and only six CSVs. The service must start without telemetry files. The exam tool is permitted to read corpus files for replay; the runtime service is not. Check start/restart produces empty state. Ensure requirements.txt contains all runtime needs without development-only tools.

Implement a reproducible offline smoke test after installation: forbid external connect/DNS paths in the test process or use a Linux network namespace/container with external egress disabled while retaining loopback. Exercise startup, ingest, status, triage, and any UI assets. A plain statement that no network library was imported is insufficient; record what was actually tested. If the environment cannot enforce a network namespace, use and describe the strongest available socket-level/process test and retain the remaining limitation honestly.

Save concise reports and exact commands. Update STATUS, README, requirement links, and AI log with actual outcomes. Make a local commit after checks pass. Do not push, and do not claim hidden-exam success from the three sample checkpoints.
```

Gate: clean official integration, actual timing measurements, and tested offline behavior.

## P11. Make the result presentable without introducing a second product

```text
Polish the support-agent product only after required correctness and integration gates pass. Read AGENTS.md, STATUS, plan section M, README, actual API outputs, and release reports. If earlier gates are failing, fix them first and defer optional presentation.

First improve the mandatory presentation: README install/start first, a three-sentence persona, clear endpoint examples, the trade-off and its code/config locations, architecture explanation, calibration summary, BX proof, actual test commands/results, known assumptions, and a concise demo. Keep evidence-linked reason strings readable and operational. Make next_action concrete without implying it was executed. Ensure the public repository is navigable without reading this entire prompt kit.

Then, if all correctness gates remain green, implement a small optional offline dashboard served by the same Python process at /. Use plain local HTML/CSS/JavaScript; no React, Node build, CDN assets, external fonts, icons, analytics, map tiles, or AI calls. It should consume the same /triage and /status responses and contain no independent diagnosis logic.

Required dashboard behaviors: explicit as-of UTC input with clear depot/local-time context; triage items showing cause, owner, priority, assets/serials, reasons, and next action; filters that affect presentation only; a device lookup; an evidence detail drawer; visible empty-store and loading/error states; keyboard-accessible controls; readable contrast; sensible desktop and narrow layouts. Escape data before rendering; do not insert event values as unsafe HTML. Default to an explicit available checkpoint or latest ingestion context rather than today's wall clock. Do not auto-load the history or mutate anything from a GET.

Keep grading endpoints and schemas unchanged. Do not expose fake fleet/scheduler success routes. If interactive API docs are included, ensure their assets work without internet. A local /openapi.json and README examples are sufficient if interactive docs would add unnecessary dependencies.

Verify the dashboard against real replayed responses, malformed API errors, empty state, and an offline browser/network environment if available. Verify no external requests are required. Add only meaningful tests for rendering/data handling and same-API behavior; do not create extensive tests for cosmetic spacing. Re-run the relevant API and integration smoke checks after any server change.

Update README screenshots only from actual current output, include an explicit statement that the UI is optional, and keep runtime dependencies minimal. Update STATUS/AI log and commit locally after verification. Do not deploy or push.
```

Gate: the reviewer can understand and demonstrate the actual decisions offline.

## P12. Generate the real submission evidence and live-call notes

```text
Prepare submission materials from the implemented service, not hypothetical outcomes. Read AGENTS.md, STATUS, the brief's Form 3 questions, planning/04_FORM3_AND_LIVE_CALL.md, actual Form 1 and ops answers, final config, code, reports, and the honest AI log.

Implement scripts/capture_end_state.py to start or use an explicitly fresh service, stream the provided history through /ingest in receipt order, and query /triage at exactly 2026-10-31T23:59:00Z. Do not set at to midnight, local time, or the host's present date. Save the complete response and extract the top three current support actions using the service's documented ordering. Preserve item IDs, cause, owner, priority, serials/assets, reasons, and key evidence. If fewer than three items are actionable, say so; do not invent extras. Verify evidence receipts are available by the checkpoint.

Generate docs/form3-draft.md answering all nine actual questions. Include the exact public repository URL, what works and precise tests, every chosen threshold with provenance, the real trade-off and implementation locations, BX mapping/validation, actual final-history top actions, true changes from Form 1, an actual AI mistake and how caught or honest independent verification if no mistake was recorded, and a product note of at most 300 words. Link to detailed calibration/docs instead of hiding missing thresholds behind vague prose. Do not claim 100% accuracy or hidden-exam results.

The AI usage log may be a concise honest log as permitted by the brief. Record this ChatGPT planning/analysis, Codex-generated implementation, important prompts/phases, human decisions, and actual corrections/verification. Never fabricate a chat export, fake timestamps, an AI error, manual authorship, or an earlier Form 1 statement. Avoid copying personal account details or secrets into the public repository. Distinguish my personal review steps from checks you actually executed.

Write docs/live-call.md for the 45-minute session: a reproducible short demo on a fresh checkpoint, a tour of temporal/dedup/fault/grouping/BX modules, defense of calibration and trade-offs, a small config-change rehearsal with a focused test, and honest limitations. Include instructions to reset the service and replay fresh data. Explain why a direct fault stays latched through backup reports and why case labels are not runtime answers.

The product note should define a first version, support-agent user, customer value, and measurable 60-day outcomes such as avoidable-ticket volume, duplicate alerts, remote resolution, time to correct owner, and tracking/video gaps before scheduled work. Include denominators/baselines and the guardrail of not increasing confirmed missed faults. Label business targets as proposed measures, not measured results from this fictional deployment.

Verify word count, links, config/code references, actual command outputs, and consistency with the final build. Update STATUS/AI log and make a local commit. Do not submit forms, send messages, or push. Finish by listing what I must personally review and explain in my own words before submission.
```

Gate: no fabricated top actions, test claims, form history, or AI disclosure.

## P13. Conduct the final release review and fix real defects

```text
Perform a final source-based release audit of The Quiet Fleet. Read the brief and unmodified contract, AGENTS.md, all requirement/test matrices, STATUS, final code/config, README, reports, BX proof, and submission draft. Review independently in this session. Do not push, deploy, submit, or ask for approval of a vague unfinished result.

Assess correctness first: as-of receipt filtering at every layer; observation-time ordering; legacy and BX times; semantic replay idempotence; future-alias evidence; reference leakage; startup emptiness; historical removed/stock inventory; cause-specific recovery; camera remote-first escalation; compatible carrier grouping and negative controls; status/triage consistency; allowed values; owner/priority rules; local dates/DST; deterministic serial partition; and real evidence.

Assess operation: Python 3.12 compatibility; exact one-command startup; six-CSV QF_DATA_DIR override; no corpus/sample file reads at startup; one worker/no reload; no runtime external calls or assets; pinned installed dependencies; malformed-event isolation; 400/404 behavior; 5,000-event batch latency; bounded memory; clean shutdown; startup after a previous run. Read the README as if you have a fresh Ubuntu 24.04 machine and no local history of our work.

Run a fresh-environment installation and the full meaningful suite. Run official preflight and practice against separate fresh instances using the final submitted source, preserving original vendor hashes. Execute the strongest available offline smoke test. If a Linux/Ubuntu environment or genuine network isolation is unavailable, report that exact gap and provide the concrete command or artifact for me to run; do not mark that gate passed. Do not substitute a macOS run for a claim of Ubuntu verification.

Review the public-facing files for unfinished TODOs, placeholders, fabricated metrics/actions, secret paths/keys, personal data, unnecessary corpus blobs, accidental runtime databases, broken links, and claims stronger than evidence. Ensure the threshold register lists all chosen cutoffs including business and defensive ones. Ensure optional UI has no separate logic or egress. Confirm Form 1 deviations and AI assistance are explicit.

Classify findings by actual consequence. Fix every genuine contract or behavioral defect within scope, add regression coverage, and rerun the affected checks. After logic changes, rerun final practice from empty state. Do not change expected answers to hide a failure or refactor unrelated working code for style alone.

Produce reports/release-readiness.md with commit/source identity, environment, exact commands, observed results, per-requirement status, timing/memory evidence, unresolved business assumptions, and explicit remaining blockers. Update STATUS and local commits. A clean release report may still state hidden-exam uncertainty; that is not a reason to invent passing results. Finish with a concise ready/not-ready decision and exact remaining action. Do not push.
```

Gate: all executable checks actually passed, with honest limits and no known unresolved contract defect.

## P14. Publish the reviewed result when submitting

Paste this only when you are actually ready to publish and submit. Earlier phases intentionally keep the work local, as the brief requests.

```text
I am now ready to submit The Quiet Fleet. Publish the reviewed local work to https://github.com/luqi101/The-Quiet-Fleet.git. This is the authorized final publication step, not permission to change decision logic or invent test results.

Read AGENTS.md, planning/STATUS.md, reports/release-readiness.md, and git status/log/remotes. Confirm all required release gates are recorded as actually passed and that any final code/config changes since those checks have been verified. If a genuine release blocker remains, complete the necessary in-scope fix and verification first; do not publish a known broken submission or conceal the blocker.

Inspect exactly what is tracked/staged. Exclude telemetry corpus, input ZIP/PDF copies unless deliberately needed, virtual environments, caches, runtime databases, secrets, personal details, and bulky transient artifacts. Preserve all meaningful development commits and honest timestamps. Ensure README, small reference CSVs, vendor contract/exam files, config, tests, concise reports, AI usage log, and Form 3 evidence are present. Do not force-push, rewrite published history, or overwrite remote work.

Verify the exact origin URL and branch. Fetch remote state and compare before pushing; if new remote work exists, reconcile it without discarding it. Push the intended reviewed branch to main using a normal push. If authentication or connectivity fails, state the exact failure and the safe next command; do not claim publication succeeded.

After a successful push, verify the remote commit SHA matches the reviewed source and the repository is publicly accessible. Record the submitted commit SHA locally and in the final handoff as appropriate. Do not make a misleading post-publication logic change. Do not send emails or submit Form 3 for me.

Return the public repository link, submitted commit SHA, exact start command, final observed verification summary, the Form 3 draft location, and the reminder that I must personally review and submit the form. Keep any real blockers explicit.
```

## Remediation prompt when a phase fails

```text
Resume the current phase from planning/STATUS.md. Read its acceptance criteria and the actual failing output. Find the root cause against the source brief/contract, reproduce it with a focused independent test, implement the smallest coherent fix, and run the relevant regressions. Do not weaken source-derived expectations, patch the vendor runner, hardcode a sample answer, or skip a failed gate. Preserve user work and previous valid behavior. Update the decision/AI log with the actual mistake and how caught. Report the specific fix, executed evidence, and whether the phase now passes. Do not push.
```

## Session-resume prompt

```text
Continue The Quiet Fleet from the current local checkout. Read root AGENTS.md, planning/STATUS.md, the requirement matrix, the relevant phase in planning/02_CODEX_PROMPTS.md, and git status/diff/log. Verify what exists and what actually passed; do not assume a previous narrative is proof. Preserve unfinished user changes. Resume the first incomplete phase, with the original source contract and current persona/ops choices authoritative. Complete its code and meaningful checks, update STATUS, and commit locally when green. Do not repeat completed corpus analysis without a concrete reason and do not push before the final submission prompt.
```

## Persona adaptation prompt, only if the actual Form 1 chose another persona

```text
My actual Form 1 persona is recorded in planning/form1.md and differs from the support recommendation. Read that exact text, the original brief/contract, AGENTS.md, the shared implementation plan, and existing code. Preserve the shared ingestion, temporal reasoning, status engine, calibration, and BX work. Rewrite the persona-specific plan and tests around the actual chosen persona before implementing its endpoint. Record the change and its trade-off honestly. Do not expose multiple placeholder personas.

If Fleet manager: implement /job-cover with depot MSS/REG, hours 1..72, required at, and only jobs starting in [at,at+hours). Diagnose location/video usability from effective associations. Normal sleeping before a future ignition should not force a swap. A carrier outage does not mechanically justify swapping every affected original job; the sample accepts keep/omission for outage-only jobs, while an outage-affected asset is not a usable replacement. A physical power failure before the next job does require viable cover. Swaps must preserve exact asset type and depot, require credible visibility/recording as appropriate, respect all scheduled and proposed allocations for the entire job slot, and never create overlap. Use half-open intervals. Minimize unnecessary moves and handle the full window jointly rather than a greedy approach that wastes the only feasible replacement. Document the objective and validate against small exhaustive fixtures. Return only contract fields/enums, valid swap_to/null, reasons, and real evidence. Ask an operational question if camera requirements for assets without installed cameras are genuinely unspecified; do not label every camera-free asset broken.

If Field-tech scheduler: implement /visits with days 1..3, required at, each depot's local day of at and following days-1, visits strictly after at, Monday-Friday 07:00..15:00 local, at most 6 per depot per local day. Use America/Toronto and America/Regina, not fixed October offsets. Only hands-on faults qualify: no carrier, normal sleep, account-only issue, record mismatch, or camera awaiting its first remote attempt. Bundle compatible serials on the same asset where appropriate. Rank by actual job/shift risk; choose a documented justified visit duration because capacity does not itself imply one hour. Schedule only slots satisfying the complete window and represent every necessary unscheduled asset in deferred with a clear reason, including weekends, elapsed workday, horizon, and capacity limits. Do not book outside the requested horizon to make deferred disappear. Test both depots, DST, equal-time boundaries, oversubscription, failed camera reboots, and same-asset bundling.

Update AGENTS.md, prompt commands/persona flags, requirement traceability, actual Form 3 changes, and the acceptance matrix consistently. Add exhaustive small-fixture tests for allocation/slot constraints and run the appropriate official practice persona. Do not claim support-specific prompts alone fully specify these alternative products, and do not push.
```
