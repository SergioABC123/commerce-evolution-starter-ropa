"""Regression checks after storefront checkout delegates to the shared service."""
from sqlalchemy import select

from store.db import get_session
from store.models import Order, Product
from store.payments import FakePaymentProcessor


def test_storefront_still_charges_once_and_persists_order(client, app, first_product_id, monkeypatch):
    amounts = []
    old_charge = FakePaymentProcessor.charge

    def tracked(self, amount, token):
        amounts.append(amount)
        return old_charge(self, amount, token)

    monkeypatch.setattr(FakePaymentProcessor, "charge", tracked)
    client.post(f"/cart/add/{first_product_id}")
    response = client.post("/checkout", data={
        "customer_name": "Web Customer", "customer_email": "web@example.com",
        "shipping_address": "", "fulfillment_method": "pickup", "payment_token": "tok_success",
    }, follow_redirects=True)
    assert b"Order #1" in response.data
    assert amounts == [10000]
    with app.app_context():
        db = get_session()
        order = db.scalar(select(Order))
        assert order.order_source == "storefront"
        assert order.marketplace_order_id is None
        assert order.fulfillment_method == "pickup"
        assert order.total_cents == 10000
        assert db.get(Product, first_product_id).stock_quantity == 4
