# BX decoding and support behavior

The BX envelope contains `event_id`, `received_at`, `type: bx_raw`, and a JSON string in `raw`. The service resolves the decoded serial against the BX entries in `devices.csv`. The normalized report keeps the outer event ID and receipt time, the original hexadecimal clock, and the decoded observation time. Vendor examples and the portal readout are development inputs.

| Wire field | Decoded value |
| --- | --- |
| `u` | Exact BX inventory serial |
| `t` | Hexadecimal Unix seconds in UTC. The shared packet range is 2000 inclusive through 2100 exclusive. |
| `b` | Integer raw battery code from 0 through 4095. The estimated percentage is `100 * b / 4095`. |
| `s & 0x01` | Moving |
| `s & 0x02` | Low-battery flag |
| `s & 0x08` | Valid GPS fix |
| `s & ~0x0B` | Unknown bits preserved alongside the original flags. Six sample and six stream envelopes contain `0x04`. |
| `p` | Two signed decimal integers in latitude, longitude order. Divide each by 100,000 and enforce geographic bounds. Publish decoded coordinates only when the GPS bit is set. |

The raw battery codes and their full-precision estimates remain available for logic. The three rounded display values support the 12-bit full-scale conversion. They cannot establish the vendor's complete battery transfer function or measure remaining life. For portal comparison, round the estimate to the nearest whole percent, with ties rounded upward.

## Exact portal comparisons

| Unit | Raw clock | Raw battery | Flags | UTC observation | Portal time in Regina (UTC−06:00) | Display battery | Moving | Low | GPS | Latitude | Longitude |
| --- | --- | ---: | ---: | --- | --- | ---: | --- | --- | --- | ---: | ---: |
| BX40471 | `6ADA16E0` | 3094 | 8 | 2026-10-22T14:00:00Z | 2026-10-22 08:00:00 | 76% | No | No | Yes | 50.42719 | −104.56695 |
| BX41085 | `6AD8D76C` | 2583 | 9 | 2026-10-21T15:17:00Z | 2026-10-21 09:17:00 | 63% | Yes | No | Yes | 50.43083 | −104.66817 |
| BX47068 | `6AE4B4B0` | 573 | 10 | 2026-10-30T15:16:00Z | 2026-10-30 09:16:00 | 14% | No | Yes | Yes | 50.46073 | −104.67404 |

The verification uses `America/Regina`, which stays at UTC−06:00 during the supplied period and the Toronto fall-back. All 300 standalone messages identify one of the 20 BX inventory units. The telemetry stream supplies 313 envelopes with the four-field shape, covering 308 distinct observations for the same 20 units. Eight distinct stream observations are absent from the sample. The stream adds the flag combination `11`, which means moving, low battery and valid fix. [Portal readout](../vendor/quiet-fleet/new_hardware/portal_readout.csv) · [Independent data audit](data-quality.md#bx-reference-comparison)

## Ingest and support policy

- Malformed JSON, duplicate keys, invalid field types or bounds, and non-BX inventory serials invalidate only their own batch elements. Hex case and leading zeroes, coordinate spacing, and JSON key order can vary between retries. Semantic identity follows the exact serial, normalized observation instant, raw battery and coordinate codes, flags, and extra fields. The first eligible original receipt supplies evidence and determines `last_heard_at`. Untrusted clock-ahead frames contribute contact only.
- An installed BX unit reports on a nominal daily cycle. Its calibrated late boundary is strictly beyond 26 hours from the latest credible observation. A timely no-fix report updates contact and battery evidence. Valid fix evidence keeps its own observation time and remains unchanged by the no-fix report.
- The low flag opens a `battery_low` episode with technician ownership. A later observation must clear the flag and reach at least 20% estimated charge to dismiss the episode. A same-clock clear cannot override a low flag. The supplied history contains no labeled example of this recovery, so the hysteresis is provisional. A small unflagged percentage alone does not open a BX episode.
- Stock and pre-installation reports can provide real contact evidence. In-service BX reporting and battery diagnoses require an effective roster assignment and an eligible BX observation at or after installation. Date-only roster entries use the existing coarse UTC date convention. Prolonged silence beyond the 26-hour allowance and one further daily cycle warrants support verification when scheduled work is at risk. [Threshold register](../config/rules.json) · [Support priority policy](decisions.md#p07-support-queue)

## Reproduce the verification

From the checkout root, regenerate the independent corpus and portal audit into an ignored local directory.

```bash
.venv/bin/python -B scripts/audit_data.py --data "$PWD/data" --bx-dir "$PWD/vendor/quiet-fleet/new_hardware" --reports-dir "$PWD/.local/p08/audit" --docs-dir "$PWD/.local/p08/audit"
```

Run the decoder and HTTP integration tests with Python 3.12.

```bash
.venv/bin/python -B -m unittest discover -s tests -p 'test_bx.py' -v
.venv/bin/python -B -m unittest discover -s tests -v
```
