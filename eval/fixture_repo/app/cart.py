import redis
import sentry_sdk
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.config import settings
from app.db import get_session
from app.models import Cart

router = APIRouter()
cache = redis.Redis.from_url(settings.redis_url, socket_timeout=0.5)


def load_cart(user_id: int, session_id: str | None):
    """Return the user's cart, or None if there is no cart for this user/session."""
    try:
        cached = cache.get(f"cart:{user_id}")
        if cached:
            return Cart.from_json(cached)
    except redis.RedisError as exc:
        # Cache is an optimization only; fall through to Postgres.
        sentry_sdk.capture_exception(exc)

    with get_session() as session:
        return Cart.for_user(session, user_id, session_id)


@router.get("/cart")
def get_cart(user=Depends(get_current_user)):
    current = load_cart(user.id, None)
    return current.to_dict() if current else {"items": []}


@router.post("/cart/items")
def add_item(body: dict, user=Depends(get_current_user)):
    with get_session() as session:
        Cart.add(session, user.id, body["sku"], body["quantity"])
    return {"ok": True}
