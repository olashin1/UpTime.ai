import httpx
import sentry_sdk

RATES_URL = "https://rates.shipco.example/v1/quote"
FLAT_RATE = 7.99


def get_rates(address, line_items) -> float:
    try:
        response = httpx.post(
            RATES_URL,
            json={"zip": address.zip, "items": len(line_items)},
            timeout=2,
        )
        response.raise_for_status()
        return response.json()["rate"]
    except httpx.HTTPError as exc:
        # Carrier API is flaky; charge the flat rate and keep the checkout moving.
        sentry_sdk.capture_exception(exc)
        return FLAT_RATE
