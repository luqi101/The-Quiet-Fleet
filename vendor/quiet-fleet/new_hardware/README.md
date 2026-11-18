# New hardware: BX-series

Twenty BX-1 trackers joined Regina's trailers on Oct 16. The vendor didn't
send documentation.

- `bx_raw_messages.txt`: 300 raw messages, one per line, exactly as the
  devices sent them.
- `portal_readout.csv`: what the vendor's web portal shows for 3 of those
  messages. The portal displays times in the depot's local time.

The same messages also arrive through `/ingest` (the exam sends newer ones) as events of type
`bx_raw`, with only `event_id`, `received_at` and `raw`. There is no `serial`
or `device_time` field; anything you need is inside `raw`.

`devices.csv` lists the BX units (family `BX`) and the trailers they're on.

This part is optional (10 points). If you skip it, say so in Form 3.
