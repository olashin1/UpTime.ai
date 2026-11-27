import sentry_sdk

from app.db import get_session
from app.models import Product


def similar_products(product_id: int) -> list[dict]:
    """Widget under the product page. Never allowed to break the page."""
    try:
        with get_session() as session:
            candidates = Product.co_purchased(session, product_id)
        ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
        return ranked[:6]
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        return []
