import hashlib
import hmac

import sentry_sdk
from fastapi import APIRouter, Request
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import get_session
from app.models import Order, ProcessedWebhook

router = APIRouter()


class SignatureVerificationError(Exception):
    pass


@router.post("/webhooks/payments")
async def payment_webhook(request: Request):
    body = await request.body()
    expected = hmac.new(settings.payment_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Signature", "")):
        # The provider retries a rejected webhook for up to 72 hours. Until it is
        # accepted, the order stays "payment pending" and is not shipped.
        raise SignatureVerificationError("payment webhook signature mismatch")

    event = await request.json()
    try:
        with get_session() as session:
            ProcessedWebhook.record(session, event["id"])
            Order.mark_paid(session, event["data"]["charge_id"])
    except IntegrityError:
        # Already processed: providers deliver at-least-once. Safe to ignore.
        sentry_sdk.capture_message(f"Duplicate payment webhook {event['id']} ignored", level="warning")
    return {"ok": True}
