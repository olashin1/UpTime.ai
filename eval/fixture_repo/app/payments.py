import time

import httpx
import sentry_sdk

from app.config import settings

PROVIDER_URL = "https://api.payprovider.example/v1"
MAX_ATTEMPTS = 3


class PaymentProviderUnavailable(Exception):
    pass


class CardDeclined(Exception):
    pass


def charge(payment_method_id: str, amount: float):
    """Charge a card. Retries timeouts and rate limits with backoff before giving up."""
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = httpx.post(
                f"{PROVIDER_URL}/charges",
                json={"payment_method": payment_method_id, "amount": int(amount * 100)},
                headers={"Authorization": f"Bearer {settings.payment_api_key}"},
                timeout=10,
            )
            if response.status_code == 402:
                raise CardDeclined(response.json().get("message"))
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_error = exc
            # Report every failed attempt so provider flakiness is visible; the
            # loop retries and most of these recover on the next attempt.
            sentry_sdk.set_extra("payment_attempt", attempt)
            sentry_sdk.capture_exception(exc)
            time.sleep(2 ** attempt)

    raise PaymentProviderUnavailable(f"charge failed after {MAX_ATTEMPTS} attempts") from last_error


def refund(charge_id: str, amount: float):
    # Refunds use a separate restricted key that can only issue refunds.
    response = httpx.post(
        f"{PROVIDER_URL}/refunds",
        json={"charge": charge_id, "amount": int(amount * 100)},
        headers={"Authorization": f"Bearer {settings.payment_refund_key}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
