#!/usr/bin/env python3
"""Generate reproducible, labelled order snapshots for business acceptance tests.

The output is synthetic by design. It contains no customer or platform data and
must not be presented as production traffic.
"""
import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


CN_TZ = timezone(timedelta(hours=8))
SCENARIOS = (
    ("NORMAL", 80),
    ("SHIPMENT_TIMEOUT", 5),
    ("HIGH_RISK_ORDER", 4),
    ("INVENTORY_SHORTAGE", 3),
    ("REFUND_TIMEOUT", 3),
    ("DUPLICATE_PAYMENT", 2),
    ("MULTIPLE_EXCEPTIONS", 3),
)
FIELDS = (
    "eventId", "orderId", "status", "paidAt", "shippedAt", "refundRequestedAt",
    "amount", "currency", "quantity", "stock", "riskScore", "duplicatePayment",
    "customer", "sourcePlatform", "storeId", "expectedExceptionTypes",
)


def iso(value):
    return value.replace(microsecond=0).isoformat() if value else ""


def build_order(index, scenario, stamp, rng):
    order_id = f"SYN-{stamp:%Y%m%d}-{index:06d}"
    hours_before = rng.randint(1, 36)
    paid_at = stamp - timedelta(hours=hours_before)
    row = {
        "eventId": f"synthetic:{stamp:%Y%m%d}:{index}:v1",
        "orderId": order_id,
        "status": "SHIPPED",
        "paidAt": iso(paid_at),
        "shippedAt": iso(paid_at + timedelta(hours=rng.randint(1, min(12, hours_before)))),
        "refundRequestedAt": "",
        "amount": f"{rng.randint(29, 9999)}.{rng.randint(0, 99):02d}",
        "currency": "CNY",
        "quantity": rng.randint(1, 3),
        "stock": rng.randint(5, 30),
        "riskScore": rng.randint(1, 50),
        "duplicatePayment": "false",
        "customer": f"客户-{index % 97:02d}*",
        "sourcePlatform": "ERP_SANDBOX",
        "storeId": f"STORE-{index % 3 + 1:02d}",
        "expectedExceptionTypes": "",
    }
    expected = []
    if scenario == "SHIPMENT_TIMEOUT":
        row.update(status="PAID", paidAt=iso(stamp - timedelta(hours=72)), shippedAt="")
        expected.append("SHIPMENT_TIMEOUT")
    elif scenario == "HIGH_RISK_ORDER":
        row.update(status="PAID", shippedAt="", riskScore=rng.randint(80, 99))
        expected.append("HIGH_RISK_ORDER")
    elif scenario == "INVENTORY_SHORTAGE":
        row.update(status="PAID", shippedAt="", quantity=6, stock=2)
        expected.append("INVENTORY_SHORTAGE")
    elif scenario == "REFUND_TIMEOUT":
        row.update(status="REFUNDING", shippedAt="", refundRequestedAt=iso(stamp - timedelta(hours=36)))
        expected.append("REFUND_TIMEOUT")
    elif scenario == "DUPLICATE_PAYMENT":
        row.update(status="PAID", shippedAt="", duplicatePayment="true")
        expected.append("DUPLICATE_PAYMENT")
    elif scenario == "MULTIPLE_EXCEPTIONS":
        row.update(
            status="PAID", paidAt=iso(stamp - timedelta(hours=72)), shippedAt="",
            quantity=6, stock=2, riskScore=95,
        )
        expected.extend(("SHIPMENT_TIMEOUT", "HIGH_RISK_ORDER", "INVENTORY_SHORTAGE"))
    row["expectedExceptionTypes"] = "|".join(expected)
    return row


def main():
    parser = argparse.ArgumentParser(description="Generate labelled synthetic order snapshots")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--as-of", default=None, help="ISO timestamp; fixes all relative business times")
    parser.add_argument("--output", type=Path, default=Path("work/synthetic-orders.csv"))
    args = parser.parse_args()
    if not 1 <= args.count <= 1_000_000:
        raise SystemExit("--count must be between 1 and 1000000")
    stamp = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(CN_TZ)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=CN_TZ)
    rng = random.Random(args.seed)
    names = [name for name, _ in SCENARIOS]
    weights = [weight for _, weight in SCENARIOS]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts = {name: 0 for name in names}
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for index, scenario in enumerate(rng.choices(names, weights=weights, k=args.count), start=1):
            writer.writerow(build_order(index, scenario, stamp, rng))
            counts[scenario] += 1
    print(f"generated={args.count} output={args.output} seed={args.seed} as_of={stamp.isoformat()}")
    print(" ".join(f"{name}={count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
