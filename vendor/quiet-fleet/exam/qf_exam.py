#!/usr/bin/env python3
"""The Quiet Fleet exam tool.

Python 3.10+ standard library only. Runs on Windows, macOS and Linux.

  python exam/qf_exam.py preflight            check your service meets the contract
  python exam/qf_exam.py practice             stream the history and run the 3 practice checkpoints
  python exam/qf_exam.py run SCENARIO.json    run any scenario file (the hidden exam uses this)

Options:
  --url URL         where your service is (default http://localhost:8080)
  --data DIR        the pack's data folder (default: ../data next to this file)
  --persona NAME    support | fleet | scheduler (default: whichever endpoint your service answers)
  --out DIR         where to save every response (default: exam/results)
  --batch N         events per /ingest request (default 5000)

Start your service fresh (empty state) before `practice` or `run`.
"""
import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = timezone.utc

STATES = {"reporting", "quiet_expected", "needs_action", "unknown"}
CAUSES = {"none", "parked_normal", "sleeping_by_design", "cold_weather", "planned_downtime",
          "coverage_gap", "carrier_outage", "power_loss", "camera_fault", "plan_paused",
          "device_swapped", "battery_low", "unknown"}
WHO = {"customer", "technician", "carrier", "support", "none"}
PRIORITY = {"high", "medium", "low"}
PROBLEM = {"no_location", "no_video", "both"}
DECISION = {"swap", "keep", "gap"}
PERSONAS = {
    "support": ("/triage", lambda at, q: {"at": at}),
    "fleet": ("/job-cover", lambda at, q: {"depot": q.get("depot", "MSS"), "at": at, "hours": q.get("hours", 24)}),
    "scheduler": ("/visits", lambda at, q: {"at": at, "days": q.get("days", 2)}),
}
VISIT_CAP = 6
SLOW_SECONDS = 10.0


# ----------------------------------------------------------------------------- time helpers
def parse_ts(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    s = s.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return d.astimezone(UTC)


def iso(d):
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_offset_hours(depot, t):
    """Fixed rules, so no tz database is needed. Regina: UTC-6 all year.
    Mississauga: UTC-4 until DST ends on 2026-11-01 at 06:00 UTC, then UTC-5."""
    if depot == "REG":
        return -6
    return -4 if t < datetime(2026, 11, 1, 6, 0, tzinfo=UTC) else -5


def to_local(depot, t):
    return t + timedelta(hours=local_offset_hours(depot, t))


# ----------------------------------------------------------------------------- output helpers
class Report:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warned = 0

    def ok(self, msg):
        self.passed += 1
        print(f"  PASS  {msg}")

    def fail(self, msg, detail=None):
        self.failed += 1
        print(f"  FAIL  {msg}")
        if detail:
            for line in str(detail).splitlines()[:6]:
                print(f"          {line}")

    def warn(self, msg):
        self.warned += 1
        print(f"  WARN  {msg}")

    def check(self, cond, msg, detail=None):
        if cond:
            self.ok(msg)
        else:
            self.fail(msg, detail)
        return cond


# ----------------------------------------------------------------------------- http
class Service:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def request(self, method, path, params=None, body=None, timeout=60):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {}
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                code = r.status
        except urllib.error.HTTPError as e:
            raw = e.read()
            code = e.code
        except Exception as e:  # connection refused, timeout ...
            return None, None, time.time() - t0, str(e)
        dt = time.time() - t0
        try:
            payload = json.loads(raw.decode() or "null")
        except Exception:
            payload = None
        return code, payload, dt, None

    def wait_healthy(self, seconds=60):
        end = time.time() + seconds
        while time.time() < end:
            code, body, _, _ = self.request("GET", "/health", timeout=5)
            if code == 200:
                return True
            time.sleep(1)
        return False


# ----------------------------------------------------------------------------- data
def data_dir(args):
    d = args.data or os.path.normpath(os.path.join(HERE, "..", "data"))
    if not os.path.isdir(d):
        sys.exit(f"Data folder not found: {d}  (use --data)")
    return d


def read_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_reference(ddir):
    assets = {r["asset_id"]: r for r in read_csv(os.path.join(ddir, "assets.csv"))}
    jobs = read_csv(os.path.join(ddir, "schedule.csv"))
    for j in jobs:
        j["_s"] = parse_ts(j["start"])
        j["_e"] = parse_ts(j["end"])
    return assets, jobs


def iter_events(paths):
    """Yield events from JSONL files, in received order (stable within equal times)."""
    for p in paths:
        with open(p, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rows.sort(key=lambda e: e.get("received_at", ""))
        for e in rows:
            yield e


# ----------------------------------------------------------------------------- validation
def validate_common_item(item, rep, where):
    errs = []
    if not isinstance(item.get("reasons"), list) or not item.get("reasons"):
        errs.append("reasons must be a non-empty list")
    if not isinstance(item.get("evidence"), list):
        errs.append("evidence must be a list of event IDs")
    return errs


def validate_status(body):
    errs = []
    if not isinstance(body, dict):
        return ["response is not a JSON object"]
    for k in ("serial", "asset_id", "at", "state", "likely_cause", "confidence", "last_heard_at", "reasons", "evidence"):
        if k not in body:
            errs.append(f"missing field {k}")
    if body.get("state") not in STATES:
        errs.append(f"state {body.get('state')!r} is not an allowed value")
    if body.get("likely_cause") not in CAUSES:
        errs.append(f"likely_cause {body.get('likely_cause')!r} is not an allowed value")
    c = body.get("confidence")
    if not isinstance(c, (int, float)) or not 0 <= c <= 1:
        errs.append("confidence must be a number from 0 to 1")
    if body.get("state") == "reporting" and body.get("likely_cause") not in ("none", None):
        errs.append("state reporting should use likely_cause none")
    errs += validate_common_item(body, None, "status")
    return errs


def validate_triage(body):
    errs = []
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        return ["response must be an object with an items list"]
    seen = {}
    for i, it in enumerate(body["items"]):
        w = f"items[{i}]"
        if it.get("kind") not in ("device", "incident"):
            errs.append(f"{w}: kind must be device or incident")
        if not isinstance(it.get("serials"), list) or not it.get("serials"):
            errs.append(f"{w}: serials must be a non-empty list")
        if it.get("likely_cause") not in CAUSES:
            errs.append(f"{w}: likely_cause {it.get('likely_cause')!r} not allowed")
        if it.get("who_acts") not in WHO:
            errs.append(f"{w}: who_acts {it.get('who_acts')!r} not allowed")
        if it.get("priority") not in PRIORITY:
            errs.append(f"{w}: priority {it.get('priority')!r} not allowed")
        errs += [f"{w}: {e}" for e in validate_common_item(it, None, w)]
        for s in it.get("serials") or []:
            if s in seen:
                errs.append(f"{s} appears in more than one item ({seen[s]} and {w})")
            seen[s] = w
    return errs


def validate_job_cover(body, q, at, assets, jobs, unavailable):
    errs = []
    if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
        return ["response must be an object with a jobs list"]
    depot = q.get("depot")
    hours = q.get("hours", 24)
    end = at + timedelta(hours=hours)
    by_id = {j["job_id"]: j for j in jobs}
    # asset bookings, updated as swaps are applied
    booked = {}
    for j in jobs:
        booked.setdefault(j["asset_id"], []).append((j["_s"], j["_e"], j["job_id"]))
    listed = set()
    for i, it in enumerate(body["jobs"]):
        w = f"jobs[{i}]"
        jid = it.get("job_id")
        j = by_id.get(jid)
        if not j:
            errs.append(f"{w}: unknown job_id {jid!r}")
            continue
        if jid in listed:
            errs.append(f"{w}: job {jid} listed twice")
        listed.add(jid)
        if j["depot"] != depot or not (at <= j["_s"] < end):
            errs.append(f"{w}: job {jid} is not at {depot} starting in the window")
        if it.get("problem") not in PROBLEM:
            errs.append(f"{w}: problem {it.get('problem')!r} not allowed")
        if it.get("decision") not in DECISION:
            errs.append(f"{w}: decision {it.get('decision')!r} not allowed")
        errs += [f"{w}: {e}" for e in validate_common_item(it, None, w)]
        if it.get("decision") == "swap":
            to = it.get("swap_to")
            a0, a1 = assets.get(j["asset_id"]), assets.get(to)
            if not a1:
                errs.append(f"{w}: swap_to {to!r} is not a known asset")
                continue
            if a1["type"] != a0["type"] or a1["depot"] != a0["depot"]:
                errs.append(f"{w}: swap_to {to} is not the same type and depot as {j['asset_id']}")
            if to in unavailable:
                errs.append(f"{w}: swap_to {to} can't be seen or recorded at this time")
            for s, e, other in booked.get(to, []):
                if s < j["_e"] and j["_s"] < e and other != jid:
                    errs.append(f"{w}: swap_to {to} is busy with {other} during {jid}")
                    break
            booked.setdefault(to, []).append((j["_s"], j["_e"], jid))
        elif it.get("decision") == "gap" and it.get("swap_to") not in (None, ""):
            errs.append(f"{w}: a gap should have swap_to null")
    return errs


def validate_visits(body, q, at, assets):
    errs = []
    if not isinstance(body, dict) or not isinstance(body.get("visits"), list) or not isinstance(body.get("deferred", []), list):
        return ["response must be an object with visits and deferred lists"]
    per_day = {}
    for i, v in enumerate(body["visits"]):
        w = f"visits[{i}]"
        dep = v.get("depot")
        if dep not in ("MSS", "REG"):
            errs.append(f"{w}: depot must be MSS or REG")
            continue
        a = assets.get(v.get("asset_id"))
        if not a:
            errs.append(f"{w}: unknown asset_id {v.get('asset_id')!r}")
        elif a["depot"] != dep:
            errs.append(f"{w}: {v.get('asset_id')} belongs to {a['depot']}, not {dep}")
        try:
            s, e = parse_ts(v.get("start")), parse_ts(v.get("end"))
        except Exception:
            errs.append(f"{w}: start and end must be UTC timestamps")
            continue
        if s <= at:
            errs.append(f"{w}: starts before at")
        if e <= s:
            errs.append(f"{w}: ends before it starts")
        ls, le = to_local(dep, s), to_local(dep, e)
        if ls.weekday() >= 5 or ls.date() != le.date():
            errs.append(f"{w}: must be on one weekday (local)")
        if not (7 * 60 <= ls.hour * 60 + ls.minute and le.hour * 60 + le.minute <= 15 * 60 and le.date() == ls.date()):
            errs.append(f"{w}: must start and end between 07:00 and 15:00 local ({ls:%a %H:%M}-{le:%H:%M})")
        day0 = to_local(dep, at).date()
        days = q.get("days", 2)
        if not (0 <= (ls.date() - day0).days < days):
            errs.append(f"{w}: falls outside the requested days")
        per_day[(dep, ls.date())] = per_day.get((dep, ls.date()), 0) + 1
        if v.get("reason") not in CAUSES:
            errs.append(f"{w}: reason {v.get('reason')!r} not allowed")
        if v.get("priority") not in PRIORITY:
            errs.append(f"{w}: priority {v.get('priority')!r} not allowed")
        errs += [f"{w}: {x}" for x in validate_common_item(v, None, w)]
    for (dep, d), n in per_day.items():
        if n > VISIT_CAP:
            errs.append(f"{n} visits at {dep} on {d} (at most {VISIT_CAP})")
    return errs


# ----------------------------------------------------------------------------- checks
def run_check(c, ctx, rep):
    t = c["type"]
    label = c.get("label") or t
    if t == "status":
        code, body, dt, err = ctx.svc.request("GET", f"/devices/{c['serial']}/status", {"at": ctx.at_s})
        ctx.save(f"status-{c['serial']}", body)
        if code != 200:
            return rep.fail(f"{label}: status for {c['serial']} returned {code or err}")
        problems = validate_status(body)
        if body.get("state") not in c.get("state", STATES):
            problems.append(f"state is {body.get('state')!r}, expected one of {c['state']}")
        if body.get("likely_cause") not in c.get("cause", CAUSES):
            problems.append(f"likely_cause is {body.get('likely_cause')!r}, expected one of {c['cause']}")
        if c.get("evidence_any") and not set(c["evidence_any"]) & set(body.get("evidence") or []):
            problems.append(f"evidence should include at least one of {c['evidence_any']}")
        return rep.check(not problems, f"{label}: {c['serial']}", "\n".join(problems))

    resp = ctx.persona_response(c.get("query", {}))
    if resp is None:
        return None  # not this persona
    body = resp

    if t == "triage_item":
        target = set(c["serials"])
        items = body.get("items", [])
        best, cover = None, 0
        for it in items:
            n = len(target & set(it.get("serials") or []))
            if n > cover:
                best, cover = it, n
        problems = []
        need = c.get("min_cover", 1.0)
        if not best or cover / len(target) < need:
            problems.append(f"one item should cover at least {need:.0%} of {len(target)} devices; best covers {cover}")
        else:
            if best.get("likely_cause") not in c.get("cause", CAUSES):
                problems.append(f"likely_cause is {best.get('likely_cause')!r}, expected one of {c['cause']}")
            if best.get("who_acts") not in c.get("who_acts", WHO):
                problems.append(f"who_acts is {best.get('who_acts')!r}, expected one of {c['who_acts']}")
            if c.get("kind") and best.get("kind") not in c["kind"]:
                problems.append(f"kind is {best.get('kind')!r}, expected one of {c['kind']}")
            if c.get("evidence_any") and not set(c["evidence_any"]) & set(best.get("evidence") or []):
                problems.append(f"evidence should include at least one of {c['evidence_any']}")
            split = [s for it in items if it is not best for s in (it.get("serials") or []) if s in target]
            if split:
                problems.append(f"{len(split)} of these devices also appear in other items, e.g. {split[:3]}")
        return rep.check(not problems, label, "\n".join(problems))

    if t == "triage_excludes":
        hit = [s for it in body.get("items", []) for s in (it.get("serials") or []) if s in set(c["serials"])]
        return rep.check(not hit, label, f"should not be in triage: {hit}")

    if t == "job":
        found = [j for j in body.get("jobs", []) if j.get("job_id") == c["job_id"]]
        problems = []
        if not found:
            problems.append(f"{c['job_id']} should be listed")
        else:
            j = found[0]
            if j.get("problem") not in c.get("problem", PROBLEM):
                problems.append(f"problem is {j.get('problem')!r}, expected one of {c['problem']}")
            if j.get("decision") not in c.get("decision", DECISION):
                problems.append(f"decision is {j.get('decision')!r}, expected one of {c['decision']}")
        return rep.check(not problems, label, "\n".join(problems))

    if t == "jobs_no_swap_or_gap":
        assets_set = set(c["asset_ids"])
        hit = [j.get("job_id") for j in body.get("jobs", [])
               if j.get("asset_id") in assets_set and j.get("decision") in ("swap", "gap")]
        return rep.check(not hit, label, f"these jobs should not be swapped or gapped: {hit[:5]}")

    if t == "jobs_exclude_assets":
        hit = [j.get("job_id") for j in body.get("jobs", []) if j.get("asset_id") in set(c["asset_ids"])]
        return rep.check(not hit, label, f"should not be listed: {hit[:5]}")

    if t == "visit":
        lo, hi = parse_ts(c["between"][0]), parse_ts(c["between"][1])
        ok = []
        for v in body.get("visits", []):
            if v.get("asset_id") != c["asset_id"]:
                continue
            try:
                s = parse_ts(v.get("start"))
            except Exception:
                continue
            if lo <= s < hi and v.get("reason") in c.get("reason", CAUSES):
                ok.append(v)
        return rep.check(bool(ok), label, f"expected a visit for {c['asset_id']} starting {c['between'][0]} to {c['between'][1]} with reason in {c.get('reason')}")

    if t == "visits_exclude":
        hit = [v.get("asset_id") for v in body.get("visits", []) if v.get("asset_id") in set(c["asset_ids"])]
        return rep.check(not hit, label, f"no visit expected for: {sorted(set(hit))}")

    rep.warn(f"unknown check type {t}")


class Context:
    def __init__(self, svc, persona, at, cp, assets, jobs, outdir, rep):
        self.svc, self.persona, self.at, self.cp = svc, persona, at, cp
        self.at_s = iso(at)
        self.assets, self.jobs, self.outdir, self.rep = assets, jobs, outdir, rep
        self.cache = {}

    def save(self, name, body):
        if not self.outdir:
            return
        os.makedirs(self.outdir, exist_ok=True)
        with open(os.path.join(self.outdir, f"{self.cp['id']}-{name}.json"), "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2)

    def persona_response(self, q):
        path, mk = PERSONAS[self.persona]
        params = mk(self.at_s, q)
        key = json.dumps(params, sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        code, body, dt, err = self.svc.request("GET", path, params)
        tag = path.strip("/") + "".join(f"-{k}{v}" for k, v in params.items() if k != "at")
        self.save(tag, body)
        if dt > SLOW_SECONDS:
            self.rep.warn(f"{path} took {dt:.1f}s (aim for under {SLOW_SECONDS:.0f}s)")
        if code != 200:
            self.rep.fail(f"{path} {params} returned {code or err}")
            body = {}
        else:
            if self.persona == "support":
                errs = validate_triage(body)
            elif self.persona == "fleet":
                errs = validate_job_cover(body, params, self.at, self.assets, self.jobs, set(self.cp.get("unavailable_assets", [])))
            else:
                errs = validate_visits(body, params, self.at, self.assets)
            shown = ", ".join(f"{k}={v}" for k, v in params.items() if k != "at")
            self.rep.check(not errs, f"{path}{' ' + shown if shown else ''}: response follows the contract and the rules",
                           "\n".join(errs[:8]) + (f"\n... and {len(errs) - 8} more" if len(errs) > 8 else ""))
        self.cache[key] = body
        return body


def detect_persona(svc, at):
    found = []
    for name, (path, mk) in PERSONAS.items():
        code, _, _, _ = svc.request("GET", path, mk(at, {}), timeout=30)
        if code == 200:
            found.append(name)
    return found


# ----------------------------------------------------------------------------- commands
def cmd_preflight(args):
    svc = Service(args.url)
    rep = Report()
    ddir = data_dir(args)
    print(f"Preflight against {svc.url}\n")
    if not rep.check(svc.wait_healthy(30), "GET /health returns 200 within 30 s"):
        print("\nYour service isn't answering. Start it, then run preflight again.")
        return 1
    first = sorted(glob.glob(os.path.join(ddir, "telemetry", "*.jsonl")))[0]
    batch = []
    for e in iter_events([first]):
        batch.append(e)
        if len(batch) >= 300:
            break
    code, body, dt, err = svc.request("POST", "/ingest", body={"events": batch})
    rep.check(code == 200 and isinstance(body, dict) and isinstance(body.get("accepted"), int),
              "POST /ingest accepts a batch and returns {\"accepted\": n}", f"got {code or err}: {str(body)[:200]}")
    code2, body2, _, err2 = svc.request("POST", "/ingest", body={"events": batch})
    rep.check(code2 == 200, "POST /ingest accepts the same batch twice", f"got {code2 or err2}")
    junk = [{}, {"event_id": "pf-1"}, {"event_id": "pf-2", "type": "position", "serial": "T-00000", "device_time": 12,
                                       "received_at": "not a time", "payload": None},
            {"event_id": "pf-3", "type": "mystery", "serial": batch[0].get("serial"), "device_time": batch[0].get("device_time"),
             "received_at": batch[0].get("received_at"), "payload": {"x": 1}}, batch[0]]
    code3, _, _, err3 = svc.request("POST", "/ingest", body={"events": junk})
    rep.check(code3 == 200, "POST /ingest survives malformed and unknown events in a batch", f"got {code3 or err3}")
    code4, _, _, _ = svc.request("POST", "/ingest", body=b"this is not json")
    if code4 is None or code4 >= 500:
        rep.warn(f"POST /ingest with a body that isn't JSON returned {code4}; a 400 is better than a crash")
    else:
        rep.ok(f"POST /ingest rejects a body that isn't JSON without crashing ({code4})")

    at = max(e["received_at"] for e in batch)
    serial = next(e["serial"] for e in batch if e.get("serial"))
    code, body, dt, err = svc.request("GET", f"/devices/{serial}/status", {"at": at})
    errs = validate_status(body) if code == 200 else [f"returned {code or err}"]
    rep.check(not errs, f"GET /devices/{serial}/status follows the contract", "\n".join(errs))
    code, _, _, err = svc.request("GET", "/devices/ZZ-00000/status", {"at": at})
    rep.check(code == 404, "GET /devices/{unknown}/status returns 404", f"got {code or err}")

    found = detect_persona(svc, at)
    if not rep.check(bool(found), "at least one persona endpoint answers 200 (/triage, /job-cover or /visits)"):
        return finish(rep)
    assets, jobs = load_reference(ddir)
    for p in found:
        ctx = Context(svc, p, parse_ts(at), {"id": "preflight"}, assets, jobs, None, rep)
        ctx.persona_response({})
    path = PERSONAS[found[0]][0]
    bad = {"support": {"at": "yesterday"}, "fleet": {"depot": "MSS", "at": at, "hours": 500},
           "scheduler": {"at": at, "days": 9}}[found[0]]
    code, _, _, _ = svc.request("GET", path, bad)
    if code == 400:
        rep.ok(f"{path} rejects bad parameters with 400")
    else:
        rep.warn(f"{path} with bad parameters {bad} returned {code}; 400 is expected")
    print("\nPreflight sent a few events. Restart your service before running practice.")
    return finish(rep)


def run_scenario(args, scen_path):
    svc = Service(args.url)
    rep = Report()
    ddir = data_dir(args)
    with open(scen_path, encoding="utf-8") as f:
        scen = json.load(f)
    base = os.path.dirname(os.path.abspath(scen_path))
    paths = []
    for pat in scen["streams"]:
        pat = pat.replace("{data}", ddir)
        if not os.path.isabs(pat):
            pat = os.path.join(base, pat)
        paths += sorted(glob.glob(pat))
    if not paths:
        sys.exit("No event files found for this scenario.")
    assets, jobs = load_reference(ddir)
    outdir = args.out or os.path.join(HERE, "results")
    checkpoints = sorted(scen["checkpoints"], key=lambda c: c["at"])
    print(f"{scen.get('name', 'scenario')}: {len(paths)} event files, {len(checkpoints)} checkpoints, service {svc.url}\n")
    if not svc.wait_healthy(60):
        sys.exit("Your service isn't answering GET /health. Start it fresh, then try again.")

    personas = [p for p in (args.persona or "").split(",") if p]
    if any(p not in PERSONAS for p in personas):
        sys.exit("--persona must be support, fleet or scheduler")
    if not personas:
        found = detect_persona(svc, iso(parse_ts(checkpoints[0]["at"]) if checkpoints else datetime.now(UTC)))
        if len(found) != 1:
            sys.exit(f"Found persona endpoints {found or 'none'}; pass --persona support|fleet|scheduler")
        personas = found
    print(f"Persona: {', '.join(personas)}\n")

    sent = 0
    slow = 0
    t_start = time.time()
    batch = []
    cp_i = 0

    def flush():
        nonlocal batch, sent, slow
        if not batch:
            return
        code, body, dt, err = svc.request("POST", "/ingest", body={"events": batch}, timeout=120)
        if code != 200:
            sys.exit(f"\n/ingest failed ({code or err}) after {sent:,} events. Fix it and start again.")
        if dt > SLOW_SECONDS:
            slow += 1
        sent += len(batch)
        batch = []
        print(f"\r  streamed {sent:,} events", end="", flush=True)

    def run_checkpoint(cp):
        print(f"\n\n{cp['id']} at {cp['at']}: {cp.get('title', '')}")
        for i, persona in enumerate(personas):
            ctx = Context(svc, persona, parse_ts(cp["at"]), cp, assets, jobs, outdir, rep)
            for c in cp.get("checks", []):
                if c.get("persona", persona) != persona or (i > 0 and c["type"] == "status"):
                    continue
                run_check(c, ctx, rep)
            for q in cp.get("also_query", {}).get(persona, []):
                ctx.persona_response(q)
        print()

    for e in iter_events(paths):
        r = e.get("received_at", "")
        while cp_i < len(checkpoints) and r > checkpoints[cp_i]["at"]:
            flush()
            run_checkpoint(checkpoints[cp_i])
            cp_i += 1
        batch.append(e)
        if len(batch) >= args.batch:
            flush()
    flush()
    while cp_i < len(checkpoints):
        run_checkpoint(checkpoints[cp_i])
        cp_i += 1
    print(f"\nStreamed {sent:,} events in {time.time() - t_start:.0f}s.")
    if slow:
        rep.warn(f"{slow} /ingest requests took over {SLOW_SECONDS:.0f}s")
    print(f"Responses saved in {outdir}")
    return finish(rep)


def finish(rep):
    total = rep.passed + rep.failed
    print(f"\n{rep.passed}/{total} checks passed" + (f", {rep.warned} warnings" if rep.warned else "") + ".")
    return 0 if rep.failed == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="The Quiet Fleet exam tool")
    ap.add_argument("command", choices=["preflight", "practice", "run"])
    ap.add_argument("scenario", nargs="?")
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--data")
    ap.add_argument("--persona", help="support, fleet or scheduler")
    ap.add_argument("--out")
    ap.add_argument("--batch", type=int, default=5000)
    args = ap.parse_args()
    if args.command == "preflight":
        sys.exit(cmd_preflight(args))
    if args.command == "practice":
        sys.exit(run_scenario(args, os.path.join(HERE, "practice.json")))
    if not args.scenario:
        sys.exit("run needs a scenario file")
    sys.exit(run_scenario(args, args.scenario))


if __name__ == "__main__":
    main()
