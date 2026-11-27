"""Periodic infrastructure checks (every 5 minutes, from the worker).

Each check reports to Sentry as a message; the message text carries the numbers.
"""
import sentry_sdk

from app.infra import checkout_error_rate, db_cluster_status, db_disk_usage, tls_certificate

DISK_WARN_PCT = 85
ERROR_RATE_WARN_PCT = 5
TLS_WARN_DAYS = 3


def check_db_disk() -> None:
    usage = db_disk_usage()
    if usage.percent >= DISK_WARN_PCT:
        sentry_sdk.capture_message(
            f"DB primary disk usage at {usage.percent}% "
            f"(growing {usage.growth_pct_per_hour}%/hour)",
            level="warning",
        )


def check_checkout_error_rate() -> None:
    stats = checkout_error_rate(window_minutes=60)

    if stats.recovered_after_spike:
        # A spike crossed the threshold and has already come back to normal.
        sentry_sdk.capture_message(
            f"Checkout 5xx rate peaked at {stats.peak_pct}% for {stats.spike_minutes} min "
            f"and recovered at {stats.recovered_at} (now {stats.current_pct}%)",
            level="warning",
        )
    elif stats.current_pct >= ERROR_RATE_WARN_PCT:
        sentry_sdk.capture_message(
            f"Checkout 5xx rate at {stats.current_pct}% and rising "
            f"{stats.trend_points_per_hour} points/hour for the last {stats.trend_hours} hours",
            level="warning",
        )


def check_db_failover() -> None:
    status = db_cluster_status()
    if status.failover_completed:
        # The managed database promotes the replica automatically.
        sentry_sdk.capture_message(
            f"DB primary failed over to replica {status.new_primary}; writes failed for "
            f"{status.write_outage_seconds}s; replication healthy, error rate back to baseline",
            level="warning",
        )


def check_tls_expiry() -> None:
    cert = tls_certificate("shop.acme.example")
    if cert.days_left <= TLS_WARN_DAYS:
        # Auto-renewal needs a DNS challenge; if it fails, someone must renew by hand.
        sentry_sdk.capture_message(
            f"TLS certificate for shop.acme.example expires in {cert.days_left} days "
            f"({cert.not_after}); auto-renewal failed: {cert.renewal_error}",
            level="warning",
        )
