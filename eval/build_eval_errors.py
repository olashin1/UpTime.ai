"""Builds eval/eval_errors.json from the case list below.

Labels (severity, escalate) and the rationale for each are written here by hand,
BEFORE any assessor is run. Stack-frame line numbers are looked up from the fixture
source so the frames point at real lines in eval/fixture_repo.

Run: python eval/build_eval_errors.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixture_repo"
BASE_URL = "https://shop.acme.example"

RUBRIC = {
    "severity": {
        "high": "Core user flow (checkout, payment, login/auth, account data) failing or at real risk "
        "for many users, or data loss/corruption, or a security exposure.",
        "medium": "Real defect with limited impact: non-core feature, minority of users, degraded path "
        "with a working fallback, or a background job that needs fixing soon.",
        "low": "Cosmetic, log-message problems, expected client errors, scanner/bot noise, or anything "
        "outside production with no user impact.",
    },
    "escalate": "Page on-call now only if waiting until business hours causes significant user, revenue, "
    "data or security harm.",
}


def frame(path: str, function: str, snippet: str) -> dict:
    """Frame at the single line in `function` (searched from its def) containing `snippet`."""
    lines = (FIXTURE / path).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.lstrip().startswith(
        (f"def {function}(", f"async def {function}(")))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("def ", "async def ", "@"))), len(lines))
    matches = [i + 1 for i in range(start, end) if snippet in lines[i]]
    if len(matches) != 1:
        raise ValueError(f"{path}: snippet {snippet!r} matched {len(matches)} lines")
    return {"filename": path, "module": path[:-3].replace("/", "."), "function": function,
            "lineno": matches[0], "in_app": True, "context_line": lines[matches[0] - 1].strip()}


def lib(module: str, function: str, lineno: int) -> dict:
    return {"filename": module, "module": module, "function": function, "lineno": lineno, "in_app": False}


CHECKOUT = frame("app/checkout.py", "place_order", "current_cart = cart.load_cart(")
CHECKOUT_ITEMS = frame("app/checkout.py", "place_order", "line_items = list(current_cart.items())")
CHECKOUT_DISCOUNT = frame("app/checkout.py", "place_order", "discount = apply_discount(")
CHECKOUT_TAX = frame("app/checkout.py", "place_order", "order_tax = tax.calculate(")
CHECKOUT_SHIP = frame("app/checkout.py", "place_order", "shipping_cost = shipping.get_rates(")
CHECKOUT_STOCK = frame("app/checkout.py", "place_order", "inventory.reserve_stock(session, line_items)")
CHECKOUT_CHARGE = frame("app/checkout.py", "place_order", "charge = payments.charge(")
CHECKOUT_LOG = frame("app/checkout.py", "place_order", 'log_order_event("order_placed", order)')
CHARGE_POST = frame("app/payments.py", "charge", "response = httpx.post(")
CHARGE_STATUS = frame("app/payments.py", "charge", "response.raise_for_status()")
CHARGE_GIVEUP = frame("app/payments.py", "charge", "raise PaymentProviderUnavailable(")
AUTH_DEP = frame("app/auth.py", "get_current_user", 'claims = verify_token(authorization.removeprefix("Bearer "))')
AUTH_VERIFY = frame("app/auth.py", "verify_token", "return jwt.decode(")
AUTH_USER = frame("app/auth.py", "get_current_user", "return User.get(session, claims")

CASES = [
    # ------------------------------------------------------------------ high
    dict(id="E01", name="Null cart in checkout", category="null-pointer",
         severity="high", escalate=True, context_needed=False,
         rationale="Every checkout that hits this crashes with a 500; checkout is the revenue path.",
         title="AttributeError: 'NoneType' object has no attribute 'items'",
         exc=("AttributeError", "'NoneType' object has no attribute 'items'"),
         frames=[CHECKOUT_ITEMS], level="error", env="production",
         req=("POST", "/checkout", 500)),
    dict(id="E02", name="Payment provider down after retries", category="payment",
         severity="high", escalate=True, context_needed=False,
         rationale="Charges fail after all retries, so customers cannot pay.",
         title="PaymentProviderUnavailable: charge failed after 3 attempts",
         exc=("PaymentProviderUnavailable", "charge failed after 3 attempts"),
         frames=[CHECKOUT_CHARGE, CHARGE_GIVEUP], level="error", env="production",
         req=("POST", "/checkout", 500)),
    dict(id="E03", name="DB statement timeout reserving stock", category="db-timeout",
         severity="high", escalate=True, context_needed=False,
         rationale="Statement timeouts inside checkout block orders.",
         title="OperationalError: canceling statement due to statement timeout",
         exc=("sqlalchemy.exc.OperationalError", "(psycopg2.errors.QueryCanceled) canceling statement due to statement timeout"),
         frames=[CHECKOUT_STOCK, frame("app/inventory.py", "reserve_stock", 'text("SELECT quantity FROM stock')],
         level="error", env="production", req=("POST", "/checkout", 500)),
    dict(id="E04", name="JWT signature invalid after key rotation", category="auth",
         severity="high", escalate=True, context_needed=False,
         rationale="Token verification fails for every authenticated request: logged-in users are effectively locked out.",
         title="InvalidSignatureError: Signature verification failed",
         exc=("jwt.exceptions.InvalidSignatureError", "Signature verification failed"),
         frames=[AUTH_DEP, AUTH_VERIFY], level="error", env="production",
         req=("GET", "/cart", 500)),
    dict(id="E05", name="Payment webhook signature mismatch", category="payment",
         severity="high", escalate=True, context_needed=True,
         rationale="Every provider callback is rejected, so paid orders stay 'payment pending' and do not ship; "
         "the code comment shows it keeps happening until fixed.",
         title="SignatureVerificationError: payment webhook signature mismatch",
         exc=("app.webhooks.payment_provider.SignatureVerificationError", "payment webhook signature mismatch"),
         frames=[frame("app/webhooks/payment_provider.py", "payment_webhook", "raise SignatureVerificationError(")],
         level="error", env="production", req=("POST", "/webhooks/payments", 500)),
    dict(id="E06", name="Inventory oversold", category="data-integrity",
         severity="high", escalate=True, context_needed=True,
         rationale="Negative stock means items were sold that do not exist; the read-then-write race in reserve_stock "
         "keeps overselling on every concurrent checkout.",
         title="Inventory went negative for SKU %s (%s)",
         message="Inventory went negative for SKU 4411 (-3)",
         frames=[CHECKOUT_STOCK, frame("app/inventory.py", "reserve_stock", "logger.error(")],
         level="error", env="production", req=("POST", "/checkout", 200)),
    dict(id="E07", name="Promo-code KeyError in checkout", category="null-pointer",
         severity="high", escalate=True, context_needed=False,
         rationale="Any checkout using a promo code from the new editor crashes; promotions drive a large share of orders.",
         title="KeyError: 'discount_pct'",
         exc=("KeyError", "'discount_pct'"),
         frames=[CHECKOUT_DISCOUNT, frame("app/checkout.py", "apply_discount", 'rules["discount_pct"]')],
         level="error", env="production", req=("POST", "/checkout", 500)),
    dict(id="E08", name="Login fails: too many DB connections", category="db",
         severity="high", escalate=True, context_needed=False,
         rationale="Login returns 500 because the database refuses connections.",
         title="OperationalError: FATAL: sorry, too many clients already",
         exc=("sqlalchemy.exc.OperationalError", "(psycopg2.OperationalError) FATAL: sorry, too many clients already"),
         frames=[frame("app/auth.py", "login", "user = User.by_email(")],
         level="error", env="production", req=("POST", "/login", 500)),
    dict(id="E09", name="Connection pool exhausted site-wide", category="db-timeout",
         severity="high", escalate=True, context_needed=False,
         rationale="QueuePool timeouts mean requests across the site are waiting 30s and failing.",
         title="TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00",
         exc=("sqlalchemy.exc.TimeoutError", "QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00"),
         frames=[AUTH_DEP, AUTH_USER], level="error", env="production",
         req=("GET", "/orders", 500)),
    dict(id="E10", name="Tax service unreachable", category="dependency",
         severity="high", escalate=True, context_needed=True,
         rationale="tax.calculate deliberately has no fallback, so a tax outage blocks every checkout (503).",
         title="ConnectTimeout: timed out",
         exc=("httpx.ConnectTimeout", "timed out"),
         frames=[CHECKOUT_TAX, frame("app/tax.py", "calculate", "response = httpx.post(TAX_URL")],
         level="error", env="production", req=("POST", "/checkout", 503)),
    dict(id="E11", name="Live payment key in event data", category="security",
         severity="high", escalate=True, context_needed=False,
         rationale="A live secret key was written to Sentry; it must be rotated immediately.",
         title="HTTPStatusError: Server error '500 Internal Server Error'",
         exc=("httpx.HTTPStatusError", "Server error '500 Internal Server Error' for url "
              "'https://api.payprovider.example/v1/charges' request headers: "
              "{'Authorization': 'Bearer sk_live_51Hq8EVALFIXTUREa9Xw2'}"),
         frames=[CHECKOUT_CHARGE, CHARGE_STATUS], level="error", env="production",
         req=("POST", "/checkout", 200)),
    dict(id="E12", name="Provider rate limiting during sale", category="payment",
         severity="high", escalate=True, context_needed=False,
         rationale="Checkouts fail with 503 after retries are exhausted by provider rate limits.",
         title="PaymentProviderUnavailable: charge failed after 3 attempts",
         exc=("PaymentProviderUnavailable", "charge failed after 3 attempts (last error: 429 Too Many Requests)"),
         frames=[CHECKOUT_CHARGE, CHARGE_GIVEUP], level="error", env="production",
         req=("POST", "/checkout", 503)),
    # ---------------------------------------------------------------- medium
    dict(id="E13", name="DB disk filling up", category="infrastructure",
         severity="medium", escalate=True, context_needed=False,
         rationale="No user impact yet, but at 2%/hour the primary is full in about 4 hours, before business hours.",
         title="DB primary disk usage at 92% (growing 2%/hour)",
         message="DB primary disk usage at 92% (growing 2%/hour)",
         frames=[frame("app/jobs/health_checks.py", "check_db_disk", "sentry_sdk.capture_message(")],
         level="warning", env="production", req=None),
    dict(id="E14", name="DB timeout in admin sales report", category="db-timeout",
         severity="medium", escalate=False, context_needed=False,
         rationale="Internal ops report only; customers unaffected; fix during business hours.",
         title="OperationalError: canceling statement due to statement timeout",
         exc=("sqlalchemy.exc.OperationalError", "(psycopg2.errors.QueryCanceled) canceling statement due to statement timeout"),
         frames=[frame("app/admin/reports.py", "sales_report", "rows = session.execute(")],
         level="error", env="production", req=("GET", "/admin/reports/sales", 500)),
    dict(id="E15", name="Redis cache down for carts", category="dependency",
         severity="medium", escalate=False, context_needed=True,
         rationale="load_cart catches Redis errors and reads from Postgres; carts still work, just slower.",
         title="ConnectionError: Error 111 connecting to redis:6379. Connection refused.",
         exc=("redis.exceptions.ConnectionError", "Error 111 connecting to redis:6379. Connection refused."),
         frames=[frame("app/cart.py", "get_cart", "current = load_cart(user.id, None)"),
                 frame("app/cart.py", "load_cart", 'cached = cache.get(f"cart:{user_id}")')],
         level="error", env="production", req=("GET", "/cart", 200)),
    dict(id="E16", name="Search cluster unreachable", category="dependency",
         severity="medium", escalate=False, context_needed=True,
         rationale="search_products falls back to a DB LIKE query; results are worse but search works.",
         title="ConnectError: [Errno 111] Connection refused",
         exc=("httpx.ConnectError", "[Errno 111] Connection refused"),
         frames=[frame("app/search.py", "search_products", "response = httpx.post(SEARCH_URL")],
         level="error", env="production", req=("GET", "/search", 200)),
    dict(id="E17", name="Confirmation email SMTP disconnect", category="notifications",
         severity="medium", escalate=False, context_needed=True,
         rationale="Emails are retried by the worker (8 attempts, 5 min apart); orders are unaffected.",
         title="SMTPServerDisconnected: Connection unexpectedly closed",
         exc=("smtplib.SMTPServerDisconnected", "Connection unexpectedly closed"),
         frames=[frame("app/notifications/email.py", "send_order_confirmation", "smtp.send_message(")],
         level="error", env="production", req=None),
    dict(id="E18", name="Nightly warehouse export denied", category="background-job",
         severity="medium", escalate=False, context_needed=True,
         rationale="Internal analytics export; the next run re-exports the missed night. No customer impact.",
         title="ClientError: An error occurred (AccessDenied) when calling the PutObject operation: Access Denied",
         exc=("botocore.exceptions.ClientError", "An error occurred (AccessDenied) when calling the PutObject operation: Access Denied"),
         frames=[frame("app/jobs/nightly_export.py", "run", 'boto3.client("s3").put_object(')],
         level="error", env="production", req=None),
    dict(id="E19", name="Avatar upload fails for HEIC", category="non-core",
         severity="medium", escalate=False, context_needed=False,
         rationale="Profile picture upload is a non-core feature affecting only some file types.",
         title="UnidentifiedImageError: cannot identify image file <_io.BytesIO object at 0x7f3b2c1d9e50>",
         exc=("PIL.UnidentifiedImageError", "cannot identify image file <_io.BytesIO object at 0x7f3b2c1d9e50>"),
         frames=[frame("app/accounts.py", "upload_avatar", "image = Image.open(file.file)")],
         level="error", env="production", req=("POST", "/account/avatar", 500)),
    dict(id="E20", name="Account deletion FK violation", category="data",
         severity="medium", escalate=False, context_needed=False,
         rationale="Privacy deletions fail and must be fixed within the 30-day window, but nothing breaks for users tonight.",
         title="IntegrityError: update or delete on table \"users\" violates foreign key constraint \"orders_user_id_fkey\"",
         exc=("sqlalchemy.exc.IntegrityError", "(psycopg2.errors.ForeignKeyViolation) update or delete on table \"users\" "
              "violates foreign key constraint \"orders_user_id_fkey\" on table \"orders\""),
         frames=[frame("app/accounts.py", "delete_account", "User.delete(session, user.id)")],
         level="error", env="production", req=("DELETE", "/account", 500)),
    dict(id="E21", name="Worker OOM in nightly export", category="background-job",
         severity="medium", escalate=False, context_needed=True,
         rationale="Fatal crash, but in the nightly export worker; the next run catches up and customers are unaffected.",
         title="MemoryError",
         exc=("MemoryError", ""),
         frames=[frame("app/jobs/nightly_export.py", "run", 'body = "\\n".join(str(o) for o in orders)')],
         level="fatal", env="production", req=None),
    dict(id="E22", name="Shipping rates API timeout", category="dependency",
         severity="medium", escalate=False, context_needed=True,
         rationale="get_rates falls back to a flat rate, so checkout completes; shipping charges are approximate.",
         title="ReadTimeout: The read operation timed out",
         exc=("httpx.ReadTimeout", "The read operation timed out"),
         frames=[CHECKOUT_SHIP, frame("app/shipping.py", "get_rates", "response = httpx.post(")],
         level="error", env="production", req=("POST", "/checkout", 200)),
    dict(id="E23", name="Order history IndexError for new users", category="null-pointer",
         severity="medium", escalate=False, context_needed=False,
         rationale="Order history page 500s for users with no orders; buying still works.",
         title="IndexError: list index out of range",
         exc=("IndexError", "list index out of range"),
         frames=[frame("app/orders.py", "list_orders", "newest = orders[0]")],
         level="error", env="production", req=("GET", "/orders", 500)),
    dict(id="E24", name="Refunds failing: restricted key expired", category="payment",
         severity="medium", escalate=False, context_needed=True,
         rationale="Only the refund-only key is affected: support cannot issue refunds, but charges and checkout work.",
         title="HTTPStatusError: Client error '401 Unauthorized'",
         exc=("httpx.HTTPStatusError", "Client error '401 Unauthorized' for url 'https://api.payprovider.example/v1/refunds'"),
         frames=[frame("app/admin/refunds.py", "refund_order", "payments.refund(order.charge_id"),
                 frame("app/payments.py", "refund", "response.raise_for_status()")],
         level="error", env="production", req=("POST", "/admin/orders/88213/refund", 500)),
    # ------------------------------------------------------------------- low
    dict(id="E25", name="Single payment timeout, retried", category="payment",
         severity="low", escalate=False, context_needed=True,
         rationale="The charge loop reports each failed attempt and retries; attempt 1 of 3 timing out is routine flakiness.",
         title="ReadTimeout: The read operation timed out",
         exc=("httpx.ReadTimeout", "The read operation timed out"),
         frames=[CHECKOUT_CHARGE, CHARGE_POST], level="error", env="production",
         req=("POST", "/checkout", 200), extra={"payment_attempt": 1}),
    dict(id="E26", name="Typo'd success log at ERROR level", category="log-message",
         severity="low", escalate=False, context_needed=True,
         rationale="A success message ('sent succesfully', with typos) is logged at ERROR level; nothing failed.",
         title="Order confirmaton email sent succesfully for order %s",
         message="Order confirmaton email sent succesfully for order 90412",
         frames=[frame("app/notifications/email.py", "send_order_confirmation", "logger.error(")],
         level="error", env="production", req=None),
    dict(id="E27", name="Log format TypeError after order placed", category="log-message",
         severity="low", escalate=False, context_needed=True,
         rationale="Bad format string in a log helper; checkout catches it after the order is committed.",
         title="TypeError: not all arguments converted during string formatting",
         exc=("TypeError", "not all arguments converted during string formatting"),
         frames=[CHECKOUT_LOG, frame("app/logging_utils.py", "log_order_event", 'logger.info("order event')],
         level="error", env="production", req=("POST", "/checkout", 200)),
    dict(id="E28", name="Wrong password", category="auth",
         severity="low", escalate=False, context_needed=False,
         rationale="A user typed the wrong password; expected 401.",
         title="HTTPException: Invalid credentials",
         exc=("fastapi.exceptions.HTTPException", "401: Invalid credentials"),
         frames=[frame("app/auth.py", "login", 'raise HTTPException(status_code=401, detail="Invalid credentials")')],
         level="warning", env="production", req=("POST", "/login", 401)),
    dict(id="E29", name="Login rate limit hit", category="auth",
         severity="low", escalate=False, context_needed=False,
         rationale="The rate limiter blocking a burst of logins from one IP is the protection working.",
         title="RateLimitExceeded: 10 per 1 minute",
         exc=("RateLimitExceeded", "10 per 1 minute (key=ip:203.0.113.7)"),
         frames=[],
         level="warning", env="production", req=("POST", "/login", 429)),
    dict(id="E30", name="Scanner probing wp-login", category="noise",
         severity="low", escalate=False, context_needed=False,
         rationale="Bot scanning for WordPress; route does not exist.",
         title="404 Not Found: /wp-login.php",
         message="404 Not Found: /wp-login.php",
         frames=[], level="warning", env="production", req=("GET", "/wp-login.php", 404)),
    dict(id="E31", name="Recommendations widget KeyError", category="non-core",
         severity="low", escalate=False, context_needed=True,
         rationale="similar_products swallows errors and returns []; the page renders without the widget.",
         title="KeyError: 'score'",
         exc=("KeyError", "'score'"),
         frames=[frame("app/recommendations.py", "similar_products", "ranked = sorted(")],
         level="error", env="production", req=("GET", "/products/5521", 200)),
    dict(id="E32", name="Legacy coupon backfill script crash", category="script",
         severity="low", escalate=False, context_needed=True,
         rationale="Only a manually run staff script imports this module; no API route is affected.",
         title="ValueError: too many values to unpack (expected 2)",
         exc=("ValueError", "too many values to unpack (expected 2)"),
         frames=[frame("scripts/backfill_coupons.py", "main", "rules=parse_v1_code(code)"),
                 frame("app/legacy/v1_coupons.py", "parse_v1_code", 'prefix, pct = code.split("-")')],
         level="error", env="production", req=None),
    dict(id="E33", name="Duplicate payment webhook ignored", category="payment",
         severity="low", escalate=False, context_needed=True,
         rationale="At-least-once delivery; the handler detects the duplicate and ignores it as designed.",
         title="Duplicate payment webhook evt_1Q2w3E ignored",
         message="Duplicate payment webhook evt_1Q2w3E ignored",
         frames=[frame("app/webhooks/payment_provider.py", "payment_webhook", 'sentry_sdk.capture_message(f"Duplicate')],
         level="warning", env="production", req=("POST", "/webhooks/payments", 200)),
    dict(id="E34", name="DB timeout in staging", category="db-timeout",
         severity="low", escalate=False, context_needed=False,
         rationale="Same error as E03 but in staging: no customers affected.",
         title="OperationalError: canceling statement due to statement timeout",
         exc=("sqlalchemy.exc.OperationalError", "(psycopg2.errors.QueryCanceled) canceling statement due to statement timeout"),
         frames=[CHECKOUT_STOCK, frame("app/inventory.py", "reserve_stock", 'text("SELECT quantity FROM stock')],
         level="error", env="staging", req=("POST", "/checkout", 500)),
    dict(id="E35", name="Null cart in local development", category="null-pointer",
         severity="low", escalate=False, context_needed=False,
         rationale="Same crash as E01 but from a developer's machine.",
         title="AttributeError: 'NoneType' object has no attribute 'items'",
         exc=("AttributeError", "'NoneType' object has no attribute 'items'"),
         frames=[CHECKOUT_ITEMS], level="error", env="development",
         req=("POST", "/checkout", 500)),
    dict(id="E36", name="Validation error: missing quantity", category="client-error",
         severity="low", escalate=False, context_needed=False,
         rationale="Client sent a malformed request; 422 is the correct response.",
         title="RequestValidationError: field required (quantity)",
         exc=("fastapi.exceptions.RequestValidationError", "1 validation error: body -> quantity: field required"),
         frames=[], level="warning", env="production", req=("POST", "/cart/items", 422)),
    dict(id="E37", name="utcnow deprecation warning", category="noise",
         severity="low", escalate=False, context_needed=False,
         rationale="Deprecation warning; no behavior change.",
         title="DeprecationWarning: datetime.datetime.utcnow() is deprecated",
         message="DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version.",
         frames=[], level="warning", env="production", req=None),
    dict(id="E38", name="SQL injection probe on search", category="noise",
         severity="low", escalate=False, context_needed=False,
         rationale="Scanner payload rejected with a 400 by input validation.",
         title="HTTPException: Invalid query",
         exc=("fastapi.exceptions.HTTPException", "400: Invalid query (q=\"' OR 1=1--\")"),
         frames=[frame("app/search.py", "search_products", 'raise HTTPException(status_code=400, detail="Invalid query")')],
         level="warning", env="production", req=("GET", "/search", 400)),
    dict(id="E39", name="Analytics collector unreachable", category="non-core",
         severity="low", escalate=False, context_needed=True,
         rationale="Client analytics forwarding fails silently and returns ok; no customer impact.",
         title="ConnectTimeout: timed out",
         exc=("httpx.ConnectTimeout", "timed out"),
         frames=[frame("app/analytics.py", "track", 'httpx.post("https://collector')],
         level="error", env="production", req=("POST", "/analytics/event", 200)),
    dict(id="E40", name="Websocket closed by customer", category="noise",
         severity="low", escalate=False, context_needed=True,
         rationale="Customer closed the tab during live tracking; normal disconnect.",
         title="ConnectionClosedOK: received 1001 (going away); then sent 1001 (going away)",
         exc=("websockets.exceptions.ConnectionClosedOK", "received 1001 (going away); then sent 1001 (going away)"),
         frames=[frame("app/live_tracking.py", "order_updates", "await ws.send_json(update)")],
         level="error", env="production", req=None),
]


def sentry_payload(case: dict, issue_number: int) -> dict:
    frames = [lib("starlette/routing.py", "handle", 276), *case["frames"]] if case["frames"] else []
    culprit = (
        f"{case['frames'][-1]['module']} in {case['frames'][-1]['function']}" if case["frames"] else case.get("message", "")
    )
    event: dict = {
        "event_id": f"evalcase{case['id'].lower()}",
        "issue_id": str(7_100_000 + issue_number),
        "title": case["title"],
        "culprit": culprit,
        "level": case["level"],
        "environment": case["env"],
        "platform": "python",
        "web_url": f"https://acme.sentry.io/issues/{7_100_000 + issue_number}/",
        "extra": dict(case.get("extra", {})),
    }

    if "exc" in case:
        exc_type, exc_value = case["exc"]
        event["exception"] = {"values": [{"type": exc_type, "value": exc_value,
                                          "stacktrace": {"frames": frames}}]}
    else:
        event["logentry"] = {"formatted": case["message"]}
        event["message"] = case["message"]
        if frames:
            event["exception"] = {"values": [{"type": "Message", "value": case["message"],
                                              "stacktrace": {"frames": frames}}]}

    if case["req"]:
        method, route, status = case["req"]
        event["request"] = {"method": method, "url": f"{BASE_URL}{route}"}
        event["extra"].update({"route": route, "method": method, "status_code": status})

    return {"action": "triggered", "actor": {"type": "application", "name": "Sentry"},
            "data": {"event": event, "triggered_rule": "Any new or regressed issue"}}


def main() -> None:
    out = []
    for number, case in enumerate(CASES, start=1):
        out.append({
            "id": case["id"],
            "name": case["name"],
            "category": case["category"],
            "label": {"severity": case["severity"], "escalate": case["escalate"]},
            "rationale": case["rationale"],
            "context_needed": case["context_needed"],
            "sentry_webhook": sentry_payload(case, number),
        })

    ids = [c["id"] for c in out]
    assert len(ids) == len(set(ids)) == 40, ids
    doc = {
        "description": "UpTime.ai severity/escalation eval set. Labels were written before any assessor ran.",
        "fixture_repo": "eval/fixture_repo (stack-frame paths are relative to it)",
        "rubric": RUBRIC,
        "cases": out,
    }
    (ROOT / "eval_errors.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    from collections import Counter
    print("severity:", dict(Counter(c["label"]["severity"] for c in out)))
    print("escalate:", dict(Counter(c["label"]["escalate"] for c in out)))
    print("context_needed:", sum(c["context_needed"] for c in out))


if __name__ == "__main__":
    main()
