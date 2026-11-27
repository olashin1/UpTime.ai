import httpx
import sentry_sdk
from fastapi import APIRouter

router = APIRouter()


@router.post("/analytics/event")
def track(body: dict):
    try:
        httpx.post("https://collector.analytics.example/e", json=body, timeout=1)
    except httpx.HTTPError as exc:
        sentry_sdk.capture_exception(exc)
    return {"ok": True}
