from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import get_session
from app.models import Order

router = APIRouter()


@router.get("/orders")
def list_orders(page: int = 1, user=Depends(get_current_user)):
    with get_session() as session:
        orders = Order.for_user(session, user.id, page=page)
    newest = orders[0]
    return {"orders": [o.to_dict() for o in orders], "last_order_at": newest.created_at}
