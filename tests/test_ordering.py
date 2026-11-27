"""Focused tests for the shared ordering service; runnable before HTTP adapters merge."""
from sqlalchemy import func, select

from store.db import get_session
from store.models import Order, Product
from store.ordering import InsufficientStock, OrderRequest, RequestedItem, place_order


def _request(*items):
    return OrderRequest(
        customer_name="Test Buyer", customer_email="buyer@example.com",
        shipping_address="123 Test St", fulfillment_method="standard",
        items=tuple(RequestedItem(sku, qty) for sku, qty in items),
    )


def test_shared_service_places_one_order_and_updates_stock(app):
    with app.app_context():
        db = get_session()
        charged = []
        result = place_order(db, _request(("TEST-1", 2)), lambda total: charged.append(total) or "web_payment")
        assert result.created is True
        assert charged == [29900]
        assert result.order.total_cents == 29900
        assert result.order.items[0].quantity == 2
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 3


def test_shared_service_combines_duplicate_skus(app):
    with app.app_context():
        db = get_session()
        result = place_order(db, _request(("TEST-1", 1), ("TEST-1", 2)), lambda total: "web_payment")
        assert result.order.items[0].quantity == 3
        assert len(result.order.items) == 1
        assert result.order.subtotal_cents == 30000


def test_shared_service_rejects_stock_without_payment(app):
    with app.app_context():
        db = get_session()
        def unexpected_charge(total):
            raise AssertionError("Invalid order must not be charged")
        try:
            place_order(db, _request(("TEST-1", 7)), unexpected_charge)
        except InsufficientStock:
            pass
        else:
            raise AssertionError("Stock check did not reject an invalid request")
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 5
