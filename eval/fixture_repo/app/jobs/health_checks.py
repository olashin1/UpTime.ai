import sentry_sdk

from app.infra import db_disk_usage

DISK_WARN_PCT = 85


def check_db_disk() -> None:
    usage = db_disk_usage()
    if usage.percent >= DISK_WARN_PCT:
        sentry_sdk.capture_message(
            f"DB primary disk usage at {usage.percent}% "
            f"(growing {usage.growth_pct_per_hour}%/hour)",
            level="warning",
        )
