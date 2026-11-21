import pytest
from sqlalchemy import func, select

from store import create_app
from store.db import get_session
from store.models import Order, Product
from store.payments import FakePaymentProcessor


def checkout(client, product_id, method, address=None, token="tok_success"):
    client.post(f"/cart/add/{product_id}")
    data = {
        "customer_name": "Test Customer", "customer_email": "test@example.com",
        "payment_token": token, "fulfillment_method": method,
        # These client values must never control the amount charged.
        "shipping_cents": "0", "total_cents": "1",
    }
    if address is not None:
        data["shipping_address"] = address
    return client.post("/checkout", data=data, follow_redirects=True)


@pytest.mark.parametrize("method,label,cost,address", [
    ("standard", "Standard Shipping", 9900, "123 Test St"),
    ("express", "Express Shipping", 19900, "123 Test St"),
    ("pickup", "Store Pickup", 0, None),
])
def test_checkout_fulfillment_persists_and_charges_correct_total(
    client, app, first_product_id, monkeypatch, method, label, cost, address
):
    charged = []
    original = FakePaymentProcessor.charge

    def capture(self, amount_cents, token):
        charged.append(amount_cents)
        return original(self, amount_cents, token)

    monkeypatch.setattr(FakePaymentProcessor, "charge", capture)
    result = checkout(client, first_product_id, method, address)
    assert result.status_code == 200
    assert b"Order #1" in result.data
    assert label.encode() in result.data
    assert charged == [10000 + cost]
    with client.session_transaction() as session:
        assert session["cart"] == {}

    # A new app/engine reads the same file: this verifies restart persistence.
    reopened = create_app(dict(app.config))
    try:
        with reopened.app_context():
            db = get_session()
            order = db.scalar(select(Order))
            assert order.fulfillment_method == method
            assert order.shipping_address == (address or "")
            assert order.shipping_cents == cost
            assert order.subtotal_cents == 10000
            assert order.total_cents == 10000 + cost
            assert len(order.items) == 1
            assert order.items[0].quantity == 1
            assert db.get(Product, first_product_id).stock_quantity == 4
        assert label.encode() in reopened.test_client().get("/orders/1").data
        assert label.encode() in reopened.test_client().get("/orders").data
    finally:
        reopened.extensions["store_engine"].dispose()


@pytest.mark.parametrize("method,address,message", [
    ("standard", "", b"Shipping address is required"),
    ("express", "   ", b"Shipping address is required"),
    ("unknown", "123 Test St", b"Invalid fulfillment option"),
    ("", "123 Test St", b"Invalid fulfillment option"),
])
def test_invalid_fulfillment_has_no_side_effects(
    client, app, first_product_id, monkeypatch, method, address, message
):
    def unexpected_charge(*args):
        pytest.fail("Invalid checkout must not attempt a payment")

    monkeypatch.setattr(FakePaymentProcessor, "charge", unexpected_charge)
    assert message in checkout(client, first_product_id, method, address).data
    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.get(Product, first_product_id).stock_quantity == 5
    with client.session_transaction() as session:
        assert session["cart"][str(first_product_id)] == 1


@pytest.mark.parametrize("method,address", [("express", "123 Test St"), ("pickup", None)])
def test_declined_payment_preserves_inventory(client, app, first_product_id, method, address):
    assert b"Payment was declined" in checkout(
        client, first_product_id, method, address, token="tok_fail"
    ).data
    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.get(Product, first_product_id).stock_quantity == 5


def test_checkout_renders_all_options_and_default_total(client, first_product_id):
    client.post(f"/cart/add/{first_product_id}")
    html = client.get("/checkout").data
    for label in (b"Standard Shipping", b"Express Shipping", b"Store Pickup"):
        assert label in html
    assert b'value="standard"' in html
    assert b"$199.00" in html
    express = client.get("/checkout?fulfillment_method=express").data
    assert b"$299.00" in express
