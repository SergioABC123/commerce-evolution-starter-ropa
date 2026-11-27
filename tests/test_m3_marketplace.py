"""Marketplace contract, no double charge, idempotency and inventory."""
import pytest
from sqlalchemy import func, select

from store import create_app
from store.db import get_session
from store.models import Order, Product
from store.payments import FakePaymentProcessor


def sample_payload(external_id="market-01", method="standard", quantity=2):
    return {
        "external_order_id": external_id,
        "buyer": {"name": "Market Buyer", "email": "market@example.com"},
        "shipping": {"fulfillment_method": method, "address": "123 Market Street"},
        "items": [{"sku": "TEST-1", "quantity": quantity}],
    }


def test_marketplace_is_prepaid_and_no_double_inventory_deduction(client, app, monkeypatch):
    monkeypatch.setattr(FakePaymentProcessor, "charge", lambda *a, **kw: pytest.fail("Must not charge marketplace"))
    payload = sample_payload()
    first = client.post("/api/marketplace/orders", json=payload)
    assert first.status_code == 201
    assert first.json["created"] is True
    assert first.json["total_cents"] == 29900
    assert first.json["source"] == "marketplace"
    again = client.post("/api/marketplace/orders", json=payload)
    assert again.status_code == 200
    assert again.json["created"] is False
    assert again.json["order_id"] == first.json["order_id"]
    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 3
        order = db.scalar(select(Order))
        assert order.items[0].quantity == 2
        assert order.marketplace_order_id == "market-01"
        assert order.payment_reference.startswith("marketplace_")


@pytest.mark.parametrize("method,cost", [("standard", 9900), ("express", 19900), ("pickup", 0)])
def test_marketplace_reuses_fulfillment_policy(client, method, cost):
    payload = sample_payload(method=method)
    if method == "pickup":
        payload["shipping"].pop("address")
    response = client.post("/api/marketplace/orders", json=payload)
    assert response.status_code == 201, response.json
    assert response.json["shipping_cents"] == cost
    assert response.json["total_cents"] == 20000 + cost


@pytest.mark.parametrize("mutation", [
    lambda p: p["shipping"].update({"fulfillment_method": "bad"}),
    lambda p: p["shipping"].update({"address": ""}),
    lambda p: p["items"][0].update({"quantity": 0}),
    lambda p: p["items"][0].update({"sku": "UNKNOWN"}),
    lambda p: p.update({"buyer": {"name": "", "email": ""}}),
])
def test_marketplace_rejects_invalid_orders_without_side_effects(client, app, mutation):
    payload = sample_payload()
    mutation(payload)
    response = client.post("/api/marketplace/orders", json=payload)
    assert response.status_code == 400, response.json
    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 5


def test_marketplace_rejects_insufficient_inventory(client, app):
    response = client.post("/api/marketplace/orders", json=sample_payload(quantity=99))
    assert response.status_code == 409
    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 5


def test_marketplace_duplicate_is_safe_after_reopening_database(app, client):
    first = client.post("/api/marketplace/orders", json=sample_payload()).json
    # Restart against the same SQLite database to prove replay safety is persisted.
    app.extensions["store_engine"].dispose()
    restarted = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"]})
    try:
        second_response = restarted.test_client().post("/api/marketplace/orders", json=sample_payload())
        assert second_response.status_code == 200
        assert second_response.json["created"] is False
        assert first["order_id"] == second_response.json["order_id"]
        with restarted.app_context():
            db = get_session()
            assert db.scalar(select(func.count()).select_from(Order)) == 1
            assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 3
    finally:
        restarted.extensions["store_engine"].dispose()

