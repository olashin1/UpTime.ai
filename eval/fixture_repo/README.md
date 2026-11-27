# acme-shop

Backend for the Acme online store (FastAPI + PostgreSQL). Serves the storefront, cart,
checkout, and customer accounts, plus internal admin tools and background jobs.

## Layout

| Path | What it does |
| --- | --- |
| `app/main.py` | FastAPI app, routes, request middleware that tags Sentry events |
| `app/checkout.py` | `place_order`: cart -> discounts -> tax -> shipping -> stock -> charge -> order |
| `app/payments.py` | Card charges and refunds through the payment provider |
| `app/webhooks/payment_provider.py` | Payment provider callbacks (marks orders paid) |
| `app/inventory.py` | Stock reservation |
| `app/tax.py`, `app/shipping.py` | Tax and shipping rate lookups |
| `app/auth.py` | Login and token verification for every authenticated request |
| `app/cart.py` | Cart storage (Redis cache in front of Postgres) |
| `app/search.py` | Product search |
| `app/recommendations.py` | "You may also like" widget on product pages |
| `app/accounts.py` | Profile, avatar upload, account deletion |
| `app/orders.py` | Order history page |
| `app/analytics.py` | Client-side event forwarding |
| `app/live_tracking.py` | Live order-status websocket |
| `app/notifications/email.py` | Order confirmation emails (sent from the worker queue) |
| `app/admin/reports.py` | Internal sales reports for the ops team |
| `app/jobs/nightly_export.py` | Nightly export of orders to the data warehouse |
| `app/jobs/health_checks.py` | Periodic checks: DB disk, checkout error rate, DB failover, TLS expiry |
| `app/security.py` | Login anomaly detection |
| `app/maintenance.py` | Tags Sentry events during planned maintenance windows |
| `app/legacy/v1_coupons.py` | Old coupon format, only used by `scripts/backfill_coupons.py` |
| `app/db.py` | SQLAlchemy engine and sessions |
| `app/logging_utils.py` | Structured order-event logging |

Errors are reported to Sentry from the API and from the worker.
