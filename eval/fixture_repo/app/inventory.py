import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def reserve_stock(session, line_items) -> None:
    for item in line_items:
        # Reads then writes without a row lock; two concurrent checkouts can both
        # see the same stock level.
        row = session.execute(
            text("SELECT quantity FROM stock WHERE sku = :sku"), {"sku": item.sku}
        ).one()
        remaining = row.quantity - item.quantity
        session.execute(
            text("UPDATE stock SET quantity = :q WHERE sku = :sku"),
            {"q": remaining, "sku": item.sku},
        )
        if remaining < 0:
            logger.error("Inventory went negative for SKU %s (%s)", item.sku, remaining)
