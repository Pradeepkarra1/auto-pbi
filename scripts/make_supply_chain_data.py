"""Generate realistic supply-chain order-line data for the example dashboard.

Deterministic (seeded) so the example is reproducible:
~3,600 order lines across 2024-01 to 2025-09 with realistic noise —
late deliveries, short shipments, carrier/warehouse/category mix.

    .venv/bin/python scripts/make_supply_chain_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "examples" / "supply-chain" / "data" / "shipments.csv"

WAREHOUSES = ["Dallas TX", "Chicago IL", "Atlanta GA", "Ontario CA"]
CARRIERS = ["FedEx", "UPS", "XPO"]
CATEGORIES = ["Electronics", "Apparel", "Home Goods", "Industrial"]
UNIT_PRICE = {"Electronics": 85.0, "Apparel": 32.0, "Home Goods": 48.0, "Industrial": 120.0}


def main() -> None:
    rng = random.Random(42)
    start = date(2024, 1, 1)
    end = date(2025, 9, 27)
    span = (end - start).days

    rows: list[dict] = []
    order_id = 10000
    for _ in range(3600):
        order_id += 1
        order_date = start + timedelta(days=rng.randint(0, span))
        category = rng.choices(CATEGORIES, weights=[3, 3, 2, 2])[0]
        warehouse = rng.choice(WAREHOUSES)
        carrier = rng.choices(CARRIERS, weights=[4, 4, 2])[0]
        ordered_qty = rng.randint(5, 120)

        # forecast is roughly right, with noise
        forecast_qty = max(1, round(ordered_qty * rng.uniform(0.8, 1.2)))

        promised_date = order_date + timedelta(days=rng.randint(5, 8))
        ship_delay = rng.randint(1, 3)
        if rng.random() < 0.05:  # warehouse delay
            ship_delay += rng.randint(1, 4)
        shipped_date = order_date + timedelta(days=ship_delay)

        transit = rng.randint(1, 3)
        if rng.random() < 0.06:  # carrier delay
            transit += rng.randint(1, 4)
        delivered_date = shipped_date + timedelta(days=transit)

        # short shipments -> backorders
        if rng.random() < 0.04:
            shipped_qty = max(1, round(ordered_qty * rng.uniform(0.6, 0.95)))
        else:
            shipped_qty = ordered_qty
        # small in-transit loss on some lines
        delivered_qty = shipped_qty if rng.random() > 0.03 else max(0, shipped_qty - rng.randint(1, 3))

        lead_time_days = (delivered_date - shipped_date).days
        line_value = round(delivered_qty * UNIT_PRICE[category], 2)

        rows.append({
            "order_id": order_id,
            "order_date": order_date.isoformat(),
            "promised_date": promised_date.isoformat(),
            "shipped_date": shipped_date.isoformat(),
            "delivered_date": delivered_date.isoformat(),
            "warehouse": warehouse,
            "carrier": carrier,
            "product_category": category,
            "ordered_qty": ordered_qty,
            "forecast_qty": forecast_qty,
            "shipped_qty": shipped_qty,
            "delivered_qty": delivered_qty,
            "lead_time_days": lead_time_days,
            "line_value": line_value,
        })

    rows.sort(key=lambda r: (r["order_date"], r["order_id"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
