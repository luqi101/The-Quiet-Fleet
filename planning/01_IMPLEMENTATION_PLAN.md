# The Quiet Fleet: implementation specification

## A. Goal, authority, and scope

Deliver a localhost service for **one persona**, the support agent, that explains whether fleet devices are reporting normally, intentionally quiet, failing, or uncertain, and gives a deduplicated, actionable queue. It runs on Ubuntu 24.04 with Python 3.12, starts with one documented command, and works with networking disabled after dependencies have been installed.

Source authority is the candidate brief, the pack's `docs/CONTRACT.md`, and the concrete request/response behavior exercised by `exam/qf_exam.py`. Practice expectations are acceptance examples, not a list of IDs or dates to special-case. General public documentation supports implementation mechanics, not fictional business rules.

This specification recommends support and a false-alarm-averse policy. If the actual Form 1 differs, record the difference before implementing persona-specific logic. Do not silently claim that this was the submitted choice. Shared ingestion, temporal reasoning, hardware decoding, and device status remain useful for every persona.

Mandatory output endpoints for support:

| Endpoint | Required behavior |
|---|---|
| `GET /health` | `200 {"status":"ok"}` only after startup validation completes |
| `POST /ingest` | Mixed batches, maximum 5,000 events, per-event error isolation, integer `accepted`, under 10 seconds |
| `GET /devices/{serial}/status?at=...` | Required fields, allowed enums, as-of reasoning, evidence, 404 for unknown inventory serial |
| `GET /triage?at=...` | Only current action/follow-up, one ownership item per device, meaningful owner and priority |

Do not implement fleet or scheduler endpoints as empty success responses. They are not required for support and can interfere with persona autodetection. Return 404 for unsupported paths.

## B. Verified findings from this exact pack

The following were measured directly, rather than copied from approximate figures in the brief. Treat them as findings to reproduce in P01, not constants to bake into runtime logic.

| Finding | Measured result | Implementation consequence |
|---|---:|---|
| Assets | 251 | Iterate actual reference rows; do not assume “about 260” |
| Devices | 360 | A=76, BX=20, C=93, T=171 |
| Device inventory status | 341 active, 13 stock, 6 removed | Status is not a complete historical assignment timeline |
| Jobs | 8,957 | Schedule extends through November 3 |
| Support cases | 179 | Training evidence, not a runtime answer table |
| Weather rows | 62 | Local dates for MSS/REG, through November 3 |
| Plan changes | 22 | CSV copies history events; streamed changes can supersede them |
| Telemetry events | 640,419 | Full replay performance must be measured |
| Exact-ID duplicate excess | 5,353 | Event-ID deduplication is necessary |
| Semantic duplicate excess | 7,609 | Identity ignoring ID/receipt finds 632,810 logical messages under the audit's raw semantic definition |
| New-ID aliases beyond semantic messages | 2,256 | ID-only deduplication misses real retries |
| Retry receipt delay | Median 301 s, maximum 599 s | A retry can otherwise make stale telemetry look fresh for almost 10 minutes |
| A-series firmware 1.9.0 timestamps | 252 raw events use numeric Unix seconds | Do not require every `device_time` to be an ISO string |
| BX telemetry envelopes | 313; 308 distinct raw messages | More than the separate 300-message decoder file; decoding cannot be a lookup table |
| Typical tracker positions while ignition stays on | Median 120 s; p95/p99 123 s | Calibrate a short driving gap, separately from parked heartbeats |
| Typical camera recording cadence | 300 s median | Camera freshness differs from tracker freshness |
| Healthy daily A check-ins, restricted audit cohort | 1,734 intervals, p99 88,500 s, max 88,800 s | A 24-hour hard cutoff would create routine false alarms |
| BX consecutive reports | Median 86,340 s, max 89,940 s | Approximately daily, with a distinct calibration cohort |
| Camera-fault case fixes | 28 remote reboots, 12 technician visits | Remote action first, escalate using current failed-attempt evidence |
| Camera firmware 4.2.1 cases | 27 reboot, 10 visit | Enough to support a remote-first prior |
| Camera firmware 4.3.0 cases | 1 reboot, 2 visit | Only three cases; do not convert this into a deterministic firmware rule |
| Cold-weather cases | 23, all no-fault/no-action | Observed overnight lows range from -10 C to -16 C |
| Power-loss cases | 14, all technician visits | Strong physical-fault evidence routes to a technician |
| Battery-low cases | 11, all technician visits | History notes cite battery below 10% for A tags |
| Coverage-gap cases | 14, all no action after backfill | Isolated silence needs context before dispatch |
| Seasonal pattern | All 12 landscaping trailers stop after October 23 | Suggests planned winter downtime, but requires operational confirmation |
| Case quality issue | CS-0016 closes 5 minutes before opening | Exclude invalid duration calculations; do not silently “repair” timestamps |

The semantic duplicate count above uses normalized JSON key order but the original device time and payload content. A production normalizer may merge additional representational aliases, so report its definition rather than forcing its count to match a different definition.

Observed receipt delays are normally a few seconds. Long T-series delays reach approximately 90 minutes, consistent with buffering. No negative receipt-minus-device-time values were found in this supplied history. Clock-skew handling is still needed defensively; do not invent a measured skew problem that was not present.

Two important identity findings:

* `T-59271` is marked `removed` in the CSV, but appears among the affected trackers in P1 on October 12. Its replacement `T-52798` begins reporting later, on October 19. Filtering all removed devices would fail a known checkpoint.
* `T-58830` is marked `stock` with no assigned asset but sends 1,084 telemetry rows in this history. VIN evidence must be able to override the static assignment hypothesis. A stock record with no telemetry is a different situation.

Two important causal findings:

* P3's `T-59847` disconnects at 18:10, reports backup-battery low voltage at 18:20, and still emits position messages through approximately 18:28. A position message does not prove that external power was restored.
* P2's failed camera has no newer recording event at the checkpoint. Its previous sleeping status must not conceal a later `storage_error`.

## C. Requirements and evidence matrix

Implement the matrix as a living file at `docs/requirements.md`, with exact code/test links when available.

| ID | Requirement | Implementation locus | Verification |
|---|---|---|---|
| R01 | Python 3.12 / Ubuntu 24.04 | requirements, entrypoint | Fresh Linux install |
| R02 | One offline start command, port 8080 | `__main__.py` | Offline startup process test |
| R03 | Honor `QF_DATA_DIR`; default `./data` | `reference.py` | Alternate directory and minimal six-CSV fixture |
| R04 | Empty telemetry on every normal start | store factory | Stop/restart test |
| R05 | No runtime telemetry-file loading | API dependency boundary | Poison/missing telemetry-directory test |
| R06 | Health readiness | startup lifecycle | Healthy only after references/config are valid |
| R07 | Mixed batches <=5,000; 10-second limit | API/store | Full replay latency measurements |
| R08 | Bad event does not reject good neighbors | ingestion normalizer | Mixed malformed batch |
| R09 | Unknown event types accepted and ignored | normalizer | Unknown-type fixture |
| R10 | Exact and semantic retry idempotence | event identity/store | Repeated batches and new-ID aliases |
| R11 | Arrival order does not overwrite newer facts | projection | Shuffled ingestion fixtures |
| R12 | As-of receipt cutoff | every query layer | Future-arrival noninterference |
| R13 | Device observation time preserved | normalizer/projection | Buffered old message test |
| R14 | T parked timing: 4 h + 30 min | config/T rules | Before/at/after boundary |
| R15 | T driving timing is separate | calibrated T rule | Ongoing drive gaps |
| R16 | C sleeps after ignition off +15 min | C/asset context | Transition and next-ignition tests |
| R17 | A daily timing with justified grace | A/config | Daily jitter, missing opportunities |
| R18 | Power fault survives backup messages | diagnosis episodes | P3 and synthetic reproduction |
| R19 | Camera fault recovery and escalation | camera episode/actions | Error, reboot, timeout, recording |
| R20 | Plans ordered and recoverable | plan facts | Paused, ended, active, backdated arrival |
| R21 | Historical assignment/VIN inference | assignment projection | Removed-before-swap and stock VIN tests |
| R22 | Battery/cold/downtime do not hide faults | competing evidence | Low battery on cold day |
| R23 | Shared carrier diagnosis generalizes | incidents | Both carriers/depots, negative controls |
| R24 | Triage has one item per serial | ownership partition | Set uniqueness invariant |
| R25 | Correct owner and priority | triage policy | Decision table and job/shift boundaries |
| R26 | Real evidence IDs, available by `at` | evidence builder | Referential and temporal audit |
| R27 | Valid fields/enums/confidence | response schemas | Official validators plus strict own checks |
| R28 | Invalid params 400, unknown serial 404 | exception handlers | HTTP contract matrix |
| R29 | All chosen thresholds in config | config validation | Threshold registry/code review |
| R30 | Thresholds justified from history | audit/calibration report | Reproducible scripts and sensitivity report |
| R31 | BX decoded and used in decisions | `bx.py`, A-like rules | Three anchors, malformed inputs, replay |
| R32 | Official preflight and practice | release scripts | Separate fresh services, unmodified tool |
| R33 | Honest AI disclosure and commits | docs/commit history | Human review |
| R34 | Actual final-history top three | capture script | Saved API response and reasoned extraction |
| R35 | Product note <=300 words | Form 3 draft | Word count and human review |
| R36 | No public push before submission | workflow | Git remote log/release checklist |
| R37 | Can explain and make a live change | live-call notes | Rehearsed config change + focused test |

## D. Recommended architecture

Use a compact Python service, not an online ML system. The task is mostly temporal logic, explicit evidence, and operational decisions. An interpretable rules engine with calibrated thresholds is easier to validate and defend than a classifier trained on 179 selected support cases.

### D1. Runtime components

| Component | Responsibility |
|---|---|
| API layer | Transport, parameter validation, response schemas, consistent errors |
| Reference catalog | Assets, devices, jobs, weather, historical plan metadata, case-training metadata |
| Normalizer | Validate one event, parse time, decode BX, retain raw identity/provenance |
| Event store | Append logical observations and receipt/alias provenance, with indexes |
| As-of projection | Build device, asset, assignment, plan, fault, and peer facts at a requested time |
| Diagnosis rules | Evaluate competing causes and return an explained diagnosis |
| Incident builder | Correlate current compatible failures without duplicating serials |
| Triage policy | Owner, priority, next action, stable ordering, actionable suppression |
| Development tools | Data audit, calibration, synthetic scenarios, replay, release verification |

Keep FastAPI route functions thin. Domain functions should accept explicit inputs and `at`, return typed values, and have no wall-clock or network dependency. Do not put all rules in one endpoint function.

### D2. Event storage

Use the standard-library SQLite interface. Prefer a fresh temporary on-disk SQLite database for each process to keep memory bounded; an in-memory database is acceptable if the full replay benchmark confirms acceptable memory. Never reuse a previous run's database by default. A persistent debug mode, if added, must be explicitly separate from the documented grading start command.

A reasonable schema has:

* `messages`: internal key, serial, original type, normalized type, normalized observation time, time-quality flags, canonical payload, first receipt time, and raw source data needed for explanation.
* `receipts`: logical-message key, original event ID, original receipt time, original-envelope hash. This is provenance, not another observation.
* `reference_*`: loaded reference rows, separate from telemetry.
* Optional derived indexes or projections that can be recreated from messages and do not determine answers using future information.

Index by serial and observation time, serial and first-receipt time, event type, and event ID. Use parameterized SQL and bounded per-batch transactions. Avoid per-event commits.

Run a **single Uvicorn worker**. Multiple independent workers with separate local state would ingest into one process and answer from another. Disable reload in the grading command. Use a tested connection strategy and serialization boundary: for example, one SQLite connection with `check_same_thread=False` plus a lock around all database access and snapshot construction. Keep expensive rule evaluation outside the lock after extracting an immutable snapshot. Alternatively, use separate connections with correct transaction snapshots; do not introduce this complexity without tests.

`GET` requests must not acknowledge incidents, increment failed attempts, choose different priorities because they were called twice, or create ongoing state. Response caching, if necessary, must include the query time and a store revision and must invalidate on relevant new information.

### D3. Dependency and packaging policy

Runtime dependencies should remain small: FastAPI, Uvicorn, Pydantic as required, and `tzdata` where cross-platform zone data is needed. SQLite, CSV, JSON, hashing, and datetime operations use the standard library. Use separate development dependencies for pytest, HTTP client tests, lint/type checks, and optional property tests.

Resolve and pin a mutually compatible dependency set under Python 3.12 during implementation. Do not copy guessed “latest” version numbers from this plan. The exact tested versions belong in committed requirements files. No install or download may occur in the start command.

FastAPI normally uses 422 for request validation errors. Add a deliberate `RequestValidationError` handler returning the required JSON 400. Validate the batch envelope first, then validate each event independently; an all-or-nothing typed list of strict event objects is unsuitable for malformed mixed batches.

Disable CDN-backed interactive documentation unless its assets are vendored. `/openapi.json` is fine locally. Default Swagger or ReDoc pages can try to fetch external JavaScript; a service that runs offline should not rely on them for its presentation.

## E. Temporal correctness and ingestion semantics

### E1. Three different times

Maintain these distinctions:

| Time | Meaning | Rule |
|---|---|---|
| `received_at` | When the platform obtained the envelope | Whether information was available by query `at` |
| `observed_at` | Normalized device observation time | Order ignition, power, camera, battery, and position facts |
| Request `at` | Hypothetical evaluation instant | All freshness, local business dates, and priorities use this |

The host's current date is irrelevant. Tests should fail if replacing the host clock changes an answer for the same input and `at`.

For a query, use only logical observations with an ingested receipt at or before `at`. Among those, reconstruct state by trustworthy observation time. A late old `ignition_on` cannot overturn a newer `ignition_off`. A late pre-fault `recording` event cannot resolve a newer storage fault. A delayed low battery reading cannot overturn a later battery replacement. A future-dated device clock cannot make a reading valid forever.

For trustworthy observation times later than `at`, do not apply the observation as a past fact. If the timestamp is demonstrably corrupt, normalize under an explicit uncertainty policy rather than silently treating future evidence as real. Preserve raw time and time-quality reasons.

### E2. Timestamp parser

* Accept timezone-aware ISO timestamps and normalize to UTC. A canonical output timestamp ends in `Z`.
* Accept actual numeric Unix seconds for the supported legacy A firmware. Reject booleans as timestamps; Python treats them as integers unless explicitly guarded.
* Decode BX hexadecimal epoch seconds through the BX adapter.
* Do not interpret arbitrary naive strings in the host timezone. If a known firmware format is recognized, apply a documented family-specific interpretation; otherwise retain uncertainty or reject the event's time as invalid.
* Validate timestamp range and finite numeric values. If milliseconds are supported defensively, recognize them by a documented magnitude/range rule and test the units; the supplied numeric A examples are seconds.
* Do not cap every large positive receipt delay and replace the observation time with the receipt time. That destroys the very buffering signal needed to identify coverage and outages.
* If correcting device clock offsets, derive them from information already available by `at` and robust repeated observations. The initial implementation can avoid speculative corrections and use conservative uncertainty when the evidence is insufficient.

### E3. Two-layer idempotence

Deduplicate both repeated IDs and identical physical observations carrying different IDs.

A semantic fingerprint should include serial, source/normalized message type, original or canonical observation time, and canonicalized payload/raw-frame fields. It must exclude `event_id` and `received_at`. Sort JSON keys and normalize representational equivalents deliberately. Never use Python's randomized `hash()` as a persistent identity.

For every logical message, retain original event-ID aliases and their receipt times. The logical message contributes once to freshness, evidence facts, incident counts, and failed-command counts. Its first valid receipt is the earliest known receipt; a retry at 10:09 of a 10:00 reading does not make it a new 10:09 observation. Evidence at 10:05 cannot contain an alias first received at 10:09.

Choose an evidence representative deterministically, such as the earliest available receipt with a stable event-ID tie-break. Keep key fault event IDs available even when extra aliases exist. Do not deduplicate solely on a coarse time bucket, serial alone, coordinates alone, or payload without observation time.

If the same event ID carries conflicting substantive content, quarantine/log that conflict and preserve the original valid record. Never silently overwrite. Clearly distinguish this defensive policy from the measured pack, where conflicting duplicate IDs were not found by the audit.

An identical batch replay must leave every domain answer unchanged. A late ingested event with an earlier `received_at` can legitimately alter a retrospective answer once it becomes part of “ingested so far”; tests must distinguish that from a duplicate retry.

### E4. Accepted count and malformed input

The contract requires an integer but does not define whether duplicates count as newly inserted. Choose and document a policy: `accepted` counts valid envelopes accepted for processing, including duplicates and safely ignored unknown types; malformed individual events are excluded. Maintain internal counters for inserted, duplicate, unknown, malformed, and conflicting records without adding unrequested response fields.

`events=[]` returns 200 with zero. Invalid JSON, a non-object envelope, missing `events`, non-list `events`, or more than 5,000 elements returns 400. A valid list containing bad elements must still process its valid neighbors. Catch known parsing/validation failures at the event boundary; do not swallow arbitrary programming exceptions and claim success.

Unknown event types must not update health freshness, ignition, plans, or fault state. A platform `command` or `plan_change` also does not mean the device itself checked in. Unknown serials observed in telemetry can be retained for diagnostics and VIN reconciliation, but device-status requests return 404 for serials not in the reference catalog unless the contract is explicitly extended and documented. Known stock serials are in the catalog and are not 404.

### E5. Reference facts and leakage prevention

Load all six required CSVs. Keep them separate from ingested observations.

* `support_cases.csv`: use aggregated historical relationships and offline evaluation. Do not answer “camera_fault” because a row names this serial's future resolved case. Do not resolve a current episode using a case closure that has not happened. It is simplest to keep individual case rows out of the runtime diagnosis path entirely.
* `plan_changes.csv`: load as reference/corroboration metadata. Since it copies telemetry and lacks receipt time, use ingested `plan_change` receipts as the operational authority. Do not insert CSV rows into telemetry at startup or cite their IDs as though ingested. This avoids both future pause/resume leakage and double counting. Document this choice.
* `devices.csv`: treat assignment/status as a roster hypothesis with installation dates, not a perfect historical timeline. Use observed VIN and serial transition evidence for historical identity.
* `schedule.csv`: future schedules are legitimate planning context. A schedule says an asset is needed, not that it is currently moving or communicating.
* `weather.csv`: select the relevant depot's local date for a missed reporting opportunity; do not use tomorrow's cold as the cause of today's silence.

## F. As-of device and asset projections

Build an immutable evaluation context once for each `at`/store revision. Include:

1. Eligible logical observations and permitted evidence aliases.
2. Latest trustworthy device-origin contact and latest fresh measurement, tracked separately.
3. Ignition timeline from explicit ignition events and `position.ignition` on the effective tracker.
4. Camera recording/sleep/boot/error timeline.
5. Unresolved power-disconnect episodes and explicit restorations.
6. Battery trend, last credible battery value, and any recovery observation.
7. Connectivity plan timeline.
8. Effective asset/device associations using VIN, static assignments, installation dates, and observed serial transitions.
9. Current and upcoming jobs; next 06:00 local shift; relevant local weather.
10. Compatible peer cohorts and ongoing correlated silence episodes.

Expose `last_heard_at` consistently. A defensible convention is the latest first receipt of a valid, unique device-origin message available by `at`, excluding commands, plans, unknown types, and retry-only freshness. Internally retain `freshest_measurement_at` to avoid treating old buffered data as live. Document this interpretation because the contract does not define the exact semantics of this one field.

If there is no device-origin evidence, use `last_heard_at: null`, a valid known asset or null association, state `unknown`, cause `unknown`, a low finite confidence, an explanation, and `evidence: []`. Do not invent an event ID to avoid an empty list.

## G. Diagnosis policy and competing causes

Use a set of candidate diagnoses with evidence strength, validity conditions, recovery conditions, and an operational action. Do not use an unconditional chain where the latest event or a broad outage always overrides a physical fault.

### G1. General precedence principles

1. Positive unresolved fault evidence outranks a benign inference based only on silence.
2. A confirmed account/assignment cause can explain silence without a site visit, but must not erase independent physical fault evidence.
3. A correlated carrier incident explains compatible due-reporting gaps; it does not absorb unrelated power failures or dormant devices.
4. Normal sleep/parking requires positive context and the appropriate timing rules.
5. Weather or lack of jobs alone is insufficient to prove intentional downtime or a healthy battery.
6. Recovery is cause-specific and must occur after the fault in observation time, with receipt available by `at`.
7. When evidence cannot distinguish causes, return `unknown` honestly and choose proportionate support follow-up if warranted.

When simultaneous causes exist but the contract allows only one `likely_cause`, choose the currently actionable, best-supported explanation and include the other constraint in reasons. Record the policy and test it. Confidence is a bounded evidence-strength score unless genuinely calibrated probabilistically; do not claim that 0.8 is a measured 80% probability.

### G2. T-series normal behavior

While ignition is on, expect positions approximately every two minutes. Use the calibrated driving-late threshold. At a red light, speed can be zero while ignition remains on; do not equate zero speed with parked ignition-off mode.

When ignition is off, expect a heartbeat every four hours and regard the device as late after four hours thirty minutes with no credible device contact. This 270-minute rule is given, not learned. Specify and test the exact boundary: “late after” means strictly beyond 270 minutes unless later authoritative instructions say otherwise.

A fresh heartbeat can establish device communication while the normal operational interpretation is `quiet_expected/parked_normal` for an ignition-off asset. Be consistent: use `reporting/none` for normal active reporting; choose the parked state when explaining expected inactivity between operational reports. Do not alert solely because no position has arrived during a healthy parked heartbeat period.

If ignition is unknown and no fault explains silence, use an uncertainty policy. The existence of a scheduled job should raise investigation priority, not manufacture an ignition-on event.

### G3. C-series normal behavior

Use the effective tracker's ignition on the same asset. A camera may record for up to 15 minutes after ignition off, then sleep normally. Before that boundary, use recent camera observations and a transition grace; do not prematurely declare a missing sleeping event a fault. After that boundary, a camera quiet in the context of ignition off is `quiet_expected/sleeping_by_design`, provided no stronger unresolved fault exists.

On the next credible ignition-on event, the previous sleep explanation expires. Allow a calibrated boot/wake grace, then require current recording evidence. `booting` is not the same as `recording`. A camera can be faulty while continuing to emit `storage_error`, so “recent contact” is insufficient to call it healthy.

A sleeping camera on a parked vehicle is not an actionable triage item. A camera with an unresolved storage error on a currently needed/driving vehicle is actionable even if it last slept earlier.

### G4. A-series normal behavior

Expect one check-in per day. A 24-hour threshold without jitter allowance is too strict for this pack. Use both elapsed time and the device's stable reporting phase where enough observations exist. A device at 23 hours without today's report has not necessarily missed a daily opportunity.

Treat periodic phase estimates as derived only from observations available by `at`; do not fit a per-device future calendar and then use it in past queries. New or sparse devices use family-level defaults.

Confirmed healthy battery plus a cold missed opportunity can justify temporary `quiet_expected/cold_weather`. Persistent silence beyond the bounded cold grace becomes unknown/actionable. Known low battery remains actionable even in cold weather.

### G5. Power loss

Open an episode from `power_disconnect`, corroborated by backup-battery `low_voltage` when present. Distinguish `source: backup_battery` from ordinary vehicle-voltage readings. Explain whether the tracker is still running on backup and whether expected reports have stopped.

Do not clear the episode on a position, heartbeat without sufficient power evidence, ignition change, or a newer received old observation. Clear on a later credible `power_restore`, or an explicitly documented equivalent supported by power observations. A tracker may be `needs_action/power_loss` while still emitting backup messages.

Owner: technician when hands-on reconnection/repair is required. Include the disconnection and/or backup low-voltage event as key evidence. Prefer high priority for an active or imminent operational job; lower priority for a confirmed unused asset without an immediate deadline.

### G6. Camera fault and remote-first escalation

Open a camera episode on a storage error, or on sustained absence of recording while credible asset ignition is on and plans/outages/normal transitions do not explain it. Track unique reboot commands in the **current** episode, issued after the failure. A command is evidence of an attempt, not proof of successful execution or recovery.

Default owner: support, next action a remote reboot/check. The observed resolved-case mix is 28/40 remote fixes, a useful policy prior with selected-case limitations. Do not send every 4.3.0 camera directly to a technician from three cases.

Escalate to technician after the configured number of unique failed attempts and response grace, provided the camera was expected to be awake. Count failure from lack of resumed recording or repeated errors; avoid counting a reboot during normal sleep as a failed test. Duplicate command receipts cannot create extra attempts.

A later `recording` observation resolves the fault. A later `booting`, `sleeping`, or another command does not by itself prove repaired recording. If the asset is parked after the error, retain the unresolved episode but adjust urgency and the timing of a meaningful remote test.

### G7. Paused or ended plans

Use the most recent effective ingested plan transition by observation time. Both `paused` and `ended` map to the permitted cause `plan_paused`; there is no `plan_ended` enum. A later `active` transition removes this explanation.

Owner: support for account investigation/reactivation steps. Mention customer approval in the next action when necessary, without creating a technician task. Do not pretend that recommending a plan change actually changes the account. A paused device cannot be treated as healthy merely because a platform command was received.

### G8. Device swaps and assignments

Use known asset VINs, VIN-bearing heartbeat/ignition events, and credible activity transitions. Preserve historical mappings. A replacement becoming active later must not retroactively remove the old tracker from earlier peer cohorts.

Do not bind an unknown serial to an asset from geographic proximity alone. Require matching VIN or a strong explicit assignment source. When multiple serials claim the same VIN concurrently, retain the conflict and seek support reconciliation; do not arbitrarily select the alphabetically first.

For a stale registry mapping, use `device_swapped`, owner support, next action reconcile the serial/asset record using cited VIN and transition evidence. If the roster already marks the old serial removed and correctly assigns the observed replacement, the old unit's expected inactivity should not create a perpetual duplicate ticket. Distinguish a documented completed removal from an unresolved record mismatch, and document this ambiguity rather than hardcoding six known replacements.

### G9. Battery low

For A-series, case notes support investigating battery below 10%, with threshold validation against actual check-in trends. A low-battery fault can be actionable before complete silence. Use a clear recovery threshold/hysteresis or explicit replacement evidence so noise near a cutoff does not flap the diagnosis.

For BX, use the decoded low-battery flag and separate percentage policy; the portal labels a 14% device low, so blindly reusing A's below-10% rule would miss it. Retain decline trend and available reporting time as context. Do not claim a precise remaining lifetime from a few samples.

Owner: technician for physical battery or tracker replacement. Priority reflects actual usage and deadlines, not merely “battery tag” versus “vehicle.” Clear only from a later credible recovery measurement, not a late old high battery sample.

### G10. Cold weather and planned downtime

Use the relevant local overnight low, adequate recent battery evidence, and a bounded missed-report allowance. The supplied cold cases are consistent with -10 C or colder; this is evidence for a candidate cutoff, not a universal physical law.

The 12 landscaping trailers cease reporting after October 23 despite active inventory status. The data alone does not prove a customer-approved seasonal shutdown. Ask the ops lead for the policy and effective dates. Add confirmed rules to config with source attribution and effective intervals. Without confirmation, explain a suspected seasonal pattern as uncertain; do not silently suppress every landscaping device forever.

No jobs in a schedule is not by itself proof that an asset was intentionally powered off. The brief says battery tags normally report daily regardless of jobs. A strong explicit power/battery fault must remain visible even when there is seasonal context, unless an authoritative policy says the device was intentionally disconnected and no action is required.

### G11. Coverage gaps and backfill

Detect nontrivial delivery delays from observation versus receipt time and look for repeated isolated interruptions, weak signal evidence, and geospatial recurrence derived from the history. Use aggregated learned patterns, not an allowlist of device IDs or dates.

After backfill arrives, distinguish restored communication with old measurements from genuinely current reporting. Do not resurrect an already resolved old outage because delayed messages describe its past. While a gap is ongoing, do not claim certainty from the future fact that it later recovered. Use prior known coverage patterns and current evidence; otherwise say unknown.

Transient, supported coverage gaps generally warrant bounded follow-up, not a technician. If the current job is at risk, a support item can ask to verify connectivity or contact the customer. A gap beyond the calibrated tolerance must not be suppressed indefinitely.

## H. Carrier incident detection

Implement this as a shared diagnosis, not 35 independent alarms. It must work for both depots and carriers without knowing practice IDs.

### H1. Eligible peers

Start with comparable devices that were expected to report: principally ignition-on T trackers and awake cameras. Do not put all daily battery tags or parked trackers in a two-minute cohort. Group by depot, carrier, and compatible reporting family/mode. Exclude devices with better direct causes such as power loss, a paused plan, a proven swap, or normal sleep.

An eligible peer set must not disappear just because an outage has lasted longer than a recent-event lookback. Represent due-reporting gap episodes from the last credible reporting context, with explicit recovery and cancellation conditions.

### H2. Correlation evidence

Evaluate a configurable minimum number of independent devices, affected share of the eligible cohort, spread of silence onset times, and comparison to live peers on the other carrier. Count unique devices, not messages or retries. Geographically dispersed last locations strengthen a carrier explanation over one garage dead zone.

Initial candidate values are in section J, but optimize them against ordinary non-outage windows as well as both labelled outage periods. A high raw count alone is insufficient when every asset is ending its shift. Compare candidates against their actual expected mode.

If both carriers fail together and there is no carrier-specific contrast, do not assert a particular carrier fault. Use a lower-confidence shared unknown/support incident if justified. If only one model/firmware is affected across carriers, treat that as a different hypothesis.

### H3. Grouping and recovery

Produce one `kind: incident` support item for a compatible carrier/depot episode, containing its actionable affected serials and associated assets. Keep unrelated physical failures out. Each serial appears at most once across the complete triage response.

On recovery, remove fresh recovered members and close the group when the remaining compatible evidence no longer warrants it. Use a documented partial-recovery policy, not a fixed permanent member list. A second outage later must create a separate episode, while the same snapshot must have deterministic membership and `item_id`.

Evidence should include the last pre-gap observations from affected peers and useful unaffected-peer reports. The absence itself has no event ID; explain the evaluated deadlines in reasons. Never invent an “outage-start” ID.

Owner: carrier. Next action: escalate one incident to the carrier, communicate one service-impact update to the customer, and monitor recovery. The service returns that recommendation; it does not send a message. Priority should be high for broad current operational impact. The customer should receive a consolidated explanation, not hundreds of individual alarms.

## I. Support triage policy

### I1. Ownership and action table

| Diagnosis/context | Usually included now? | Owner | Next action |
|---|---|---|---|
| Normal active reporting | No | none | None |
| Parked within heartbeat tolerance | No | none | None |
| Camera sleeping after ignition off | No | none | None |
| Confirmed planned downtime | No, unless an actual follow-up is due | none/customer | Resume/confirm only when policy requires |
| Supported transient cold miss | Usually no | none | Monitor within bounded allowance |
| Confirmed carrier outage | One group | carrier | Escalate/monitor and give consolidated impact update |
| Unresolved power loss | Yes | technician | Reconnect/inspect power and wiring |
| New camera fault | Yes | support | Remote reboot and verify recording |
| Camera fault after meaningful failed attempts | Yes | technician | Inspect/replace storage/device |
| Plan paused/ended while service is needed | Yes | support | Account/approval investigation |
| Unresolved asset/serial mismatch | Yes | support | Reconcile inventory from VIN/transition evidence |
| Confirmed depleted battery | Yes | technician | Replace battery or tracker |
| Uncertain prolonged silence with a job deadline | Yes, proportionately | support | Verify status before dispatch |
| Isolated, expected short coverage gap | No or bounded follow-up | support if follow-up due | Check recovery; no automatic visit |

This table is a default policy. Record ops-lead instructions where they refine owner or priority. Do not emit `who_acts: none` for an item unless there is a clear immediate follow-up that explains why the item is actionable; generally suppress such items.

### I2. Priority policy

Ask the ops lead how Larchmont defines urgency. Pending a response, use one transparent policy across causes:

* **High:** verified failure affects a currently scheduled job, a broad active incident, or a job/shift deadline within the configured urgent horizon with insufficient recovery time.
* **Medium:** credible fault requires action before a later known need, or repeated unexplained silence warrants support investigation without an immediate job at risk.
* **Low:** nonurgent account/record follow-up or a low-risk uncertainty requiring action now but no immediate operational deadline.

Calculate current jobs with half-open intervals `[start,end)`. At the exact end of one job it no longer counts as active. Calculate the next 06:00 local shift using `America/Toronto` for MSS and `America/Regina` for REG. Only technician visits are explicitly restricted to weekdays in the brief; do not silently make every shift or job weekday-only.

The urgent horizon, any next-shift preparation buffer, and all business cutoffs belong in config. Do not equate long silence with high priority when an asset is deliberately unused. Do not mark a serious active fault low merely because its last contact was recent.

### I3. Deterministic response construction

1. Obtain one immutable as-of context.
2. Diagnose devices with the same rules used by `/status`.
3. Build compatible shared incidents and claim their serials.
4. Add remaining actionable device items.
5. Check the ownership partition: no serial in two items; device items have exactly one serial; incidents have multiple compatible serials.
6. Deduplicate assets, serials, reasons, and evidence while preserving deterministic order.
7. Sort by high/medium/low, then operational deadline, cause/asset/serial stable tie-breaks.
8. Generate stable IDs from the incident scope/episode or logical fault identity, not random UUIDs or the current wall clock.

A good reason names the observation, time, missing expectation, and operational consequence. A good next action names one owner and a concrete step. Avoid generic strings such as “investigate issue.” Include the critical fault event, supporting same-asset context, and relevant peer evidence without dumping the entire telemetry history.

Example reasoning style: “The tracker reported external power disconnected at 18:10 UTC and backup battery low at 18:20. No later restoration is available at this checkpoint. Its next job starts tomorrow at 07:55 Regina time; arrange a wiring check before use.” The action must be based on actual events and jobs in the response context, not this example's literals.

## J. Threshold register and calibration procedure

### J1. Separate kinds of parameters

Store given rules, inferred wire-format constants, calibrated behavior thresholds, and defensive limits in distinct sections of config. Every entry needs units, provenance, rationale, boundary comparator, evaluation script/test, and any uncertainty. No threshold may silently differ between status and triage.

The following are **starting hypotheses for implementation**, not already validated final choices:

| Parameter | Initial candidate | Basis and final validation |
|---|---:|---|
| T ignition-on interval | 120 s, given | Brief; observed p99 within ongoing drives 123 s |
| T parked heartbeat | 14,400 s, given | Brief; do not relearn it from mixed-mode intervals |
| T parked late | 16,200 s, given | Brief says late after 4 h 30 min |
| Camera sleep delay | 900 s, given | Brief |
| T driving overdue | 360 s | Approximately three missed positions; compare 240/360/480/600 s |
| Normal receipt-lag allowance | 10 s | Most normal receipt lags <=8 s; validate separate family cohorts |
| Camera recording overdue | 720 s | Beyond two 300 s opportunities plus margin; compare 600/720/900 s |
| Camera wake grace | 120 s | Measure actual ignition-to-boot/recording intervals before fixing |
| Camera failed reboots before visit | 2 | Case notes support two failures for physical repairs; verify current episodes |
| Reboot response grace | 600 s | Candidate operational allowance; fit meaningful awake recovery intervals |
| A check-in overdue | 93,600 s (26 h) | Healthy observed max 24 h 40 min in restricted cohort |
| BX check-in overdue | 93,600 s (26 h) | Observed interval max 24 h 59 min; validate all decoded units |
| A low battery | <10% candidate | Case notes; inspect actual last readings before labeled failures |
| A recovery battery | >=20% candidate | Hysteresis assumption; compare replacement recoveries |
| BX low battery | Wire flag `0x02`; percentage fallback <=15% candidate | 14% portal example is low; fallback is a policy, not proved by three rows |
| Cold temperature | <=-10 C candidate | Labeled no-fault cold cases begin at -10 C |
| Cold silence allowance | Up to 52 h candidate | Bounded extra daily opportunity; validate recovery/false suppression |
| Outage minimum devices | 5 candidate | Fit both outages and many ordinary windows, not only P1 |
| Outage affected eligible share | 0.50 candidate | Family/mode-specific denominator required |
| Outage onset spread | <=600 s candidate | Quantify normal versus outage gap starts |
| Urgent operational horizon | 2 h candidate | Business assumption awaiting ops clarification |
| Response confidence levels | Named evidence-strength levels | Do not advertise as probabilities without calibration |

Do not leave these values untested and call them “calibrated.” If data cannot identify a value, label it an operational or defensive assumption and test sensitivity. All comparisons, including `<` versus `<=`, must be documented.

### J2. Reproducible analysis

1. Inventory schemas, counts, nulls, foreign-key references, dates, statuses, and file hashes.
2. Parse event envelopes; report malformed fields, raw types, unknown types, and timestamp formats.
3. Quantify exact-ID and semantic retries, including their receipt delays.
4. Reconstruct unique observation timelines. Separate ignition-on positions from overnight and ignition-off gaps.
5. Calculate normal receipt-delay distributions and buffered tails by family/firmware/depot/carrier.
6. Measure camera boot/recording/sleep transitions using same-asset ignition; measure successful and failed reboot episodes without using closure times as telemetry.
7. Measure daily A/BX cadence, jitter, battery trends, cold-day missed opportunities, and recovery.
8. Build gap episodes and evaluate cohort outage detection against both labeled outages and many quiet ordinary windows.
9. Examine identity transitions using VIN and commissioning time; report ambiguous mappings.
10. Inspect seasonal stops and schedule patterns as evidence for ops questions, not as an automatic shutdown policy.
11. Relate labeled support cases to episode windows. Exclude invalid case durations. Report class counts and sample sizes, especially tiny cohorts.
12. Sweep the meaningful candidate thresholds and publish effect on false benign alerts, missed explicit faults, and incident fragmentation.

Use an early-history development slice and a later-history validation slice; one practical split is October 4-24 for fitting and October 25-31 for validation. After selecting a defensible policy, report final aggregate findings from the full provided history. Do not repeatedly optimize directly against the three practice IDs.

Selected support-case labels do not provide a clean fleet-wide false-positive rate: unreported normal periods are not labeled cases. Separate case-aligned diagnostic accuracy from ordinary-period alert volume and invariant tests. Avoid reporting “100% accurate” from passing the practice tool.

Keep derived calibration output deterministic, with source hashes and a documented regeneration command. Runtime startup reads small committed config, never the corpus or a notebook.

## K. BX reverse engineering and integration

### K1. Mapping supported by the supplied anchors

| Raw key | Interpretation | Decode |
|---|---|---|
| `u` | Inventory serial | Preserve exactly, e.g. `BX40471` without inserting a hyphen |
| `t` | UTC Unix time represented in hexadecimal | `int(value,16)` -> UTC datetime |
| `b` | Battery value consistent with a 12-bit full-scale percentage | `100 * b / 4095`; round only for portal-display comparison |
| `s & 0x01` | Moving flag | Nonzero -> moving |
| `s & 0x02` | Low-battery flag | Nonzero -> low battery |
| `s & 0x08` | GPS fix | Nonzero -> valid fix |
| `p` | Signed latitude,longitude in 1e-5 degrees | Split two integers; divide each by 100,000 |

This is an inferred mapping that exactly matches all three provided readouts. The battery denominator is consistent with a 12-bit full scale; three rounded anchors alone cannot uniquely prove the vendor's entire battery transfer function. Do not describe `b` as millivolts. The high/low values and portal percentages support the chosen simple model.

An unknown `0x04` flag appears in six of the 300 separate messages. Preserve it as unknown bits; do not invent a meaning or mistakenly call it low battery. The stream additionally includes combinations such as `s=11`, so decode independent bits rather than a table of a few observed integers.

### K2. Exact anchor checks

| Serial | Raw timestamp | Raw battery/flags | Expected UTC and decoded values |
|---|---|---|---|
| BX40471 | `6ADA16E0` | `b=3094, s=8` | 2026-10-22 14:00 UTC = 08:00 Regina; 76%; not moving; not low; GPS; 50.42719,-104.56695 |
| BX41085 | `6AD8D76C` | `b=2583, s=9` | 2026-10-21 15:17 UTC = 09:17 Regina; 63%; moving; not low; GPS; 50.43083,-104.66817 |
| BX47068 | `6AE4B4B0` | `b=573, s=10` | 2026-10-30 15:16 UTC = 09:16 Regina; 14%; not moving; low; GPS; 50.46073,-104.67404 |

The portal time is Regina local time, UTC-6 year-round, not UTC and not daylight time. Keep full battery precision internally. Use a documented display-rounding rule; truncating 75.56% to 75 would fail the first anchor.

### K3. Ingestion integration

The envelope has `event_id`, `received_at`, `type: bx_raw`, and `raw`; there is no outer serial, device time, or payload. Parse the envelope without demanding those missing fields, decode the JSON string in `raw`, resolve `u` against inventory, and emit the internal A-like battery/position observation with its original envelope evidence ID.

Wire decoded reports into normal freshness, battery diagnosis, cross-device/asset context, and support triage. Never preload `bx_raw_messages.txt` as telemetry, and never use `portal_readout.csv` as an answer table. A decoder-only unit test is insufficient for the 10-point hardware requirement.

Validate JSON shape, required fields, hex time, integer flags, battery bounds, coordinate count/ranges, serial existence, and GPS validity. Non-finite numbers and bool-as-int surprises must be rejected. If `gps_fix` is false, do not present the raw coordinates as a newly valid fix. A timely no-fix message still proves communication; persistent location loss can warrant a separately justified unknown diagnosis, since `gps_fault` is not an allowed cause.

## L. Testing strategy

The full test inventory is in `03_ACCEPTANCE_TEST_MATRIX.md`. The central layers are:

1. **Contract tests:** all fields/enums, errors, malformed mixed batches, supported endpoints, UTC encoding.
2. **Temporal tests:** cutoff boundaries, out-of-order arrivals, future receipts, old backfill, no wall-clock dependency.
3. **Idempotence tests:** same batch twice, same reading/new ID, duplicate reboot commands, stable evidence representatives.
4. **Rule/episode tests:** normal transitions, positive faults, cause-specific recovery, competing causes.
5. **Incident tests:** grouping, peers, negative controls, partial recovery, no duplicate serial ownership.
6. **Hardware tests:** exact anchors, unknown bits, malformed frames, full end-to-end status and triage.
7. **Metamorphic tests:** rename serials, shift dates while preserving local context, swap carrier/depot cohorts, change batching, vary ingestion order with an equivalent final eligible set.
8. **Official integration:** preflight and practice from different fresh processes, unmodified runner and fixtures.
9. **Operational release:** fresh install, external reference directory, no telemetry files needed at startup, outbound networking blocked, full replay latency and memory.

Use synthetic event IDs in independent fixtures, not only copied practice IDs. Construct expected outcomes from stated rules and source reasoning rather than from the same helper functions used by production code.

Audit evidence automatically: every returned event ID must correspond to an eligible original receipt at or before `at`; each key causal observation must be present; no synthetic case ID or internal message hash masquerades as an event ID.

For performance, measure maximum and percentile batch durations across the full replay, query latency at each checkpoint, startup time, peak resident memory, and total run time. The hard ingestion requirement is under 10 seconds for 5,000 events. Set an internal margin, such as under 2 seconds on the tested development machine, but report the machine and observed numbers rather than promising identical grading hardware performance.

## M. Presentation and offline operation

Mandatory presentation work: a concise README with install/start first, a persona description, a clear architecture explanation, readable JSON examples from actual results, a threshold register, documented assumptions, evidence-linked reasons, an AI usage log, and a clean repository.

Optional dashboard, only after correctness gates pass: one local static HTML/CSS/JS page served by the Python app. Include an as-of time input, triage list, owner/priority filters, device lookup, evidence drawer, and visible “no events ingested” state. Use the same API responses; do not reimplement diagnosis in JavaScript. Default to an explicit replay checkpoint or latest eligible ingestion time, not today's wall clock.

All assets must be local. No fonts, icons, scripts, analytics, images, documentation assets, maps, or AI calls from a CDN. No React/Node build is necessary. Verify browser network behavior and the API in an offline environment. The page is for demonstration; it does not gain hidden-exam points.

## N. Ops-lead questions

The brief allows at most two written questions, one per Form 2 submission. First check whether you already used either allowance. Do not ask a third, and do not fabricate a reply. Suggested questions for the support plan:

1. **“Which assets or asset uses are intentionally taken offline for the autumn-to-winter changeover, and what are the effective local dates for that downtime and return to service?”** This resolves the unlabeled landscaping stop pattern and establishes an actual customer policy.
2. **“When a device issue is found, what exact operational deadline makes it high priority rather than medium or low, including issues discovered before the 06:00 shift?”** This supplies business semantics that telemetry cannot establish.

Use actual answers to update config and the decision log. If no answer arrives, state the provisional policy and its effect honestly. Do not spend these questions asking for a hidden threshold that can be estimated from the supplied telemetry. The provided Form 2 link is in the original pack README; this plan does not submit it for you.

## O. Release gates and honest completion

A release is ready only when:

* Source references and requirement traceability are complete.
* The required support endpoints conform with no placeholder success paths.
* All focused contract/temporal/idempotence/causal/hardware tests pass.
* Preflight and practice pass from separate clean processes, with warnings reviewed.
* The service starts with only the six CSVs in an alternate `QF_DATA_DIR` and an empty telemetry store.
* Full history can be ingested under the per-batch limit and queried within reasonable latency.
* Outbound networking is demonstrably unnecessary at runtime, including the optional UI.
* Every chosen threshold has provenance; assumptions are labeled.
* BX anchors and unseen valid frames work through real endpoints.
* End-of-history top actions are obtained from the final service at the exact requested time.
* The AI log, Form 1 changes, product note, and setup instructions are truthful and complete.
* The candidate can explain the code and make a small live change.

Do not call an unexecuted check passed. Do not call a polished dashboard a complete solution while the temporal engine is wrong. Do not invent final top-three actions in this plan; they must come from the implemented and replayed service.

## P. Primary implementation references

These references support implementation details only. Fleet-specific rules come from the supplied brief and pack.

* Python 3.12 IANA timezone support: https://docs.python.org/3.12/library/zoneinfo.html
* Python 3.12 SQLite interface and connection/transaction behavior: https://docs.python.org/3.12/library/sqlite3.html
* FastAPI custom validation-error handlers, including returning HTTP 400: https://fastapi.tiangolo.com/tutorial/handling-errors/
* Official Codex IDE documentation: https://learn.chatgpt.com/docs/codex/ide
* Official Codex project guidance with AGENTS.md: https://learn.chatgpt.com/docs/agent-configuration/agents-md

Use `America/Toronto` and `America/Regina`, with packaged/system timezone data. Do not hardcode October offsets and forget that Mississauga changes from UTC-4 to UTC-5 on November 1, 2026, while Regina stays UTC-6. The hidden window includes that transition.
