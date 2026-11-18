# Primer: how fleet devices report

No fleet experience needed. This page covers what's true of telematics in
general. Larchmont's own device rules are in section 1 of the brief.

## The path an event takes

A device on a vehicle or trailer records something (a position, an ignition
change, a camera status), stamps it with its own clock (`device_time`) and
sends it over a cellular carrier's network to the platform, which stamps it
again when it arrives (`received_at`). Your service sees events in the order
the platform received them.

Most of the time the two stamps are seconds apart. When they aren't, it's
usually for one of these reasons:

- **No signal.** In a dead zone or a basement garage, a device keeps its
  events in memory and sends them all when it reconnects. They arrive late,
  in a burst.
- **The carrier is down.** Every device on that carrier in the area goes quiet
  at about the same time, whatever it was doing. Devices that buffer send
  their backlog when service returns.
- **The device's clock is wrong.** Clocks drift, and some firmware writes the
  time in a different format.
- **Retries.** If a device or the platform isn't sure a message got through, it
  sends it again. The same reading can arrive twice, sometimes with a new
  event ID.

## Why a device goes quiet

Quiet isn't the same as broken. Common reasons, roughly from harmless to
serious:

| Reason | What it looks like |
|---|---|
| Parked | A vehicle tracker drops from frequent positions to occasional heartbeats. |
| Sleeping by design | Cameras and battery devices power down to save energy. |
| Cold weather | Batteries lose capacity in the cold. A battery device can miss a check-in on a cold night and recover when it warms up. |
| Planned downtime | The customer has stopped using the asset for a while: off-season equipment, a vehicle in the shop. |
| No coverage | Out of range; the data usually arrives later. |
| Carrier outage | Many devices on one carrier go quiet together. Nothing on the vehicles is wrong. |
| Data plan paused or ended | The device works but isn't allowed to send. Fixed on the account, not on site. |
| Device swapped | A replacement was installed but the records still point to the old one. The old serial goes quiet; a new serial appears on the same vehicle. |
| Lost power | A wired tracker was unplugged or its wiring failed. It often sends a final alert from its small backup battery, then goes silent. Someone has to go and fix it. |
| Low battery | A battery device is running out. It needs a new battery or a new device. |
| Hardware fault | A camera's storage card fails, for example. Sometimes a remote reboot fixes it; sometimes it needs a technician. |

## Things that help you tell them apart

- What the device was doing just before it went quiet: driving, parked, or
  already reporting a problem.
- Whether other devices went quiet at the same time, and what they have in
  common (carrier, depot, model, firmware).
- Whether the asset has a reason to be idle: its schedule, the season, the
  weather.
- Whether late data turns up afterwards.
- What the account and support history say: plan changes, past cases with the
  same symptoms, and how they were fixed.
- What other devices on the same asset show. A vehicle with a quiet camera but
  a tracker that's still moving is a different story from one where both
  stopped.

## Who can fix what

- **The customer** (Larchmont's own staff): park or move an asset, confirm
  it's idle, approve a plan change.
- **A technician**: anything that needs hands on the device, such as rewiring,
  replacing a battery or a storage card, or swapping hardware.
- **The carrier**: network outages.
- **Support**: remote actions such as a reboot, fixing records, account and
  plan changes, and chasing the carrier.

Sending a technician costs real money and a slot from a small daily
allowance. Waking someone up for a problem that fixes itself costs trust.
Missing a real problem costs a job that can't be tracked or recorded.
