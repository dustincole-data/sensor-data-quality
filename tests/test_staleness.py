"""Staleness is the one v1 check T2 ships: a Sensor is stale when silent > 24h
(CONTEXT.md glossary). Boundary cases pinned by the ticket: 23h passes, 25h fails."""
from datetime import datetime, timedelta, timezone

from src.staleness import is_stale

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def test_23h_since_last_report_is_not_stale():
    assert is_stale(NOW - timedelta(hours=23), NOW) is False


def test_25h_since_last_report_is_stale():
    assert is_stale(NOW - timedelta(hours=25), NOW) is True


def test_exactly_24h_is_not_stale_boundary_is_strictly_greater():
    # Glossary defines staleness as "silent > 24h": exactly 24h is still healthy.
    assert is_stale(NOW - timedelta(hours=24), NOW) is False


def test_one_second_past_24h_is_stale():
    assert is_stale(NOW - timedelta(hours=24, seconds=1), NOW) is True


def test_threshold_hours_is_configurable():
    last = NOW - timedelta(hours=10)
    assert is_stale(last, NOW, threshold_hours=6) is True
    assert is_stale(last, NOW, threshold_hours=12) is False
