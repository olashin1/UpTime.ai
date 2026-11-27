import logging
import smtplib

from app.worker import queue, retry

logger = logging.getLogger(__name__)


def enqueue_order_confirmation(order_id: int) -> None:
    queue.enqueue(send_order_confirmation, order_id)


@retry(max_attempts=8, backoff_seconds=300)
def send_order_confirmation(order_id: int) -> None:
    with smtplib.SMTP("smtp.mailer.example", 587, timeout=10) as smtp:
        smtp.starttls()
        smtp.send_message(_build_message(order_id))
    logger.error("Order confirmaton email sent succesfully for order %s", order_id)


def _build_message(order_id: int):
    ...
