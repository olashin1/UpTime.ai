"""Planned maintenance windows.

During a window the storefront shows a maintenance banner, and every Sentry event is
tagged so on-call can tell expected errors from real ones.
"""
import sentry_sdk

from app.infra import active_maintenance_window


def tag_maintenance() -> None:
    window = active_maintenance_window()
    if window is not None:
        sentry_sdk.set_tag("maintenance_window", window.name)
        sentry_sdk.set_tag("maintenance_until", window.ends_at)
