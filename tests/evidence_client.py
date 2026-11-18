"""Check synthetic HTTP answers against the wire contract and their source receipts."""

import json
import unittest
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from math import isfinite

from fastapi.testclient import TestClient


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CAUSES = {
    "none", "parked_normal", "sleeping_by_design", "cold_weather", "planned_downtime",
    "coverage_gap", "carrier_outage", "power_loss", "camera_fault", "plan_paused",
    "device_swapped", "battery_low", "unknown",
}


class AuditedClient(TestClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._delivered = defaultdict(set)
        self._check = unittest.TestCase()

    def request(self, method, url, *args, **kwargs):
        response = super().request(method, url, *args, **kwargs)
        if response.status_code != 200:
            return response
        path = response.request.url.path
        if method.upper() == "POST" and path == "/ingest":
            self._remember_receipts(json.loads(response.request.content)["events"])
        if method.upper() == "GET" and (path == "/triage" or path.endswith("/status")):
            self._audit_response(path, response.request.url.params["at"], response.json())
        return response

    def _remember_receipts(self, events):
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("event_id"), str):
                continue
            raw_receipt = event.get("received_at")
            if not isinstance(raw_receipt, str):
                continue
            try:
                receipt = datetime.fromisoformat(raw_receipt)
            except ValueError:
                continue
            if receipt.utcoffset() is not None:
                self._delivered[event["event_id"]].add(receipt)

    def _audit_response(self, path, at, body):
        check = self._check
        cutoff = datetime.fromisoformat(at)
        check.assertTrue(body["at"].endswith("Z"))
        check.assertEqual(datetime.fromisoformat(body["at"]), cutoff)
        if path != "/triage":
            check.assertEqual(set(body), {
                "serial", "asset_id", "at", "state", "likely_cause", "confidence",
                "last_heard_at", "reasons", "evidence",
            })
            check.assertIn(body["state"], {"reporting", "quiet_expected", "needs_action", "unknown"})
            check.assertIn(type(body["confidence"]), (int, float))
            check.assertTrue(isfinite(body["confidence"]) and 0 <= body["confidence"] <= 1)
            if body["last_heard_at"] is not None:
                check.assertTrue(body["last_heard_at"].endswith("Z"))
                check.assertLessEqual(datetime.fromisoformat(body["last_heard_at"]), cutoff)
            if body["state"] == "reporting":
                check.assertEqual(body["likely_cause"], "none")
            items = [body]
        else:
            check.assertEqual(set(body), {"at", "items"})
            items = body["items"]
            serials = set()
            for item in items:
                check.assertEqual(set(item), {
                    "item_id", "kind", "serials", "asset_ids", "likely_cause", "who_acts",
                    "next_action", "priority", "reasons", "evidence",
                })
                check.assertIn(item["kind"], {"device", "incident"})
                check.assertIn(item["who_acts"], {"customer", "technician", "carrier", "support", "none"})
                check.assertIn(item["priority"], {"high", "medium", "low"})
                check.assertTrue(item["item_id"].strip() and item["next_action"].strip())
                check.assertTrue(item["evidence"])
                check.assertEqual(len(item["asset_ids"]), len(set(item["asset_ids"])))
                check.assertEqual(len(item["serials"]), len(set(item["serials"])))
                if item["kind"] == "device":
                    check.assertEqual(len(item["serials"]), 1)
                else:
                    check.assertGreaterEqual(len(item["serials"]), 2)
                check.assertTrue(serials.isdisjoint(item["serials"]))
                serials.update(item["serials"])

        cutoff_us = (cutoff - _EPOCH) // timedelta(microseconds=1)
        store = self.app.state.runtime.store
        evidence = set()
        for item in items:
            check.assertIn(item["likely_cause"], _CAUSES)
            check.assertIsInstance(item["reasons"], list)
            check.assertTrue(item["reasons"] and all(isinstance(reason, str) and reason.strip() for reason in item["reasons"]))
            check.assertIsInstance(item["evidence"], list)
            check.assertEqual(len(item["evidence"]), len(set(item["evidence"])))
            evidence.update(item["evidence"])
        for event_id in evidence:
            check.assertIsInstance(event_id, str)
            eligible_us = {
                (receipt - _EPOCH) // timedelta(microseconds=1)
                for receipt in self._delivered[event_id] if receipt <= cutoff
            }
            check.assertTrue(eligible_us, f"{path} at {at} cited an undelivered or future event ID {event_id!r}")
            check.assertTrue(
                any(row.event_id == event_id and row.received_us in eligible_us
                    for row in store.receipts_for(event_id, cutoff_us)),
                f"{path} at {at} cited an uncommitted event ID {event_id!r}",
            )
