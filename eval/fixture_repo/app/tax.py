import httpx
from fastapi import HTTPException

TAX_URL = "https://tax.internal.acme/v2/quote"


def calculate(address, amount: float) -> float:
    # Tax must be exact for invoicing, so there is deliberately no fallback:
    # if the tax service is down, checkout cannot complete.
    try:
        response = httpx.post(TAX_URL, json={"address": address.dict(), "amount": amount}, timeout=3)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Tax service unavailable") from exc
    return response.json()["tax"]
