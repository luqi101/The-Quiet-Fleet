# Quiet Fleet requirement traceability

This matrix preserves R01–R37 from the planning kit and adds explicit source requirements. The phase records cover independent behavioral verification and the official replay on macOS. Ubuntu offline execution remains a release gate.

The candidate brief in `inputs/candidate-brief.pdf` and the API contract govern requirements. The exam runner and practice scenario define the supplied executable checks. The planning kit supplies the lettered acceptance IDs and additional adversarial cases. [API contract](../vendor/quiet-fleet/docs/CONTRACT.md), [practice expectations](../vendor/quiet-fleet/exam/PRACTICE.md), [acceptance matrix](../planning/03_ACCEPTANCE_TEST_MATRIX.md)

Support, prioritizing fewer false alarms, and one grouped customer alert for a major outage are confirmed by the supplied Form 1 record. [Form 1 record](../planning/form1.md) · [Decisions](decisions.md)

## Startup, HTTP, and immutable inputs

| ID | Requirement | Future module or artifact | Meaningful verification |
| --- | --- | --- | --- |
| R01 | Target Ubuntu 24.04 with Python 3.12 | `requirements.txt`, release checks | H09. In a clean Ubuntu environment, install the pinned dependencies and run documented startup under Python 3.12. |
| R02 | One start command on localhost port 8080, offline after install | `quiet_fleet/__main__.py`, README | A01, A06, H10. Start by the documented command with outbound networking unavailable and issue real loopback HTTP requests. |
| R03 | Load the six named reference CSVs from `QF_DATA_DIR`, default `./data` | `reference.py` | A02, A05. Start with only the six files in an alternate directory, confirm a query uses that roster, then verify a missing required file prevents readiness. |
| R04 | Start each normal process with empty telemetry | `store.py`, startup lifecycle | A04. Ingest, restart, then verify the known device has no prior contact or evidence. |
| R05 | Telemetry enters through `/ingest` only | Startup dependency boundary | A03. Start with no corpus and with a deliberately unreadable or invalid telemetry directory. Check readiness and empty state both times. |
| R06 | `GET /health` returns `200 {"status":"ok"}` when ready | `api.py`, startup lifecycle | A01, A05. Verify exact JSON after successful initialization and failure to become ready with invalid critical inputs. |
| R07 | `POST /ingest` accepts batches of up to 5,000 events within 10 seconds and returns integer `accepted` | `api.py`, `store.py` | A11, A12, A16, H07. Measure each batch on full replay, exercise an empty envelope and the 5,001 limit, and verify concurrent queries see coherent batches. |
| R08 | Isolate individual malformed events | `normalize.py`, `api.py` | A13. Place malformed rows between valid observations, assert HTTP 200 and the documented count, and verify each valid neighbor affects status. |
| R09 | Accept and ignore unfamiliar event types | `normalize.py` | A14. Include a valid unknown envelope and verify it is counted per policy without changing status, freshness, or evidence. |
| R27 | Emit complete contract JSON with UTC timestamps, valid enum values, finite confidence in [0, 1], and the selected persona's required fields | `models.py`, `api.py` | A07, C15, E13. Run an independent strict schema assertion on populated and empty responses, including `reporting/none`. |
| R28 | Return JSON 400 for invalid or missing parameters and malformed batch envelopes, 404 for unknown serials and unsupported personas | `api.py` | A08–A11, A15. Exercise malformed JSON, invalid query times, unknown serial, known stock serial, and persona discovery. |
| R38 | Keep vendor files byte-identical, six reference CSVs available at startup, and the original corpus local | `vendor/quiet-fleet/`, `data/`, `.gitignore` | H01, H16. Recheck the source hash manifest and six staged CSVs. Verify originals, telemetry and generated bulk outputs stay outside Git. |

## Temporal model, identity, and evidence

| ID | Requirement | Future module or artifact | Meaningful verification |
| --- | --- | --- | --- |
| R10 | Deduplicate exact event IDs and semantic retries with new IDs | `normalize.py`, `store.py` | B01–B05. Retry a batch, reorder keys, change retry IDs and receipt times, and verify unchanged domain facts. Separate actual readings at different observation times and preserve the first valid record on conflicted ID. |
| R11 | Reconstruct facts independent of ingestion order | `store.py`, `projection.py` | B08–B12, B21. Vary arrival ordering and batch boundaries over equivalent accepted facts. Verify backfill can add retrospective knowledge without replacing newer observations. |
| R12 | At query time, apply the inclusive platform receipt cutoff and the ingested-so-far constraint | `store.py`, `projection.py`, persona evaluator | B06–B08, B20. Add a receipt exactly at `at` and one just after. Compare prior status, association, incident and action results under repeated queries. |
| R13 | Normalize and preserve device observation time independently of receipt | `time_utils.py`, `normalize.py`, `projection.py` | B09–B17. Test buffered observations, legacy numeric Unix seconds, malformed and future times, and platform-only events. Backfill may show a receipt while the old reading remains stale. |
| R21 | Reconstruct historical asset assignments with VIN, roster and dated transition evidence | `projection.py` | D15–D19. Preserve a removed unit before the observed swap, recognize a matching VIN from stock, and retain ambiguity when two serials remain credible. |
| R26 | Return original evidence event IDs available by `at` and meaningful reasons | `projection.py`, diagnosis and persona response builders | B07, B18, B19, E21, H05–H06. Resolve every output ID to an eligible receipt, include the key fault evidence, and return an explained empty evidence list when no event exists. |
| R39 | Supply every required status field, including asset association and `last_heard_at` | `projection.py`, `models.py` | A07, A08, B02, B13, B17, B19. Verify no-contact nulls for known devices and that commands, plan changes, and later retry receipts cannot advance the latest first receipt of a distinct device observation. |
| R40 | Read reference context without introducing future outcome information into runtime decisions | `reference.py`, `projection.py` | B22, C06, D25, D32. Make case and CSV plan rows match a hidden future fault, then verify the current result derives only from eligible facts. Test legitimate future schedule context with local-date weather. |

## Diagnosis and calibration

| ID | Requirement | Future module or artifact | Meaningful verification |
| --- | --- | --- | --- |
| R14 | Respect the given tracker parked heartbeat of four hours and lateness after four hours 30 minutes | `config/rules.json`, `diagnosis.py` | C03, C04. Exercise 269:59, 270:00, and 270:01 at stable ignition-off and verify behavior around the boundary. |
| R15 | Use the given two-minute driving position cadence and a separately calibrated overdue threshold | `config/rules.json`, `diagnosis.py` | C01, C02, C05. Compare ordinary cadence, zero speed with ignition on, and overdue driving reports. |
| R16 | Camera sleeps 15 minutes after ignition off and wakes with ignition | `projection.py`, `diagnosis.py` | C07–C10, H05. Verify before and after the 15-minute transition and a new ignition-on before a recording resumes. |
| R17 | A-series normally reports daily with calibrated jitter/grace | `calibrate.py`, `diagnosis.py` | C11–C14. Check one and multiple missed opportunities, ordinary jitter, and sparse newly installed devices using only earlier observations. |
| R18 | Keep power loss active through backup transmissions and close on credible restoration | `diagnosis.py` | B12, D01–D04, H06. Ingest disconnect, backup low voltage and positions, then a real restore, and compare subsequent status. |
| R19 | Track camera fault, remote-first intervention, and true recording recovery | `diagnosis.py`, persona actions | B10, D05–D12, H05. Verify old recording, booting, sleep, and duplicate reboots leave the episode unresolved. Escalate under tested policy after distinct failed awake attempts and clear on later recording. |
| R20 | Apply ingested pause/end and resume transitions as of query | `projection.py`, `diagnosis.py` | D13, D14, B22. Compare paused, ended, and resumed states, including a later-delivered transition, with account ownership and separate device freshness. |
| R22 | Keep battery, cold, downtime, and coverage explanations evidence-based and bounded | `diagnosis.py`, `config/rules.json` | D20–D31. Exercise low-battery hysteresis/recovery, a cold healthy miss versus a proven depleted battery, independently confirmed seasonal policy, and backfill without future knowledge. |
| R23 | Correlate due-reporting losses by carrier and depot with meaningful controls and recovery | `reporting_peers.py`, `incidents.py` | E01–E11, H04. Use renamed cohorts, healthy other-carrier peers, ordinary shift changes, individual failures, retry bursts, and partial and complete recovery. |
| R29 | Config holds chosen thresholds and provisional business cutoffs with units, comparators, and provenance | `config/rules.json`, calibration register | F07, H14. Validate config on startup and inspect every chosen rule and boundary against its documented origin and synthetic case. |
| R30 | Reproduce calibration from history and document limitations | `scripts/audit_data.py`, `scripts/calibrate.py`, `docs/calibration.md` | D32, H14. Check source hashes and cohort sizes, reproduce candidate sweeps on chronological development and validation slices, and report alert volume independently of selected case labels. |
| R31 | Integrate optional BX decoding through ingest, status and selected persona | `bx.py`, `normalize.py`, `projection.py`, `diagnosis.py` | G01–G14. Verify three original portal anchors and a new valid frame, malformed isolation, flags/no fix, receipt cutoff, duplicate safety and actual battery actions/recovery. Record BX integration and inference limits in Form 3. |
| R41 | Apply real depot-local dates, daily 06:00 shifts, and the November DST change | `time_utils.py`, `operations.py`, persona evaluator | F01–F06. Verify Mississauga's repeated hour, year-round Regina offset, a UTC/local date split, exact 06:00 and weekend jobs. |

## Persona-specific decision surfaces

Only the selected persona's rows become grading gates. Shared API and diagnosis rows apply in every case.

| ID | Requirement | Future module or artifact | Meaningful verification |
| --- | --- | --- | --- |
| R24 | Support `GET /triage?at=` returns only actionable or follow-up items, with each serial in at most one item | `triage.py` | E12–E14, E19–E22, H04. Validate single-device versus incident shape, stable output, shared status consistency and no duplicate serial ownership or side effects. |
| R25 | Support supplies who acts, next action, reasons, evidence and priority based on actual operating needs | `triage.py`, `operations.py` | E15–E22, H04–H06. Check owner/action and active versus ended jobs, then verify sleeping camera exclusion, remote-first camera, carrier group, and physical power dispatch. |
| R42 | If fleet manager is selected, `GET /job-cover?depot=&at=&hours=` covers impaired jobs starting in the half-open window | Fleet job-cover evaluator | Validate MSS/REG and integer hours 1–72. Assert `no_location`, `no_video`, or `both` and `swap`, `keep`, or `gap` with required fields, same type/depot and visible/recordable free replacements for the full slot, and no overlapping bookings. Exercise P1 keep or omit, P2 video loss and P3 valid swap. |
| R43 | If field-tech scheduler is selected, `GET /visits?at=&days=` books only technician work and explains deferred work | Field-tech visit evaluator | Verify integer days 1–3 and the depot-local window, strictly after `at`, weekdays 07:00–15:00, at most six per depot/day and no new visits for remote-first, carrier, or sleeping cases. Assert required visit/kit/evidence fields, deferred asset/reason/why fields, and P3 power visit. |
| R44 | Describe the chosen persona, decision timing, cost of mistakes and deliberate false-alarm/miss trade-off | README, selected persona evaluator, `docs/decisions.md` | H14. Compare the profile and policy to verified Form 1 if available and use synthetic false-alarm and missed-fault cases to show the choice and its safeguards in behavior. |

## Verification, submission evidence, and live call

| ID | Requirement | Future module or artifact | Meaningful verification |
| --- | --- | --- | --- |
| R32 | Run the unmodified preflight and practice against separate fresh processes | `scripts/release_check.py` | H01–H09. Capture the official results and review warnings. Independently enforce strict errors, replay idempotence, per-batch latency, checkpoint query latency, and memory. |
| R33 | Keep a truthful AI record and meaningful local commits | `docs/ai-usage.md`, planning status, Git history | H14–H16. Check actual authorship, corrections or independent validations, original form text where available, and no fabricated results or times. |
| R34 | Capture the persona's actual top actions at `2026-10-31T23:59:00Z` | `scripts/capture_end_state.py`, Form 3 worksheet | H13. Compare the draft to the saved real endpoint response at the exact cutoff. Record an actual shortage of items if applicable. |
| R35 | Form 3 product note stays at or below 300 words | Form 3 worksheet | H14. Count words and review the proposed first version, user, value to customers, and 60-day measure. |
| R36 | Keep development commits local until the submission stage | Git workflow and release checklist | H15, H16. Inspect the exact remote, tested commit, and allowlisted contents. Require separate user direction for publication and form submission. |
| R37 | Candidate can demo a fresh checkpoint and make a small live code change | Live-call notes and focused tests | Rehearse one configurable behavior change, its focused test, and the brief's demo and discussion timings. |
| R45 | Form 3 records the repository and AI log, actual tests, thresholds, trade-off, BX disposition, top actions, Form 1 changes and AI verification | Form 3 worksheet and supporting docs | H13–H15. Verify every answer against actual source, replay outputs, user-confirmed intent, and recorded checks. Review release source identity and the setup-only post-submission exception. |
| R46 | Use only provided data and general public knowledge, and track the ops allowance accurately | Calibration provenance, decisions, ops notes | Review provenance, verify no runtime external API or AI calls, and compare any attributed ops fact and question count with actual records. |

## P01 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R10, R13, R21 | The full audit reproduced the identity and clock counts. The focused offline cases exercised retry aliases, ID conflicts, timezone/epoch equivalence and delayed recovery. The audit lists observed VIN transitions and a transmitting stock unit. | Runtime ingestion, historical assignments and HTTP noninterference tests. |
| R29, R30 | The threshold register and aggregate report cover separate development and validation slices, candidate sweeps, provenance, limits and source hashes. Both sensor timing and case-aligned analyses ran on the complete pack. | Startup validation and future behavior tests at the registered boundaries. |
| R23, R31 | The offline driving seed matched both labeled carrier openings. All three BX portal examples were matched and a focused decoder test checked an unknown flag and invalid battery input. | Runtime episode continuation and recovery, BX integration, status and triage. |
| R38, R44 | Source hashes and local Git exclusions were checked. The exact supplied Form 1 record confirms support and the false-alarm trade-off. | Final repo integrity and behavioral checks for the trade-off. |

[Audit results](../reports/data-audit.json) · [Calibration evidence](calibration.md) · [Threshold register](../config/rules.json) · [Analysis tests](../tests/test_offline_analysis.py)

## P02 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R01–R03, R06 | The pinned runtime installed under Python 3.12.2 and the documented command served real loopback HTTP with default and alternate references. The six-CSV-only alternate run passed under a Python outbound socket guard. `test_default_and_alternate_reference_directory` and both invalid-startup tests passed. | Ubuntu 24.04 runtime and OS-level network isolation. |
| R04, R05 | `test_lifespan_ignores_telemetry_and_recreates_store` blocked telemetry-directory access and verified that the prior database connection closed and its test marker was absent in the next store. | Verify persistence boundaries after P03 actually inserts observations. |
| R07–R09, R28 | The HTTP suite verified valid arrays of 0 and 5,000 entries, mixed raw items, invalid JSON and envelope handling, 5,001-entry rejection, required aware timestamps, and 404 for unknown serials or unsupported routes. Every valid envelope acknowledges zero processed entries in P02. | Independent event processing, accepted count semantics, and full replay latency. |
| R26, R27, R39, R40 | `test_health_status_and_triage_contract` and `test_response_enum_values_match_vendor_contract` verified the no-observation shape, contract enums, UTC output, and empty evidence. Fixture plan and case entries did not create a diagnosis. | Real facts, evidence cutoffs and nonempty triage items. |
| R29 | Startup validated the shipped rule register and rejected missing or invalid config. | Verify diagnosed behavior at each registered threshold. |

[Start and test commands](../README.md) · [HTTP tests](../tests/test_http_foundation.py)

## P03 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R04, R07–R09, R28 | HTTP tests confirmed empty state after restart, bounded mixed batches, and accepted counts. An unexpected store failure rolls the batch back. A read attempted during a partial write observes the committed batch as a unit. Preliminary HTTP replay accepted all 640,419 envelopes. Maximum request time was 2.585 s and server peak RSS was 64.574 MiB. | Release replay timing with final diagnoses and exam checkpoints. |
| R10–R13 | Runtime tests exercise same-batch replay, new aliases, ID conflicts, both time cutoffs, future clocks, invalid numeric timestamps, and out-of-order observations. Device status uses the eligible first receipt and the projection uses credible observation order. | Apply the same temporal snapshot to asset and incident decisions. |
| R18–R20, R26, R39–R40 | Projected facts retain newer faults through older observations. Deduplicated platform commands add one reboot fact and no contact. CSV plan rows and historical cases do not create events. Status evidence IDs come from eligible receipts. | Implement business rules and validate action-specific evidence. |
| R31 | Opaque BX records are accepted and retained with receipt provenance. | Decode and join those observations to devices in P08. |

[Ingestion and time model](ingestion.md) · [Temporal tests](../tests/test_temporal_ingest.py)

## P04 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R14, R15, R39 | HTTP fixtures verify zero-speed ignition-on tracking, exact driving and parked cutoffs, and late receipts that change contact without refreshing an old position. Future schedule does not establish ignition. | Actionable causes for overdue trackers. |
| R16, R19 | Camera fixtures cover the 15-minute sleep boundary, the 60-second wake grace, current recording, unresolved storage evidence, and missing or competing same-asset trackers. Selective source replay confirmed a sleeping camera. | Camera fault actions and escalation. |
| R17, R27 | A-series tests cover an empty history, numeric epoch seconds, jitter through 26 hours, and prolonged silence. Supported reporting uses cause `none`. | Battery and cold explanations. |
| R12, R21, R26 | Tests verify historical removed-tracker context, exclusion before installation, stock VIN evidence becoming available by receipt, and absence of future evidence. A selective source replay confirmed the same association cases. | Classify unresolved or mismatched assignments as individual faults. |

[Normal-status HTTP tests](../tests/test_normal_reporting.py) · [Normal-status decisions](decisions.md#p04-normal-status)

## P05 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R18, R19, R26 | The renamed power fixture verified backup corroboration, stale-restore rejection and later recovery. The camera tests verified retry-safe per-episode escalation, wake and plan gates, parked urgency, and reopening after recovery. A selective source replay reproduced P2 camera and P3 power statuses with the expected evidence and internal owners. | Publish shared and individual action items in triage. |
| R20, R39, R40 | A future or older plan update cannot clear a currently active diagnosis at the wrong time. Per-plan transition tests preserve resumption and platform-only contact remains null. | Actionable plan items in triage. |
| R21, R25 | VIN tests verify receipt-gated stock installation, conflicting live trackers, support routing, and suppression after a documented handover. | Shared outage cohort selection and triage ownership. |
| R22, R29 | Fixtures verify the 10% opening and 20% recovery battery cutoffs, depot-local cold and approved downtime boundaries, and bounded weak-signal and backfill evidence. Shipped rules carry no approved downtime. | Operational confirmation and BX-specific rules. |

[Individual diagnosis HTTP tests](../tests/test_individual_diagnosis.py) · [Cause precedence and policy](decisions.md#p05-individual-diagnosis)

## P06 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R12, R23, R29 | Renamed and rescheduled HTTP fixtures exercise both depot scopes, separate driving and awake-camera modes, calibrated count/share/spread and live contrast, dormant exclusions, synchronized cross-carrier loss, and same-firmware ambiguity. | Official practice and release checks. |
| R18, R19, R24, R25 | A physical power or storage failure remains independently actionable in a carrier loss. No serial belongs to both an incident and an individual item. Support follows up on an uncertain shared cause. | Job/shift urgency and additional support workflow tests in P07. |
| R23, R24, R26 | Fixtures verify historical opening evidence, late receipts and retries, elapsed silence, exact partial recovery, stable IDs, closure, and distinct recurrence. Status uses the same cause and eligible original evidence as triage. Full-history checkpoint replay verified both labeled outages, eight ordinary checkpoints with no shared group, and 693 eligible evidence references. | Official practice and end-state verification on the release environment. |

[Carrier incident HTTP tests](../tests/test_carrier_incidents.py) · [Runtime policy](decisions.md#p06-carrier-incidents)

## P07 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R18–R25 | Support HTTP fixtures verify each actionable cause and owner, actionable uncertainty, camera escalation on completed checks, an independent fault during a carrier outage, and benign exclusions. | Add BX diagnoses through the same support policy in P08. |
| R25, R29, R41 | Tests exercise exact job starts and ends, the inclusive two-hour deadline, remote response slack, both Toronto fall-back instants, Regina's unchanged offset and a Sunday shift. | Larchmont confirmation of the urgency policy. |
| R24, R26, R39 | Tests verify shared status and queue reasons, stable episode IDs and order, a unique serial partition, and original receipt-eligible evidence. The vendored support assertions also run against saved full-history responses. | Fresh-process official exam and release measurements. |

[Support HTTP tests](../tests/test_support_triage.py) · [Support queue decisions](decisions.md#p07-support-queue)

## P08 verification record

| Row | Observed evidence | Remaining work |
| --- | --- | --- |
| R26, R31, R39 | Three vendor anchors match UTC and Regina-local time, displayed battery, independent flags, and coordinates. HTTP fixtures cover mixed malformed and valid input, exact inventory matching, original receipt evidence, semantic retry, clock cutoffs, and unknown bits. A full mixed replay accepted all 313 BX envelopes and verified 308 distinct readings and their first original receipts. | Fresh-process official exam and release verification. |
| R22, R24, R25, R29, R31 | An unseen BX frame at about 14% with a low flag creates a technician item. Tests verify exact 26-hour timeliness, support follow-up for prolonged operational silence, strictly later 20% recovery with the flag clear, valid-fix provenance across a no-fix report, and stock/pre-installation contact. | Verify new frames through the release entrypoint and record optional BX completion in Form 3. |

[BX verification and regeneration](bx-decoding.md) · [BX HTTP tests](../tests/test_bx.py)

## P09 verification record

| Requirements | Acceptance scenarios | Observed check |
| --- | --- | --- |
| R02–R06, R27 | A01–A07, H10 | `test_entrypoint_uses_reference_only_directory_and_restarts_empty_with_egress_denied` ran two real localhost:8080 processes with only six CSVs and a Python network audit guard. Ingest changed the first process's status and queue. The second started empty. CDN-backed docs returned 404 and the local OpenAPI description returned 200. Prior tests still cover forbidden startup data reads and failed readiness on bad configuration. |
| R07–R13, R28, R39 | A08–A16, B01–B05, B14–B17, B20, B21 | `test_mixed_wire_elements_cannot_corrupt_valid_neighbors_or_add_a_catalog_device` exercises a valid JSON overflow exponent, boolean fields, naive and future device clocks, same-ID conflict and an unknown type/serial with valid neighbors. `test_renamed_relocated_repartitioned_and_retried_fleet_keeps_its_meaning` replays a 5,000-entry batch, permutes rows across smaller requests, reorders keys on later aliases, and changes host time before a repeat query. The store rollback and snapshot tests also pass. |
| R12, R18–R21, R24–R26, R31, R39, R40 | B06–B13, B17–B19, B22, D01–D03, D12–D19, E05, E12–E13, E19–E20, G09–G11, G14 | `test_ingested_future_receipts_leave_the_entire_view_unchanged_until_eligible` compares every roster status and the entire queue before and after future recovery, plan activation, a VIN claim and a retry have arrived. Their receipts gate changes to issues, owners, priorities, membership and evidence. A newly ingested, genuinely earlier receipt adds knowledge. Older fault backfill leaves resolved issues closed. `test_reference_cases_and_plan_rows_do_not_leak_current_diagnosis` changes reference case outcomes and copied plan rows without changing the eligible stream or results. |
| R18–R20, R22, R25, R26, R29 | B23, D07–D12, D14, D21–D22, D33–D34, E19 | The coincident-readings and plan-hold tests preserve issue IDs and causal evidence in both event-ID orders. The awake-trial tests distinguish expired ignition, transient power loss, a late ignition-off and continuous confirmations, with explicit assertions just before and at the 600-second grace boundary. |
| R21, R23–R27, R41 | B18, C15, D15, E01–E02, E05, E12–E13, E15–E20, F01–F07 | The relocated fleet fixture changes event, serial and asset IDs, depot, carrier, and calendar date at equivalent local Sunday hours. The tracker marked removed in final inventory still belongs to the historical operating cohort. Status, triage and original evidence roles match. The shared synthetic HTTP auditor verifies exact fields, UTC, finite confidence, allowed enums, serial partition and original committed evidence by `at`. Existing exact shift and DST boundary fixtures remain in the suite. |
| R22, R30, R31, R38, R40 | D28–D29, D32, G01–G14, H01 | The landscaping gap stays uncertain with no approved downtime. A negative closure appears as −900 seconds in the offline audit and is excluded from duration labels. A targeted replay of the 313 BX envelopes found 308 distinct readings and one technician battery item at the final checkpoint. All nine vendor hashes matched. |

[Adversarial scenarios](../tests/test_adversarial.py) · [HTTP evidence auditor](../tests/evidence_client.py) · [Process test](../tests/test_process_lifecycle.py) · [Offline data tests](../tests/test_offline_analysis.py) · [Remaining gates](../planning/STATUS.md#next-phase)

## P10 verification record

| Requirements | Acceptance scenarios | Observed check |
| --- | --- | --- |
| R02–R06, R38 | A01–A06, H01, H10, H16 | Verified the full vendor hash manifest. The real entrypoint started and restarted against six renamed reference CSVs with macOS OS outbound restrictions, a Python socket and DNS guard, and denied corpus access. Health, ingest, status, triage and local OpenAPI worked. The fresh install matched all 15 runtime pins. Ubuntu 24.04 execution remains pending. |
| R07–R13, R28, R32 | A10–A14, B01–B05, H02–H03, H07–H08 | Original preflight passed 10/10, with malformed-neighbor isolation, an unused kind and HTTP 400 for malformed JSON. Practice ran in a different empty process and passed 14/14. All 640,419 envelopes were accounted for and 7,609 retries matched the independent audit. Every 5,000-event request completed in under 2.57 s. The report includes measured percentiles, startup, wall time, peak service RSS and all checkpoint queries. |
| R18, R19, R23–R26 | D01–D04, D05–D12, E01, E05, E12, H04–H06 | P1 grouped all 35 expected trackers in a carrier-owned incident. P2 preserved the storage-fault evidence and support-first action and excluded the expected sleeping camera. P3 retained power-loss evidence and technician ownership. Verified 405 evidence references by their receipt cutoffs. |
| R26, R32, R34 | H08, H13 | Baseline P3 and END triage warnings led to a query-profile fix. The final run had zero warnings and its ten saved checkpoint responses matched the baseline byte for byte. The verifier captured and validated the complete seven-item queue at the exact END instant. Its Form 3 extraction remains P12. |

[Measured report](../reports/release-verification.json) · [Reproduction commands](../README.md#release-verification) · [Focused tracker projection regression](../tests/test_support_triage.py) · [Process and vendor tests](../tests/test_process_lifecycle.py)
