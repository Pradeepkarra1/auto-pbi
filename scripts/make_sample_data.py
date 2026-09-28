"""Generate deterministic sample sales data for the AutoPBI example.

Writes examples/sales/data/sales.csv (clean, analysis-ready).
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
START = date(2024, 1, 1)
DAYS = 730  # 2024-01-01 .. 2025-12-31

REGIONS = ["West", "Central", "East", "South"]
CATEGORIES = {
    "Furniture": [("Ergonomic Chair", 349.0), ("Standing Desk", 599.0),
                  ("Bookshelf", 189.0), ("Filing Cabinet", 229.0)],
    "Office Supplies": [("Notebook Pack", 24.5), ("Pen Set", 18.0),
                        ("Desk Organizer", 42.0), ("Printer Paper", 32.0)],
    "Technology": [("Laptop", 1299.0), ("Monitor 27in", 329.0),
                   ("Wireless Mouse", 49.0), ("Keyboard", 89.0)],
}
CUSTOMERS = [f"Customer {i:03d}" for i in range(1, 61)]

OUT = Path(__file__).resolve().parent.parent / "examples" / "sales" / "data" / "sales.csv"


def main() -> None:
    rng = random.Random(SEED)
    rows = []
    order_id = 1000
    for day in range(DAYS):
        d = START + timedelta(days=day)
        # weekend dip + yearly growth trend + noise
        base = 5 if d.weekday() < 5 else 2
        growth = 1 + (day / DAYS) * 0.6
        n_orders = max(1, int(rng.gauss(base * growth, 1.5)))
        for _ in range(n_orders):
            order_id += 1
            category = rng.choice(list(CATEGORIES))
            product, price = rng.choice(CATEGORIES[category])
            qty = rng.choice([1, 1, 1, 2, 2, 3, 4, 6])
            discount = rng.choice([0.0, 0.0, 0.0, 0.05, 0.10, 0.15, 0.20])
            net = round(qty * price * (1 - discount), 2)
            rows.append({
                "order_id": order_id,
                "order_date": d.isoformat(),
                "customer_name": rng.choice(CUSTOMERS),
                "region": rng.choice(REGIONS),
                "category": category,
                "product_name": product,
                "quantity": qty,
                "unit_price": price,
                "discount_pct": discount,
                "net_revenue": net,
            })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
