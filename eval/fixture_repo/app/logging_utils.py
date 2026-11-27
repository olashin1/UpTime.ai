import json
import logging

logger = logging.getLogger("orders")


def log_order_event(event: str, order) -> None:
    payload = {"event": event, "order_id": order.id, "total": order.total}
    logger.info("order event: %s" % json.dumps(payload), order.id)
