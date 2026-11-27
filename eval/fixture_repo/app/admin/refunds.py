from fastapi import APIRouter, Depends

from app import payments
from app.auth import require_staff
from app.db import get_session
from app.models import Order

router = APIRouter(prefix="/admin")


@router.post("/orders/{order_id}/refund")
def refund_order(order_id: int, staff=Depends(require_staff)):
    """Support agents issue refunds from the admin console."""
    with get_session() as session:
        order = Order.get(session, order_id)
        payments.refund(order.charge_id, order.total)
        order.mark_refunded(session)
    return {"refunded": True}
