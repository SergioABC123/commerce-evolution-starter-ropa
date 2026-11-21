from sqlalchemy import create_engine, select

from store import create_app
from store.db import get_session
from store.models import Order, OrderItem, Product


def test_m1_database_is_upgraded_without_losing_data(tmp_path):
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    # Reconstruct the M1 orders table (before fulfillment_method existed).
    with engine.begin() as conn:
        conn.exec_driver_sql('''CREATE TABLE orders (
            id INTEGER PRIMARY KEY, customer_name VARCHAR(120) NOT NULL,
            customer_email VARCHAR(160) NOT NULL, shipping_address TEXT NOT NULL,
            subtotal_cents INTEGER NOT NULL, shipping_cents INTEGER NOT NULL,
            total_cents INTEGER NOT NULL, payment_reference VARCHAR(80) NOT NULL,
            status VARCHAR(30) NOT NULL, created_at DATETIME NOT NULL)''')
        Product.__table__.create(conn)
        OrderItem.__table__.create(conn)
        conn.exec_driver_sql("INSERT INTO products VALUES (1,'LEGACY','Old product','Old',10000,4,'/static/images/mug.svg',1)")
        conn.exec_driver_sql("INSERT INTO orders VALUES (7,'Legacy customer','test@example.com','Old address',10000,9900,19900,'pay_old','confirmed','2026-01-01 12:00:00')")
        conn.exec_driver_sql("INSERT INTO order_items VALUES (1,7,1,'LEGACY','Old product',10000,1)")
    engine.dispose()

    config = {"TESTING": True, "DATABASE": str(path)}
    for _ in range(2):  # repeated initialization must be safe
        app = create_app(config)
        try:
            with app.app_context():
                db = get_session()
                order = db.scalar(select(Order))
                assert order.id == 7
                assert order.fulfillment_method == "standard"
                assert order.shipping_address == "Old address"
                assert order.shipping_cents == 9900
                assert order.total_cents == 19900
                assert order.payment_reference == "pay_old"
                assert order.items[0].sku == "LEGACY"
                assert db.get(Product, 1).stock_quantity == 4
        finally:
            app.extensions["store_engine"].dispose()
