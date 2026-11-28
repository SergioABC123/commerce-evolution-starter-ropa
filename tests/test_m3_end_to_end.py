"""Cross-channel end-to-end tests: storefront and marketplace share inventory and orders."""
from sqlalchemy import func, select

from store.db import get_session
from store.models import Order, Product
from store.payments import FakePaymentProcessor


def test_marketplace_and_web_orders_share_inventory(client, app, first_product_id):
    payload = {
        "external_order_id": "external-aggregate-1",
        "buyer": {"name": "Market Buyer", "email": "market@example.com"},
        "shipping": {"fulfillment_method": "pickup"},
        "items": [{"sku": "TEST-1", "quantity": 3}],
    }
    assert client.post("/api/marketplace/orders", json=payload).status_code == 201
    client.post(f"/cart/add/{first_product_id}")
    web = client.post("/checkout", data={
        "customer_name": "Web Buyer", "customer_email": "web@example.com",
        "shipping_address": "123 Web St", "payment_token": "tok_success",
        "fulfillment_method": "standard",
    }, follow_redirects=True)
    assert b"Order #2" in web.data
    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Order)) == 2
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 1

    # Replaying the external ID must not consume the final unit.
    repeated = client.post("/api/marketplace/orders", json=payload)
    assert repeated.status_code == 200
    with app.app_context():
        assert get_session().scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 1


def test_marketplace_depleting_stock_blocks_web_checkout_without_charging(
    client, app, first_product_id, monkeypatch
):
    charges = []
    original_charge = FakePaymentProcessor.charge

    def tracked_charge(self, amount_cents, token):
        charges.append(amount_cents)
        return original_charge(self, amount_cents, token)

    monkeypatch.setattr(FakePaymentProcessor, "charge", tracked_charge)

    # Marketplace consumes all 5 units of TEST-1 without touching FakePaymentProcessor.
    payload = {
        "external_order_id": "external-deplete-1",
        "buyer": {"name": "Bulk Buyer", "email": "bulk@example.com"},
        "shipping": {"fulfillment_method": "express", "address": "500 Market Ave"},
        "items": [{"sku": "TEST-1", "quantity": 5}],
    }
    res = client.post("/api/marketplace/orders", json=payload)
    assert res.status_code == 201
    assert res.json["created"] is True
    assert charges == []

    # A storefront buyer trying to purchase the same SKU must be rejected without charging.
    client.post(f"/cart/add/{first_product_id}")
    web = client.post("/checkout", data={
        "customer_name": "Late Web Buyer", "customer_email": "late@example.com",
        "shipping_address": "789 Oak Rd", "payment_token": "tok_success",
        "fulfillment_method": "standard",
    }, follow_redirects=True)
    assert b"Not enough stock" in web.data
    assert charges == []

    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 0


def test_web_and_marketplace_orders_coexist_in_orders_history(
    client, app, first_product_id, monkeypatch
):
    charges = []
    original_charge = FakePaymentProcessor.charge

    def tracked_charge(self, amount_cents, token):
        charges.append(amount_cents)
        return original_charge(self, amount_cents, token)

    monkeypatch.setattr(FakePaymentProcessor, "charge", tracked_charge)

    # 1. Marketplace order (2 units, express -> 20000 + 19900 = 39900 cents, no local charge)
    market_res = client.post("/api/marketplace/orders", json={
        "external_order_id": "external-history-1",
        "buyer": {"name": "Market Client", "email": "mclient@example.com"},
        "shipping": {"fulfillment_method": "express", "address": "42 Plaza Central"},
        "items": [{"sku": "TEST-1", "quantity": 2}],
    })
    assert market_res.status_code == 201
    assert charges == []

    # 2. Storefront order (1 unit, pickup -> 10000 cents, charged once)
    client.post(f"/cart/add/{first_product_id}")
    web_res = client.post("/checkout", data={
        "customer_name": "Storefront Client", "customer_email": "sclient@example.com",
        "shipping_address": "", "payment_token": "tok_success",
        "fulfillment_method": "pickup",
    }, follow_redirects=True)
    assert web_res.status_code == 200
    assert charges == [10000]

    # 3. Orders page shows both orders and DB retains distinct sources and consistent stock.
    orders_page = client.get("/orders")
    assert orders_page.status_code == 200
    assert b"Market Client" in orders_page.data
    assert b"Storefront Client" in orders_page.data

    with app.app_context():
        db = get_session()
        orders = db.scalars(select(Order).order_by(Order.id)).all()
        assert len(orders) == 2
        assert orders[0].order_source == "marketplace"
        assert orders[0].marketplace_order_id == "external-history-1"
        assert orders[0].payment_reference.startswith("marketplace_")
        assert orders[1].order_source == "storefront"
        assert orders[1].marketplace_order_id is None
        assert orders[1].payment_reference.startswith("pay_")
        assert db.scalar(select(Product).where(Product.sku == "TEST-1")).stock_quantity == 2
