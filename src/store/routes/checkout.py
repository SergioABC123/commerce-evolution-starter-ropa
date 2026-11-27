from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..db import get_session
from ..fulfillment import OPTIONS, STANDARD, get_option, validate_address
from ..ordering import OrderRequest, OrderingError, RequestedItem, place_order as create_order
from ..payments import FakePaymentProcessor, PaymentDeclined
from .cart import get_cart_lines

bp = Blueprint("checkout", __name__, url_prefix="/checkout")


@bp.get("")
def checkout_form():
    db = get_session()
    lines = get_cart_lines(db)
    if not lines:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart.view_cart"))
    subtotal = sum(line.line_total_cents for line in lines)
    try:
        selected = get_option(request.args.get("fulfillment_method", STANDARD))
    except ValueError:
        selected = get_option(STANDARD)
    return render_template(
        "checkout.html",
        lines=lines,
        subtotal_cents=subtotal,
        options=OPTIONS,
        selected=selected,
        shipping_cents=selected.cost_cents,
        total_cents=subtotal + selected.cost_cents,
    )


@bp.post("")
def place_order():
    db = get_session()
    lines = get_cart_lines(db)
    if not lines:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart.view_cart"))

    customer_name = request.form.get("customer_name", "").strip()
    customer_email = request.form.get("customer_email", "").strip()
    shipping_address = request.form.get("shipping_address", "").strip()
    payment_token = request.form.get("payment_token", "").strip()

    # Missing field preserves the M1 checkout contract; explicit invalid values fail.
    try:
        option = get_option(request.form.get("fulfillment_method", STANDARD))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("checkout.checkout_form"))

    retry_url = url_for("checkout.checkout_form", fulfillment_method=option.code)
    if not all([customer_name, customer_email, payment_token]):
        flash("Please complete all checkout fields.", "error")
        return redirect(retry_url)
    try:
        shipping_address = validate_address(option, shipping_address)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(retry_url)

    # Shared business workflow: only the web adapter authorizes a new charge.
    # The marketplace adapter passes a reference for an already-paid order.
    try:
        result = create_order(
            db,
            OrderRequest(
                customer_name=customer_name,
                customer_email=customer_email,
                shipping_address=shipping_address,
                fulfillment_method=option.code,
                items=tuple(RequestedItem(line.product.sku, line.quantity) for line in lines),
            ),
            lambda amount_cents: FakePaymentProcessor().charge(amount_cents, payment_token),
        )
    except OrderingError as error:
        flash(str(error), "error")
        return redirect(url_for("cart.view_cart") if "Not enough stock" in str(error) else retry_url)
    except PaymentDeclined:
        flash("Payment was declined. Try a different test token.", "error")
        return redirect(retry_url)

    session["cart"] = {}
    flash("Order placed successfully.", "success")
    return redirect(url_for("orders.order_detail", order_id=result.order.id))
