from __future__ import annotations

import logging

import sentry_sdk


def configure_sentry(dsn: str | None) -> None:
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.05,
        profiles_sample_rate=0.02,
    )
    logging.info("Sentry initialized")
