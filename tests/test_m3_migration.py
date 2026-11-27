"""Existing M2 orders must survive the additive marketplace migration."""
from sqlalchemy import create_engine, select

from store import create_app
from store.db import get_session
from store.models import Order


def test_marketplace_migration_preserves_existing_orders(tmp_path):
    path = tmp_path / "m2.db"
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql('''CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_name VARCHAR(120) NOT NULL, customer_email VARCHAR(160) NOT NULL,
            shipping_address TEXT NOT NULL, fulfillment_method VARCHAR(30) NOT NULL,
            subtotal_cents INTEGER NOT NULL, shipping_cents INTEGER NOT NULL,
            total_cents INTEGER NOT NULL, payment_reference VARCHAR(80) NOT NULL,
            status VARCHAR(30) NOT NULL, created_at DATETIME NOT NULL)''')
        conn.exec_driver_sql("""INSERT INTO orders VALUES
            (8, 'M2 buyer', 'm2@example.com', 'M2 Street', 'express',
             10000, 19900, 29900, 'pay_old', 'confirmed', '2026-11-20 14:00:00')""")
    engine.dispose()

    for _ in range(2):
        app = create_app({"TESTING": True, "DATABASE": str(path)})
        try:
            with app.app_context():
                order = get_session().scalar(select(Order))
                assert order.id == 8
                assert order.order_source == "storefront"
                assert order.marketplace_order_id is None
                assert order.fulfillment_method == "express"
                assert order.total_cents == 29900
                assert order.payment_reference == "pay_old"
        finally:
            app.extensions["store_engine"].dispose()
