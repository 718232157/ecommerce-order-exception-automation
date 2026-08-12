#!/usr/bin/env python3
"""Send one normalized order event to the signed ingestion endpoint."""
import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path, help="UTF-8 JSON order file")
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/orders/ingest")
    args = parser.parse_args()
    secret = os.environ.get("INBOUND_WEBHOOK_SECRET")
    if not secret:
        raise SystemExit("Set INBOUND_WEBHOOK_SECRET before running this command")
    payload = json.loads(args.file.read_text(encoding="utf-8"))
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Timestamp": timestamp, "X-Signature": signature},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
    except urllib.error.HTTPError as error:
        print(error.read().decode())
        raise SystemExit(error.code)


if __name__ == "__main__":
    main()
