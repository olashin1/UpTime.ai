"""Login anomaly detection. Runs on every successful or failed login."""
import sentry_sdk

from app.geo import country_for_ip

FAILED_LOGIN_ALERT_PER_HOUR = 5000


def check_staff_login(user, ip: str, device_id: str) -> None:
    country = country_for_ip(ip)
    if not user.is_staff:
        return
    if country not in user.known_countries and user.minutes_since_password_reset() < 60:
        # Staff accounts can issue refunds and edit prices.
        sentry_sdk.capture_message(
            f"Staff login for {user.username} from new country {country} "
            f"{user.minutes_since_password_reset()} min after password reset (new device {device_id})",
            level="warning",
        )


def check_failed_login_volume(stats) -> None:
    # Per-IP rate limiting (auth.login) does not stop attacks spread across many IPs.
    if stats.failed_last_hour >= FAILED_LOGIN_ALERT_PER_HOUR:
        sentry_sdk.capture_message(
            f"{stats.failed_last_hour} failed logins in the last hour from {stats.distinct_ips} IPs "
            f"({stats.successful_last_hour} successful logins to accounts with a failed attempt)",
            level="warning",
        )
