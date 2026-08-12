#!/usr/bin/env python3
"""Black-box acceptance test for auth, idempotency, concurrency and review."""
import concurrent.futures
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("ORDER_API_URL", "http://127.0.0.1:8080")
SECRET = os.environ["INBOUND_WEBHOOK_SECRET"]
INTERNAL_HEADERS = {"X-Internal-Key": os.environ["INTERNAL_API_KEY"]}


def request(method, path, payload=None, headers=None):
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    req = urllib.request.Request(BASE + path, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def signed(payload):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + "/v1/orders/ingest", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Timestamp": timestamp, "X-Signature": signature,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


_, feishu = request("GET", "/feishu/status")
if (feishu.get("webhookConfigured") or feishu.get("bitableConfigured")) and os.environ.get("ALLOW_LIVE_NOTIFICATIONS") != "true":
    raise SystemExit(
        "REFUSED: Feishu is configured. Run acceptance tests in an isolated environment, "
        "or set ALLOW_LIVE_NOTIFICATIONS=true only when test messages are intentional."
    )


run = uuid.uuid4().hex[:10]
protected_reads_tested = os.environ.get("PROTECT_READ_ENDPOINTS", "false").lower() == "true"
production_docs_tested = os.environ.get("ENABLE_API_DOCS", "true").lower() == "false"
base = {"eventId": f"acceptance:{run}:same", "orderId": f"ORD-ACCEPT-{run}", "status": "PAID", "paidAt": "2020-01-01T00:00:00+08:00", "riskScore": 95, "quantity": 1, "stock": 5}
status, first = signed(base)
assert status == 200 and len(first["exceptions"]) == 2 and not first["duplicate"]
status, duplicate = signed(base)
assert status == 200 and duplicate["duplicate"]
changed = {**base, "riskScore": 96}
status, _ = signed(changed)
assert status == 409


def create(index):
    return signed({"eventId": f"acceptance:{run}:{index}", "orderId": f"ORD-ACCEPT-{run}-{index:02d}", "status": "PAID", "riskScore": 99, "quantity": 1, "stock": 5})


with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    results = list(executor.map(create, range(20)))
assert all(status == 200 and len(body["exceptions"]) == 1 for status, body in results)
numbers = [body["exceptions"][0]["exception_no"] for _, body in results]
assert len(numbers) == len(set(numbers))

critical = next(item for item in first["exceptions"] if item["exception_type"] == "HIGH_RISK_ORDER")
shipment = next(item for item in first["exceptions"] if item["exception_type"] == "SHIPMENT_TIMEOUT")
assert critical["_shouldNotify"] and not shipment["_shouldNotify"]
if protected_reads_tested:
    status, _ = request("GET", "/exceptions")
    assert status == 401
    status, _ = request("GET", "/exceptions", headers={"X-API-Key": os.environ["READ_API_KEY"]})
    assert status == 200
if production_docs_tested:
    status, _ = request("GET", "/docs")
    assert status == 404
exception_id = critical["id"]
status, _ = request("POST", f"/exceptions/{exception_id}/review", {"status": "APPROVED", "reviewer": "acceptance-test", "expectedVersion": critical["version"]})
assert status == 401
review_key = os.environ["REVIEW_API_KEY"]
status, reviewed = request("POST", f"/exceptions/{exception_id}/review", {"status": "RESOLVED", "reviewer": "acceptance-test", "note": "verified", "expectedVersion": critical["version"]}, {"X-API-Key": review_key})
assert status == 200 and reviewed["status"] == "RESOLVED"
status, current = request("GET", f"/exceptions/{exception_id}", headers=INTERNAL_HEADERS)
assert status == 200 and current["exception_no"] == reviewed["exception_no"]

recurred = {**base, "eventId": f"acceptance:{run}:recurrence"}
status, recurrence = signed(recurred)
reopened = next(item for item in recurrence["exceptions"] if item["id"] == exception_id)
assert status == 200 and reopened["status"] == "PENDING_REVIEW" and reopened["_reopened"] and reopened["_shouldNotify"]

status, approved = request("POST", f"/exceptions/{exception_id}/review", {"status": "APPROVED", "reviewer": "acceptance-test", "expectedVersion": reopened["version"]}, {"X-API-Key": review_key})
assert status == 200 and approved["status"] == "APPROVED"
status, stale = request("POST", f"/exceptions/{exception_id}/review", {"status": "RESOLVED", "reviewer": "stale-reviewer", "expectedVersion": reopened["version"]}, {"X-API-Key": review_key})
assert status == 409 and stale["detail"]["currentVersion"] == approved["version"]

recovered = {**base, "eventId": f"acceptance:{run}:recovered", "status": "SHIPPED", "shippedAt": "2026-08-12T10:00:00+08:00", "riskScore": 10}
status, recovery = signed(recovered)
assert status == 200 and shipment["id"] in {item["id"] for item in recovery["resolvedExceptions"]}

status, report = request("GET", "/internal/reports/daily", headers=INTERNAL_HEADERS)
assert status == 200 and report["newExceptions"] >= len(numbers)
status, dead = request("GET", "/internal/outbox/dead", headers=INTERNAL_HEADERS)
assert status == 200 and dead["count"] == 0
status, disabled = request("POST", "/internal/notifications/text", {"eventId": f"acceptance:{run}:report", "category": "DAILY_REPORT", "message": "isolated acceptance"}, INTERNAL_HEADERS)
assert status == 200 and not disabled["queued"]
print(json.dumps({"status": "PASS", "run": run, "concurrentExceptions": len(numbers), "uniqueBusinessNumbers": True, "severityNotificationPolicy": True, "protectedReads": protected_reads_tested, "productionDocsDisabled": production_docs_tested, "recurrenceReopened": True, "staleReviewRejected": True, "automaticRecovery": True, "operationsEndpoints": True}))
