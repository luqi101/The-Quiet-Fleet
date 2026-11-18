# Practice exam: expected outputs

`python exam/qf_exam.py practice` starts streaming the history into your
service from Oct 4. It pauses at each checkpoint below, asks your service
about it, checks the answer, then carries on to the end of Oct 31.

The hidden exam works the same way, with more checkpoints in a window after
the history. Every check below is one the hidden exam also uses.

On every checkpoint, the tool also checks that your persona's answer follows
the contract and Larchmont's rules: allowed values only, no device in two
triage items, swaps that are the same type and depot and free for the whole
slot, visits inside visit hours and capacity. For swaps, the scenario file
lists the assets that couldn't be seen or recorded at that moment
(`unavailable_assets`).

Only the checks for your persona run, plus the status checks.

## P1 · Mon Oct 12, 14:45 UTC (10:45 in Mississauga)

**What happened.** At about 14:02, 35 Mississauga trackers that were mid-drive
stopped reporting at once. All are on the Lakeline network. Northwave vehicles
driving at the same time kept reporting.

| Check | Expected |
|---|---|
| Status of 3 of those trackers | `likely_cause: carrier_outage`; `state` `needs_action` or `unknown` |
| Support agent: `/triage` | One `incident` item holding at least 80% of the 35, `likely_cause: carrier_outage`, `who_acts: carrier`. None of the 35 in any other item. |
| Fleet manager: `/job-cover?depot=MSS&hours=4` | No swaps and no gaps for jobs on those assets. The network is down, not the vehicles. Listing them with `keep`, or leaving them out, are both fine. A swap for any other reason must not land on a Mississauga asset with Lakeline devices: it can't be seen either. |
| Field-tech scheduler: `/visits?days=1` | No visits for those assets. A technician can't fix a carrier. |

## P2 · Tue Oct 20, 15:50 UTC (11:50 in Mississauga)

**What happened.** The camera on V-133 (`C-2957`) reported `storage_error` at
15:10 (event `e47594389`) and has recorded nothing since, while the van drives.
Meanwhile V-140's ignition went off at 14:57 and its camera (`C-2179`) went to
sleep at 15:12, as designed.

| Check | Expected |
|---|---|
| Status of `C-2957` | `needs_action`, `camera_fault`, evidence includes `e47594389` |
| Status of `C-2179` | `quiet_expected`, `sleeping_by_design` |
| Support agent | A `C-2957` item with `camera_fault` and `who_acts: support`: in the case history most camera faults were fixed by a remote reboot, so support tries that first. `C-2179` is not in triage. |
| Fleet manager: `hours=4` | Job `J-MSS-1020-01936` (V-133, starts 15:59) listed with `problem: no_video` (or `both`). Any decision is accepted here; a swap must be valid. V-140 isn't listed (`hours=24`). |
| Field-tech scheduler: `days=2` | No visit for V-133 yet, because a remote reboot comes first. No visit for V-140. |

## P3 · Mon Oct 26, 23:30 UTC (17:30 in Regina)

**What happened.** Pickup K-27's tracker (`T-59847`) sent `power_disconnect`
at 18:10 (event `e33683614`) and a backup-battery `low_voltage` at 18:20
(`e78779377`), then went silent while the truck was still out.

| Check | Expected |
|---|---|
| Status of `T-59847` | `needs_action`, `power_loss`, evidence includes one of those two events |
| Support agent | A `T-59847` item with `power_loss` and `who_acts: technician` |
| Fleet manager: `/job-cover?depot=REG&hours=24` | `J-REG-1027-08488` (K-27, Tuesday 07:55 local) listed as `no_location` with a valid `swap`. K-22, K-23 and K-31 are all free. `J-REG-1027-08489` listed too; any valid decision. |
| Field-tech scheduler: `days=2` | A visit for K-27 on Tuesday Oct 27 within visit hours (13:00 to 21:00 UTC), `reason: power_loss` |

## END · Sat Oct 31, 23:59 UTC

No checks. The tool saves your persona's answer at the end of the history in
`exam/results/`. Form 3 asks for your persona's top 3 actions at this moment.

## Reading the results

Every response is saved as JSON in `exam/results/`, named by checkpoint and
endpoint. A FAIL line says what was expected and what your service returned.
The practice exam is for you; it isn't scored.
