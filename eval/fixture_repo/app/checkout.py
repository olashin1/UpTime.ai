import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException

from app import cart, inventory, payments, shipping, tax
from app.auth import get_current_user
from app.db import get_session
from app.logging_utils import log_order_event
from app.models import Order, PromoCode
from app.notifications.email import enqueue_order_confirmation

router = APIRouter()


@router.post("/checkout")
def place_order(body: dict, user=Depends(get_current_user)):
    current_cart = cart.load_cart(user.id, body.get("session_id"))
    line_items = list(current_cart.items())

    subtotal = sum(item.price * item.quantity for item in line_items)
    discount = apply_discount(subtotal, body.get("promo_code"))
    order_tax = tax.calculate(user.address, subtotal - discount)
    shipping_cost = shipping.get_rates(user.address, line_items)
    total = subtotal - discount + order_tax + shipping_cost

    with get_session() as session:
        inventory.reserve_stock(session, line_items)
        charge = payments.charge(user.payment_method_id, total)
        order = Order.create(session, user=user, items=line_items, total=total, charge_id=charge["id"])

    try:
        log_order_event("order_placed", order)
    except Exception as exc:
        # Logging must never fail a paid order.
        sentry_sdk.capture_exception(exc)

    enqueue_order_confirmation(order.id)
    return {"order_id": order.id, "total": total}


def apply_discount(subtotal: float, promo_code: str | None) -> float:
    if not promo_code:
        return 0.0

    with get_session() as session:
        promo = PromoCode.get(session, promo_code)
        if promo is None:
            raise HTTPException(status_code=400, detail="Unknown promo code")
        rules = promo.rules  # JSON column written by the admin promo editor
        return round(subtotal * rules["discount_pct"] / 100, 2)
