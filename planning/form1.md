# The Quiet Fleet — Form 1: Intent & Brainstorm

## 1. Which endpoints must every persona expose, and what happens to your service after you submit?

Every persona must expose:

- `POST /ingest` — receives device events, including late, duplicate, or out-of-order events.
- `GET /devices/{serial}/status?at=` — returns a device's status, likely cause, reasons, and supporting evidence.

After submission, the evaluators start our service using the README instructions and test it against a hidden exam of realistic scenarios. They then conduct a 45-minute call involving a demo, a live code change, and questions.

## 2. The brief says when it's normal for a dash camera to go quiet. What's the rule?

A C-series dash camera normally goes to sleep **15 minutes after the vehicle's ignition is turned off** and automatically wakes when the ignition turns back on. This is expected behaviour, not a fault.

## 3. Which persona will you build for?

**Selected persona: Support agent**

### 3 (continued). Describe them in three sentences: what they decide, when, and what it costs if your system is wrong.

A support agent decides which devices need attention, who should handle them, and what action to take. They make these decisions throughout the day, especially before shifts begin. If the system is wrong, they could waste time on false alarms or miss real problems that disrupt operations.

## 4. List every way the incoming data could mislead your system. Aim for eight or more.

1. Duplicate events make devices appear more active.
2. Events arrive late.
3. Events arrive out of order.
4. Device clocks show incorrect times.
5. Cameras intentionally sleep when ignition is off.
6. Parked vehicle trackers report less frequently.
7. Battery trackers only report once daily.
8. Poor cellular coverage causes temporary silence.
9. Carrier outages affect many devices together.
10. Paused or expired connectivity plans stop reporting.
11. Cold weather affects battery performance.
12. Power disconnections cause devices to go offline.
13. Incorrect device-to-vehicle assignments cause confusion.
14. Different depot time zones lead to timing mistakes.
15. Missing or corrupted events create incomplete information.
16. New BX-series devices use an unfamiliar message format.

## 5. Describe your system in words: what comes in, what it has to remember between events, and what goes out.

The system receives device events, vehicle information, schedules, connectivity plans, and other relevant data. It remembers device activity, ignition state, timestamps, and previous events while handling duplicates and delayed information. It then identifies genuine problems, groups related failures, and returns device statuses, priorities, recommended actions, and supporting evidence.

## 6. What will you build, and what will you deliberately not build?

I will build a small offline service with the three required endpoints: `/ingest`, `/devices/{serial}/status`, and `/triage`. It will detect device problems, identify likely causes, group related incidents, and prioritize actions using rules calibrated from historical data. I will also attempt BX-series decoding if the provided examples support a reliable mapping.

I won't build a user interface, fleet job swapping, technician scheduling, or external API integrations.

## 7. How will you know it works before our exam does?

I will run the provided preflight check and sample exam, then compare my outputs with the expected results. I will also write tests for duplicate events, delayed data, normal camera sleep, genuine failures, carrier outages, and time-zone differences. Finally, I will verify that the service starts with one command, works offline, and returns correct evidence IDs.

## 8. For your persona, which is worse: a false alarm or a miss?

**Selected choice: A false alarm**

### 8 (continued). Say why, and how that changes what you build.

False alarms are worse for my support agent because they waste time, create unnecessary work, and can hide real problems among too many alerts.

I will reduce them by checking ignition status, normal reporting intervals, carrier problems, and other available evidence before raising an alert. I will also group devices affected by the same issue instead of creating hundreds of separate alerts, while prioritizing clear problems that threaten upcoming jobs.

## 9. In July 2022, one carrier's outage took millions of Canadians offline for most of a day. When hundreds of a customer's devices go quiet at once, should the product alert the customer at all? Take a side.

**Selected choice: Yes, alert the customer**

### 9 (continued). Why?

The customer needs to know when a major outage affects their fleet and operations. However, instead of sending hundreds of separate alerts, the system should group them into one clear alert explaining the likely cause, affected devices, and recommended action. This keeps the customer informed without overwhelming them with unnecessary notifications.
