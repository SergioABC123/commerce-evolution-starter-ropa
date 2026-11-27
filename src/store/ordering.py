"""Shared order placement for the storefront and external marketplace.

Only this module writes order items and decrements inventory. The caller supplies
its own payment-reference factory: the storefront charges its payment gateway,
while the marketplace supplies a reference for a payment completed externally.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .fulfillment import get_option, validate_address
from .models import Order, OrderItem, Product


class OrderingError(ValueError):
    """Invalid order data, including unavailable products."""


class InsufficientStock(OrderingError):
    """An order requests more units than are available."""


@dataclass(frozen=True)
class RequestedItem:
    sku: str
    quantity: int


@dataclass(frozen=True)
class OrderRequest:
    customer_name: str
    customer_email: str
    shipping_address: str
    fulfillment_method: str
    items: tuple[RequestedItem, ...]
    source: str = "storefront"
    marketplace_order_id: str | None = None


@dataclass(frozen=True)
class OrderResult:
    order: Order
    created: bool


def place_order(
    db: Session,
    request: OrderRequest,
    payment_reference_for_total: Callable[[int], str],
) -> OrderResult:
    """Create an order and update stock in a single database transaction.

    Marketplace requests acquire SQLite's write lock *before* checking the
    external ID. This serializes concurrent retries in the demo's SQLite DB.
    The unique index on marketplace_order_id is a second line of defense.

    IMPORTANT: the caller must not execute SQL on this session before a new
    marketplace request reaches this function; BEGIN IMMEDIATE must be first.
    """
    if request.source not in ("storefront", "marketplace"):
        raise OrderingError("Invalid order source.")

    external_id = request.marketplace_order_id
    if request.source == "marketplace":
        if not isinstance(external_id, str) or not external_id.strip() or len(external_id) > 120:
            raise OrderingError("A marketplace order ID of at most 120 characters is required.")
        external_id = external_id.strip()
        # SQLAlchemy opens a logical transaction on connection(); SQLite hasn't
        # started its actual transaction until we explicitly begin it here.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        existing = db.scalar(
            select(Order).where(Order.marketplace_order_id == external_id)
        )
        if existing is not None:
            return OrderResult(existing, created=False)
    elif external_id is not None:
        raise OrderingError("Storefront orders cannot specify a marketplace order ID.")

    customer_name = (request.customer_name or "").strip()
    customer_email = (request.customer_email or "").strip()
    if not customer_name or not customer_email:
        raise OrderingError("Buyer name and email are required.")

    try:
        option = get_option(request.fulfillment_method)
        address = validate_address(option, request.shipping_address or "")
    except ValueError as error:
        raise OrderingError(str(error)) from error

    if not request.items:
        raise OrderingError("An order must contain at least one item.")

    # Combine repeated SKUs, avoiding two independent checks for the same stock.
    quantities: dict[str, int] = {}
    for item in request.items:
        if not isinstance(item.sku, str) or not item.sku.strip():
            raise OrderingError("Each item needs a valid SKU.")
        if isinstance(item.quantity, bool) or not isinstance(item.quantity, int) or item.quantity <= 0:
            raise OrderingError("Item quantities must be positive integers.")
        quantities[item.sku] = quantities.get(item.sku, 0) + item.quantity

    rows: list[tuple[Product, int]] = []
    for sku, quantity in quantities.items():
        product = db.scalar(select(Product).where(Product.sku == sku))
        if product is None or not product.active:
            raise OrderingError(f"Unknown or inactive SKU: {sku}.")
        if quantity > product.stock_quantity:
            raise InsufficientStock(f"Not enough stock for {product.name}.")
        rows.append((product, quantity))

    subtotal = sum(product.price_cents * quantity for product, quantity in rows)
    total = subtotal + option.cost_cents
    # A web order supplies FakePaymentProcessor().charge; the marketplace
    # supplies a reference to a charge made outside this application.
    payment_reference = payment_reference_for_total(total)
    if not payment_reference:
        raise OrderingError("Payment reference is required.")

    order = Order(
        customer_name=customer_name,
        customer_email=customer_email,
        shipping_address=address,
        fulfillment_method=option.code,
        subtotal_cents=subtotal,
        shipping_cents=option.cost_cents,
        total_cents=total,
        payment_reference=payment_reference,
        status="confirmed",
    )
    if request.source == "marketplace":
        order.order_source = "marketplace"
        order.marketplace_order_id = external_id
    db.add(order)
    db.flush()

    for product, quantity in rows:
        order.items.append(
            OrderItem(
                product_id=product.id,
                sku=product.sku,
                product_name=product.name,
                unit_price_cents=product.price_cents,
                quantity=quantity,
            )
        )
        product.stock_quantity -= quantity

    db.commit()
    return OrderResult(order, created=True)
