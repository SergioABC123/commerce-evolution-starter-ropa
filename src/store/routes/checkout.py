from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..db import get_session
from ..fulfillment import OPTIONS, STANDARD, get_option, validate_address
from ..models import Order, OrderItem
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

    for line in lines:
        if line.quantity > line.product.stock_quantity:
            flash(f"Not enough stock for {line.product.name}.", "error")
            return redirect(url_for("cart.view_cart"))

    subtotal = sum(line.line_total_cents for line in lines)
    total = subtotal + option.cost_cents

    try:
        payment_reference = FakePaymentProcessor().charge(total, payment_token)
    except PaymentDeclined:
        flash("Payment was declined. Try a different test token.", "error")
        return redirect(retry_url)

    order = Order(
        customer_name=customer_name,
        customer_email=customer_email,
        shipping_address=shipping_address,
        subtotal_cents=subtotal,
        fulfillment_method=option.code,
        shipping_cents=option.cost_cents,
        total_cents=total,
        payment_reference=payment_reference,
        status="confirmed",
    )
    db.add(order)
    db.flush()

    for line in lines:
        order.items.append(
            OrderItem(
                product_id=line.product.id,
                sku=line.product.sku,
                product_name=line.product.name,
                unit_price_cents=line.product.price_cents,
                quantity=line.quantity,
            )
        )
        line.product.stock_quantity -= line.quantity

    db.commit()
    session["cart"] = {}
    flash("Order placed successfully.", "success")
    return redirect(url_for("orders.order_detail", order_id=order.id))
