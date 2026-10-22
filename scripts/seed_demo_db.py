"""Seed the demo relational database the data specialist queries.

Run with: python -m scripts.seed_demo_db
"""
from __future__ import annotations

from sqlalchemy import MetaData, Table, Column, Integer, String, Float, insert

from app.db.session import get_engine

metadata = MetaData()

customers = Table(
    "customers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("region", String, nullable=False),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("customer_id", Integer, nullable=False),
    Column("amount", Float, nullable=False),
    Column("status", String, nullable=False),
)

_CUSTOMERS = [
    {"id": 1, "name": "Acme Corp", "region": "NA"},
    {"id": 2, "name": "Globex", "region": "EU"},
    {"id": 3, "name": "Initech", "region": "NA"},
    {"id": 4, "name": "Umbrella Inc", "region": "APAC"},
]

_ORDERS = [
    {"id": 1, "customer_id": 1, "amount": 120.50, "status": "paid"},
    {"id": 2, "customer_id": 1, "amount": 75.00, "status": "paid"},
    {"id": 3, "customer_id": 2, "amount": 340.10, "status": "pending"},
    {"id": 4, "customer_id": 3, "amount": 998.00, "status": "paid"},
    {"id": 5, "customer_id": 4, "amount": 42.25, "status": "refunded"},
    {"id": 6, "customer_id": 2, "amount": 156.75, "status": "paid"},
]


def main() -> None:
    engine = get_engine()
    metadata.drop_all(engine)
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(customers), _CUSTOMERS)
        conn.execute(insert(orders), _ORDERS)
    print(f"Seeded {len(_CUSTOMERS)} customers and {len(_ORDERS)} orders.")


if __name__ == "__main__":
    main()
