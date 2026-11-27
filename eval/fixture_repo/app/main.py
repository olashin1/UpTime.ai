import sentry_sdk
from fastapi import FastAPI, Request

from app import accounts, analytics, auth, cart, checkout, live_tracking, orders, search
from app.admin import reports
from app.config import settings
from app.maintenance import tag_maintenance
from app.webhooks import payment_provider

sentry_sdk.init(environment=settings.environment, traces_sample_rate=0.1)

app = FastAPI(title="acme-shop")


@app.middleware("http")
async def tag_sentry_events(request: Request, call_next):
    # Every event captured while handling a request carries route, method and status.
    sentry_sdk.set_extra("route", request.url.path)
    sentry_sdk.set_extra("method", request.method)
    tag_maintenance()
    try:
        response = await call_next(request)
    except Exception:
        sentry_sdk.set_extra("status_code", 500)
        raise
    sentry_sdk.set_extra("status_code", response.status_code)
    return response


for module in [auth, cart, checkout, search, accounts, orders, analytics, live_tracking, reports, payment_provider]:
    app.include_router(module.router)
