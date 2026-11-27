"""Small HTTP adapter for orders already paid on an external marketplace.

POST /api/marketplace/orders JSON:
{
  "external_order_id": "market-123",
  "buyer": {"name": "Buyer", "email": "buyer@example.com"},
  "shipping": {"fulfillment_method": "standard", "address": "123 Street"},
  "items": [{"sku": "TRND-001", "quantity": 2}]
}
"""
from __future__ import annotations

from hashlib import sha256

from flask import Blueprint, jsonify, request

from ..db import get_session
from ..ordering import InsufficientStock, OrderRequest, OrderingError, RequestedItem, place_order

bp = Blueprint("marketplace", __name__, url_prefix="/api/marketplace")


def _order_json(order, *, created: bool):
    return {
        "order_id": order.id,
        "external_order_id": order.marketplace_order_id,
        "source": order.order_source,
        "fulfillment_method": order.fulfillment_method,
        "subtotal_cents": order.subtotal_cents,
        "shipping_cents": order.shipping_cents,
        "total_cents": order.total_cents,
        "status": order.status,
        "created": created,
    }


@bp.post("/orders")
def import_order():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Expected a JSON object."), 400

    try:
        buyer = payload.get("buyer")
        shipping = payload.get("shipping")
        items = payload.get("items")
        if not isinstance(buyer, dict) or not isinstance(shipping, dict) or not isinstance(items, list):
            raise OrderingError("buyer, shipping and items are required.")
        if not all(isinstance(item, dict) for item in items):
            raise OrderingError("Every item must be an object.")
        external_id = payload.get("external_order_id")
        if not isinstance(external_id, str) or not external_id.strip():
            raise OrderingError("external_order_id is required.")
        if len(external_id.strip()) > 120:
            raise OrderingError("external_order_id must be at most 120 characters.")
        order_request = OrderRequest(
            customer_name=buyer.get("name", ""),
            customer_email=buyer.get("email", ""),
            shipping_address=shipping.get("address", ""),
            fulfillment_method=shipping.get("fulfillment_method", "standard"),
            items=tuple(RequestedItem(sku=item.get("sku"), quantity=item.get("quantity")) for item in items),
            source="marketplace",
            marketplace_order_id=external_id,
        )
        reference = "marketplace_" + sha256(external_id.strip().encode("utf-8")).hexdigest()[:18]
        result = place_order(get_session(), order_request, lambda total: reference)
    except InsufficientStock as error:
        return jsonify(error=str(error)), 409
    except (OrderingError, AttributeError, TypeError) as error:
        return jsonify(error=str(error)), 400

    return jsonify(_order_json(result.order, created=result.created)), (201 if result.created else 200)
