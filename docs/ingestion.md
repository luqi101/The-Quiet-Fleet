# Ingestion and as-of facts

## Storage and identity

| SQLite table | Contents |
| --- | --- |
| `messages` | One row per logical observation. Stores its semantic SHA-256 fingerprint, serial, original and normalized type, observation time, canonical payload, device-origin flag, and the first receipt's original ID, raw clock, and time quality. |
| `event_ids` | Binds each original event ID to one logical observation. The first valid binding wins. A different observation using that ID is excluded and increments a per-process conflict count. |
| `receipts` | One row per original ID and distinct receipt instant. Stores the raw device-time value and canonical envelope SHA-256. Identical replays preserve existing rows. |

The semantic fingerprint covers serial, source kind, canonical observation instant, and sorted-key JSON payload. It excludes `event_id` and `received_at`. A new ID repeating a known observation adds receipt provenance. Source payload values and JSON number representations are preserved. BX frames use the exact inventory serial, normalized wire clock, and decoded payload values. The receipt retains the original clock spelling and the digest of the supplied envelope.

Representative evidence comes from the earliest ingested receipt and breaks ties by original ID, then envelope hash. A later retry leaves the first receipt and clock quality intact. An incoming copy with an earlier platform receipt can change retrospective evidence once that copy has been ingested.

The service opens one SQLite connection in a new temporary directory for each worker lifespan. Writes use parameterized statements and a transaction per batch. One lock covers transactions and snapshot reads. Reads copy the selected serial's rows before projecting immutable facts, leaving the database available for the next request. The store indexes serial and first receipt, plus event kind, serial, and observation. Query results are computed on demand.

## Availability and ordering

- Packet timestamps use aware ISO timestamps with `Z` or explicit offsets and a UTC range of 2000 inclusive to 2100 exclusive. Legacy A `check_in` clocks and hexadecimal BX clocks represent Unix **seconds**. Booleans, nonfinite values, milliseconds, naive clocks, and precision beyond microseconds are rejected. The HTTP `at` parser shares the aware format and does not use the packet range.
- A query sees only receipts that have been ingested and are at or before `at`. Credible facts also require observation time at or before `at`. The observation order is normalized UTC time, then first receipt and original ID. Buffered observations retain their true observation times.
- With the shipped zero-second tolerance, observations ahead of the first receipt contribute contact evidence only. They cannot change ignition, recording, faults, plans, or fresh measurements. Device and platform events retain their source distinction.
- `last_heard_at` is the latest first receipt of an eligible device-origin observation. The projection separately exposes the newest credible measurement. A backfilled reading may establish later contact while leaving the newest measurement and fault facts unchanged. Platform commands and plans never prove device contact.
- Projection returns chronology for ignition, recording and storage error, power disconnection and restoration, reboot commands, plans, and battery readings. Only a strictly later credible recording or power restoration clears the respective fault fact. BX projects the latest eligible check-in and the latest valid fix separately. Reference plan and case CSVs remain reference data.

## Accepted counts

An invalid batch object, malformed JSON, or more than 5,000 elements returns HTTP 400. Within a valid array, each known item is validated independently. The integer `accepted` includes valid known items, exact and semantic retries, and unused kinds with a valid event ID, kind and receipt. It excludes malformed items and conflicting ID reuses. Unexpected failures surface, and a failed store transaction rolls back.

Device status uses these facts to evaluate normal reporting, expected quiet, and individual faults. Triage uses the same diagnosis and evidence cutoffs as device status. [Support queue policy](decisions.md#p07-support-queue) · [BX decoding](bx-decoding.md) · [Project status](../planning/STATUS.md)

## Preliminary full-corpus HTTP benchmark

Run against a fresh local process from the checkout root. The harness streams the JSONL files in 5,000-event HTTP requests and measures request duration and the server process's peak resident memory. It writes optional results under the ignored local directory.

```bash
python scripts/benchmark_ingest.py --data "$PWD/data" --output .local/p03-ingest-benchmark.json
```

On macOS 15.7.9 x86-64 with Python 3.12.2, the server accepted all 640,419 supplied envelopes across 128 full requests and one 419-event request. Total replay took 206.07 seconds. HTTP latency was 1.620 s p50, 2.145 s p95, and 2.585 s maximum. Server peak RSS was 64.574 MiB. All requests finished under 10 seconds. This run measured ingestion with the P03 foundation. Final exam and diagnosis performance remain release checks.
