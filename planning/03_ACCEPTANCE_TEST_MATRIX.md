# Acceptance and release test matrix

This is a checklist for tests to implement and execute, not a report of tests already passed. Put actual test names, execution evidence, and status beside each row in `docs/requirements.md` or a generated verification report. Use independent synthetic fixtures wherever possible.

## A. Startup, transport, and malformed input

| ID | Scenario | Required assertion |
|---|---|---|
| A01 | Start from documented command | Listens on localhost:8080; `/health` returns exactly the required ready shape |
| A02 | Clean reference-only directory | Starts using an alternate `QF_DATA_DIR` containing only six CSVs |
| A03 | Poison telemetry directory | Startup does not open/read telemetry JSONL even if present or unreadable |
| A04 | Process restart | After ingest/stop/start, telemetry is empty; no previous-run state leaks |
| A05 | Missing/invalid critical config | Fails clearly before readiness rather than serving inconsistent data |
| A06 | Runtime network unavailable | Startup and required API operations work with external connections unavailable |
| A07 | Exact required fields | Status and triage match the contract; no missing keys, invalid enum, NaN/Infinity, or non-JSON value |
| A08 | Unknown catalog serial | Returns 404; known stock/no-data serial is not 404 |
| A09 | Missing, malformed, or naive `at` | Returns JSON 400, not 422/500 |
| A10 | Invalid JSON request body | Returns 400 without crashing the process |
| A11 | Invalid envelope | Missing/non-list `events`, scalar/null body, and >5,000 items return 400 |
| A12 | Empty batch | Returns 200 with documented zero accepted count |
| A13 | Mixed malformed batch | Good events before/after bad elements are processed; entire batch returns 200 |
| A14 | Unknown event type | Accepted/ignored by documented policy; no effect on health or state |
| A15 | Unsupported persona path | Does not return fake success; only chosen persona autodetects |
| A16 | Concurrent ingest/query | Response comes from a coherent snapshot; no database/thread errors or partial batch state |

## B. Identity, receipts, observation time, and evidence

| ID | Scenario | Required assertion |
|---|---|---|
| B01 | Same batch ingested twice | All domain responses unchanged |
| B02 | Same observation, new event ID, later receipt | No health refresh, extra fault, duplicate member, or extra reboot attempt |
| B03 | Payload key order changes | Semantically identical JSON is deduplicated |
| B04 | Same payload, different actual observation times | Distinct real reports remain distinct |
| B05 | Same ID, conflicting content | Original valid observation is not overwritten; conflict is reported internally |
| B06 | Future receipt already ingested | Cannot affect any earlier status, cause, owner, priority, association, grouping, or evidence |
| B07 | Future ID alias on an old observation | Earlier response cannot cite that future alias or gain retry freshness |
| B08 | Earlier-received observation ingested later | Once ingested, can legitimately add information to retrospective queries; distinguished from duplicate semantics |
| B09 | Newer receipt contains older ignition-on | Does not overturn later real ignition-off |
| B10 | Old recording arrives after newer storage error | Error remains unresolved |
| B11 | Old high battery arrives after later low reading | Does not falsely repair low battery |
| B12 | Old power disconnect arrives after later restore | Does not reopen the resolved episode |
| B13 | Buffered old positions arrive in a burst | May establish transport recovery; do not falsely become current location measurements |
| B14 | Future/corrupt device timestamp | Cannot remain fresh forever or alter the past; uncertainty policy is explicit |
| B15 | Legacy A integer Unix seconds | Correctly normalized as seconds, not milliseconds/naive date |
| B16 | Bool, nonfinite, huge numeric times | Rejected or safely uncertain under documented policy |
| B17 | Command/plan event alone | Does not count as device-origin contact |
| B18 | Evidence audit | Every ID belongs to an eligible original receipt by `at`; important causal IDs present |
| B19 | No observations | No fabricated event ID; empty evidence and null last contact permitted |
| B20 | Repeated GET / host clock changes | Same inputs/at produce identical decision content; no wall-clock dependence |
| B21 | Equivalent batch partitions/permutations | Same final eligible message set yields equivalent decisions and deterministic evidence policy |
| B22 | CSV future case/plan rows | Do not reveal future current-episode diagnosis, recovery, pause, or resume |

## C. Normal device behavior

| ID | Scenario | Required assertion |
|---|---|---|
| C01 | T tracker driving on cadence | `reporting/none` with real evidence |
| C02 | T tracker zero speed, ignition true | Still treated in ignition-on cadence, not parked heartbeat mode |
| C03 | T parked, healthy contact within tolerance | Expected quiet/normal parked interpretation; no triage alarm |
| C04 | Parked T at 269:59, 270:00, 270:01 since contact | Exact source-derived late-after boundary is consistent |
| C05 | Driving T at/beyond calibrated deadline | Short-mode overdue policy, distinct from 270 minutes |
| C06 | Unknown ignition + future scheduled job | Does not manufacture current driving; deadline can affect follow-up priority |
| C07 | Camera during 15-minute post-off period | Allows transition and evaluates actual observations; not premature sleeping/fault |
| C08 | Camera asleep after ignition off | `quiet_expected/sleeping_by_design`; excluded from triage |
| C09 | Sleeping camera followed by new ignition-on | Sleep expires; wake grace then current recording required |
| C10 | Camera booting | Not confused with recording, error, or proof of recovery |
| C11 | A tag before daily report is due | No premature miss |
| C12 | Healthy A daily jitter near observed maximum | No false alarm from a hard 24-hour cutoff |
| C13 | A missing one versus multiple opportunities | Bounded, calibrated escalation rather than immediate vehicle-style alarm |
| C14 | Sparse newly installed A/BX | Uses documented defaults; no future per-device phase knowledge |
| C15 | Reporting output state | Every `reporting` response uses cause `none` |

## D. Fault episodes, operational context, and recovery

| ID | Scenario | Required assertion |
|---|---|---|
| D01 | Disconnect then backup low voltage | `needs_action/power_loss`, technician owner when actionable |
| D02 | Disconnect then more positions | Fault remains; backup communication is not external-power recovery |
| D03 | Later credible power restore | Episode resolves; old fault no longer generates a ticket |
| D04 | Vehicle low voltage without backup source | Not blindly treated as identical to explicit external disconnect |
| D05 | Camera storage error during drive | `camera_fault`, key error evidence, support first |
| D06 | Camera stops recording without an explicit error | Sustained awake loss can be diagnosed after other explanations/grace |
| D07 | First reboot issued | Attempt recorded, not success; owner remains appropriate during grace |
| D08 | Two unique failed current-episode reboots | Escalates under documented awake/grace criteria |
| D09 | Duplicate/retried reboot | Counts once |
| D10 | Reboots from prior episode | Do not prematurely escalate a new independent fault |
| D11 | Booting/sleeping after error | Does not prove recording repaired; urgency may change with use |
| D12 | Later recording after error | Clears current camera fault |
| D13 | Paused or ended plan | Cause `plan_paused`, account/support owner, no technician |
| D14 | Later active plan | Pause explanation clears, fresh reporting still assessed separately |
| D15 | Removed inventory tracker before actual swap | Can still be historically active and in a carrier cohort |
| D16 | Stock serial with matching VIN telemetry | Recognized as possible installed replacement; support record reconciliation if unresolved |
| D17 | Static replacement installed after query | Not retroactively active before evidence/installation context |
| D18 | Two live serials claim same VIN | Conflict remains visible; no arbitrary binding |
| D19 | Known documented completed removal | Does not create permanent redundant triage next to a consistent replacement |
| D20 | Battery below validated threshold while still reporting | Fault can be actionable before silence |
| D21 | Battery hovering at cutoff | Comparator/hysteresis deterministic; no uncontrolled flapping |
| D22 | Later credible battery recovery | Clears fault; old high/low backfill does not reverse it |
| D23 | Cold weather plus healthy battery and one miss | Bounded cold interpretation, appropriate local date |
| D24 | Cold weather plus explicit depleted battery | Battery fault is not hidden by temperature |
| D25 | Tomorrow cold but today normal | Future weather is not today's cause |
| D26 | Extended silence beyond cold grace | Becomes uncertain/actionable; suppression not permanent |
| D27 | Confirmed seasonal policy with effective dates | Applied only to correct use/depot/window; boundary tested |
| D28 | No jobs without confirmed downtime | Does not automatically prove planned shutdown |
| D29 | Landscaping stop pattern without ops confirmation | Hypothesis/uncertainty documented, not falsely claimed confirmed |
| D30 | Known isolated coverage pattern | No automatic physical dispatch; bounded follow-up |
| D31 | Currently unexplained gap later recovers | Earlier answer cannot use future recovery as a feature |
| D32 | Case closure before open | Reported/excluded for duration calibration, not silently fixed or made a current feature |

## E. Incidents, support ownership, and priority

| ID | Scenario | Required assertion |
|---|---|---|
| E01 | One-carrier mass interruption with healthy other-carrier peers | Correct generalized carrier cause, one compatible incident, carrier owner |
| E02 | Same scenario, carrier/depot/serials renamed | Same meaning; no practice allowlist required |
| E03 | Normal end of shift | Does not become a carrier incident |
| E04 | Parked, sleeping, or not-due daily devices on same carrier | Not automatically absorbed as affected members |
| E05 | Individual power fault during mass interruption | Stays correctly diagnosed/owned; not swallowed by group |
| E06 | Both carriers interrupted | Does not invent one carrier as cause from count alone |
| E07 | One firmware across carriers | Competing model/platform hypothesis not misrepresented as certain carrier outage |
| E08 | Long ongoing outage | Cohort does not disappear because a lookback window expired |
| E09 | Partial recovery | Membership/continuation follows documented evidence policy |
| E10 | Full recovery, later second outage | First closes; second is distinct and deterministic |
| E11 | Many retry messages from few devices | Cannot satisfy an independent-device count threshold |
| E12 | Triage serial ownership | Across all items, each serial appears at most once |
| E13 | Item shape | Device=one serial; incident=multiple compatible serials; assets deduplicated |
| E14 | Benign expected states | No normal sleep/parking/cold/downtime noise without actual follow-up need |
| E15 | Owners | Account/records/support, carrier/network, technician/physical repairs, remote-first camera correctly routed |
| E16 | Active job vs ended job | Half-open start/end boundaries determine priority correctly |
| E17 | Upcoming urgent job/shift | Configured deadline/horizon applied consistently across causes |
| E18 | No imminent use | Serious fault remains visible at proportionate priority, not invented current job |
| E19 | Stable repeated snapshot | Same items, ordering, IDs, reasons, and evidence policy |
| E20 | Status/triage agreement | Shared engine's cause and actionability align |
| E21 | Reasons/next action | Real observation, timing, expectation, consequence, and specific recommended step |
| E22 | No executable side effect | Query does not send reboot, email, customer alert, plan change, or acknowledgment |

## F. Timezones and local business rules

| ID | Scenario | Required assertion |
|---|---|---|
| F01 | MSS before Nov 1 06:00 UTC | Correct EDT/UTC-4 local time |
| F02 | MSS after DST transition | Correct EST/UTC-5, including repeated 01:00 hour |
| F03 | Regina across same transition | Remains UTC-6 |
| F04 | UTC day differs from depot local day | Weather and next-shift dates use correct local day |
| F05 | Query exactly at 06:00 local | Current/next shift handling documented and tested |
| F06 | Weekend job/shift | Not silently removed by technician-only weekday restrictions |
| F07 | Threshold seconds vs minutes/hours | Units consistent in config, arithmetic, reasons, and tests |

## G. BX decoder and full integration

| ID | Scenario | Required assertion |
|---|---|---|
| G01 | Three original portal anchors | UTC/local time, percentages, flags, signed coordinates all match |
| G02 | 3094 battery raw | Display 76%, not truncation to 75 and not millivolts |
| G03 | Independent bit combinations | 0,1,8,9,10,11,12 and other valid combinations decode by bit masks |
| G04 | Unknown 0x04 or future bits | Preserved as unknown; known meanings still work |
| G05 | No outer serial/device_time/payload | Real bx_raw envelope accepted and correctly normalized |
| G06 | Malformed raw JSON/fields/ranges | Event isolated, valid batch neighbors survive |
| G07 | GPS fix false with plausible coordinates | Coordinates not claimed as a new valid fix; communication remains recognized |
| G08 | New unseen valid frame | Real status/triage changes without sample lookup |
| G09 | Low flag at approximately 14% | Actionable BX battery policy does not rely on A's <10% rule |
| G10 | Duplicate/new-ID BX retry | No freshness or task multiplication |
| G11 | Future receipt/old BX sample | Same as-of protections as other families |
| G12 | Numeric range/bool/nonfinite/hex validation | No crash or unsafe silent coercion |
| G13 | All stream frames, not only separate file | Additional valid messages decode; 300-file preload unnecessary |
| G14 | Later battery recovery | Correctly resolves current BX fault according to documented policy |

## H. Official exam, resource limits, and presentation

| ID | Scenario | Required assertion |
|---|---|---|
| H01 | Vendor source integrity | Tool, contract, primer, and practice files match recorded hashes |
| H02 | Official preflight | Passes; warnings assessed; malformed batch survival tested |
| H03 | Separate fresh practice run | All checks pass; no leftover preflight state |
| H04 | P1 | Three checked statuses carrier_outage; one incident covers >=80% of 35; carrier owner; no duplicate members |
| H05 | P2 | C-2957 fault with e47594389 and support owner; C-2179 expected sleep and excluded |
| H06 | P3 | T-59847 power_loss with key evidence and technician owner |
| H07 | Full replay batch timing | Every 5,000-event request <10 s on tested environment; report max/percentiles |
| H08 | Full replay memory/query latency | Bounded measured memory and reasonable checkpoint times, no whole-corpus scan per device |
| H09 | Fresh Ubuntu 24.04/Python 3.12 environment | Install then start/check with exact documented commands |
| H10 | Offline optional dashboard/API docs | No CDN/font/map/analytics/script requests required |
| H11 | UI empty/error/input behavior | Shows real empty state and errors; no fake loaded data or wall-clock decision |
| H12 | UI and API | Same decisions; frontend only presents data and safely escapes it |
| H13 | End state exact checkpoint | Top actions captured at 2026-10-31T23:59:00Z from real service |
| H14 | Submission evidence | Thresholds, trade-off, real AI use, Form 1 changes, <=300-word product note present |
| H15 | Release source identity | Tested source and published commit match; no unverified last-minute logic change |
| H16 | Git hygiene | No secrets, corpus, virtualenv, databases, fake dates, or premature public push |

## I. A concrete Ubuntu/offline verification target

If local development is on macOS or Windows, have Codex create a development-only `Dockerfile.verify` with Ubuntu 24.04, Python 3.12, local timezone data, and the pinned runtime/development requirements installed during `docker build`. Use `/app` as the workdir. Keep raw corpus files out of the image and mount them at run time. `scripts/release_check.py` must start fresh child services and run the checks from inside the same container, so loopback remains available when external networking is disabled.

These are target commands to make real during P13:

```bash
docker build -f Dockerfile.verify -t quiet-fleet-verify .
docker run --rm --network none -v "$PWD/data:/qf-data:ro" -v "$PWD/reports:/app/reports" -e QF_DATA_DIR=/qf-data quiet-fleet-verify python scripts/release_check.py --data /qf-data --persona support
```

The first step has internet for dependency installation. The second disables networking except the container's own loopback, which is sufficient for an exam runner and service inside it. Ensure the release script invokes actual local HTTP endpoints rather than bypassing the API. Record the observed OS/Python versions and real output. This verification Dockerfile is optional tooling for a Python service, not a new runtime requirement for the grader.

If Docker or equivalent isolation is unavailable, record that specific unexecuted gate and run the strongest available process/socket isolation test. Do not label “reviewed imports” or “tested on Mac” as verified Ubuntu/offline behavior.
