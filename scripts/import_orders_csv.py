#!/usr/bin/env python3
"""Import a platform/exported CSV after mapping it to the normalized order contract."""
import argparse
import csv
import hashlib
import hmac
import json
import os
import time
import urllib.request
from pathlib import Path


BOOL_TRUE = {"1", "true", "yes", "y"}


def convert(row, source):
    order_id = row["orderId"].strip()
    return {
        "eventId": f"csv:{source}:{order_id}:{hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]}",
        "orderId": order_id,
        "status": row["status"].strip().upper(),
        "paidAt": row.get("paidAt") or None,
        "shippedAt": row.get("shippedAt") or None,
        "refundRequestedAt": row.get("refundRequestedAt") or None,
        "amount": row.get("amount") or "0.00",
        "currency": (row.get("currency") or "CNY").upper(),
        "quantity": int(row.get("quantity") or 1),
        "stock": int(row.get("stock") or 0),
        "riskScore": int(row.get("riskScore") or 0),
        "duplicatePayment": (row.get("duplicatePayment") or "").lower() in BOOL_TRUE,
        "customer": row.get("customer") or None,
        "sourcePlatform": row.get("sourcePlatform") or source,
        "storeId": row.get("storeId") or None,
    }


def send(url, secret, payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Timestamp": timestamp, "X-Signature": signature,
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--source", default="CSV_IMPORT")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/orders/ingest")
    args = parser.parse_args()
    secret = os.environ.get("INBOUND_WEBHOOK_SECRET")
    if not secret:
        raise SystemExit("Set INBOUND_WEBHOOK_SECRET before running this command")
    accepted = duplicates = exceptions = 0
    with args.file.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            result = send(args.url, secret, convert(row, args.source))
            accepted += 1
            duplicates += int(result.get("duplicate", False))
            exceptions += len(result.get("exceptions", []))
    print(json.dumps({"accepted": accepted, "duplicates": duplicates, "exceptions": exceptions}, ensure_ascii=False))


if __name__ == "__main__":
    main()
