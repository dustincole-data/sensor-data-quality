"""The Staleness data-quality check (v1).

Pure time math, no I/O — the pre-agreed TDD seam. A Sensor is *stale* when it has
been silent longer than the threshold (default 24h, per CONTEXT.md: "silent > 24h").
The 24h bar is deliberately conservative to shrug off OpenAQ's out-of-order
ingestion lag (see docs/adr/0002)."""
from datetime import datetime, timedelta


def is_stale(datetime_last: datetime, now: datetime, threshold_hours: int = 24) -> bool:
    """True when the Sensor's last report is older than `threshold_hours` before `now`.

    Boundary is strictly greater-than: exactly `threshold_hours` old is still healthy.
    Both args must be timezone-aware datetimes in the same frame (UTC by convention).
    """
    return (now - datetime_last) > timedelta(hours=threshold_hours)
