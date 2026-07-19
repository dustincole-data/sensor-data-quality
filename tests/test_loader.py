"""The loader turns Sensor records into the derived JSON the page consumes.

`build_derived` is pure (records + now -> dict), so the full Trust Score, the
national failure-rate, and the JSON shape are all tested offline. `collect_and_build`
is exercised offline via fixture-backed fake clients — no live OpenAQ calls in the
suite (ticket criterion). T3 reads one /v3/sensors/{id}/days call per Sensor for
windowed completeness + plausibility (docs/adr/0002)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.loader import build_derived, collect_and_build
from src.scoring import TRUST_WEIGHTS

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "openaq"


def _rec(sensor_id, hours_ago=6, percent_complete=100.0, window_min=5.0, window_max=30.0, **extra):
    """A scored-ready Sensor record: display context + the windowed fields the loader
    attaches from the /days call. hours_ago=None => never reported (empty window)."""
    dt = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return {"sensor_id": sensor_id, "location": f"loc-{sensor_id}", "provider": "AirNow",
            "datetime_last": dt, "percent_complete": percent_complete,
            "window_min": window_min, "window_max": window_max, **extra}


# --- build_derived: national failure-rate + per-Sensor Trust Score -----------

def test_national_failure_rate_is_share_failing_at_least_one_sla():
    # One healthy, one incomplete (pct 50 < 90) -> 1 of 2 failed a SLA.
    derived = build_derived([_rec(1), _rec(2, percent_complete=50.0)], NOW)
    assert derived["national"]["sensors_scored"] == 2
    assert derived["national"]["sensors_failed"] == 1
    assert derived["national"]["failure_rate_pct"] == 50.0


def test_per_sensor_carries_trust_score_and_failed_checks():
    derived = build_derived([_rec(2, percent_complete=50.0)], NOW)
    sensor = derived["sensors"][0]
    assert sensor["failed_checks"] == ["completeness"]
    assert sensor["failed_any"] is True
    assert 0 <= sensor["trust_score"] <= 100


def test_never_reported_sensor_fails_staleness_and_completeness():
    derived = build_derived([_rec(9, hours_ago=None, percent_complete=0.0,
                                  window_min=None, window_max=None)], NOW)
    sensor = derived["sensors"][0]
    assert sensor["datetime_last"] is None
    assert "staleness" in sensor["failed_checks"]
    assert "completeness" in sensor["failed_checks"]


def test_derived_carries_derived_metrics_as_json_serializable():
    derived = build_derived([_rec(1, hours_ago=1)], NOW)
    sensor = derived["sensors"][0]
    assert sensor["datetime_last"] == "2026-07-18T11:00:00+00:00"
    assert sensor["percent_complete"] == 100.0
    json.dumps(derived)  # must not raise


def test_raw_window_min_max_are_never_published():
    # CLAUDE.md hard constraint: only derived QA metrics ship, never a measurement
    # value. The window min/max feed plausibility internally but must not be emitted.
    derived = build_derived([_rec(1, window_min=-3.0, window_max=1500.0)], NOW)
    sensor = derived["sensors"][0]
    assert "window_min" not in sensor and "window_max" not in sensor
    # ...yet the plausibility outcome still surfaces.
    assert "plausibility" in sensor["failed_checks"]


def test_derived_has_metadata_shape_the_page_reads():
    derived = build_derived([_rec(1)], NOW)
    assert derived["checks"] == ["staleness", "completeness", "plausibility"]
    assert derived["weights"] == TRUST_WEIGHTS
    assert derived["thresholds"]["stale_hours"] == 24
    assert derived["thresholds"]["completeness_floor_pct"] == 90.0
    assert derived["thresholds"]["plausible_max"] == 1000.0
    assert derived["generated_at"] == "2026-07-18T12:00:00+00:00"
    assert "OpenAQ" in derived["attribution"]


def test_empty_panel_reports_zero_rate_not_a_crash():
    derived = build_derived([], NOW)
    assert derived["national"] == {"sensors_scored": 0, "sensors_failed": 0, "failure_rate_pct": 0.0}


def test_failure_rate_rounds_to_one_decimal():
    # 1 of 3 fail -> 33.333... -> 33.3
    derived = build_derived([_rec(1), _rec(2), _rec(3, percent_complete=10.0)], NOW)
    assert derived["national"]["failure_rate_pct"] == 33.3


# --- collect_and_build: offline end-to-end via fake clients ------------------

class FakeClient:
    """Stands in for the live OpenAQClient, serving the committed T1 fixtures so the
    loader's collect->score->build path runs with zero network access."""

    def __init__(self):
        self._page = json.loads(
            (FIXTURES / "locations_us_pm25_page.sample.json").read_text(encoding="utf-8"))
        self._days = json.loads(
            (FIXTURES / "sensor_days_window.sample.json").read_text(encoding="utf-8"))
        self.requested_days: list[tuple] = []

    def iter_location_pages(self, sample_size):
        yield self._page

    def get_sensor_days(self, sensor_id, date_from, date_to):
        self.requested_days.append((sensor_id, date_from, date_to))
        return self._days  # same healthy window fixture for every id


def test_collect_and_build_scores_fixture_sensors_offline():
    derived = collect_and_build(FakeClient(), NOW, sample_size=3)
    assert [s["sensor_id"] for s in derived["sensors"]] == [268, 2071327, 2071333]
    assert derived["national"]["sensors_scored"] == 3
    # Fixture window is healthy (99.9% complete, plausible, ~7h since last day-end).
    assert derived["national"]["sensors_failed"] == 0
    assert derived["sensors"][0]["trust_score"] == 88.3


def test_collect_and_build_queries_a_30_day_window_by_date_not_datetime():
    client = FakeClient()
    collect_and_build(client, NOW, sample_size=1)
    _sensor_id, date_from, date_to = client.requested_days[0]
    # 30-day trailing window, YYYY-MM-DD (date_*, never datetime_*; docs/adr/0002).
    assert (date_from, date_to) == ("2026-06-18", "2026-07-18")


class PagedClient:
    """Two single-sensor location pages then exhaustion, to cover collect_and_build's
    multi-page accumulation + `page += 1` continuation (offline)."""

    def __init__(self):
        self._days = json.loads(
            (FIXTURES / "sensor_days_window.sample.json").read_text(encoding="utf-8"))

    def iter_location_pages(self, sample_size):
        yield {"results": [{"name": "L1", "provider": {"name": "P"},
                            "sensors": [{"id": 11, "parameter": {"id": 2}}]}]}
        yield {"results": [{"name": "L2", "provider": {"name": "P"},
                            "sensors": [{"id": 22, "parameter": {"id": 2}}]}]}
        yield {"results": []}  # exhausted

    def get_sensor_days(self, sensor_id, date_from, date_to):
        return self._days


def test_collect_and_build_accumulates_across_pages_until_sample_size():
    derived = collect_and_build(PagedClient(), NOW, sample_size=2)
    # One PM2.5 sensor per page -> must advance to page 2 to fill the sample of 2.
    assert [s["sensor_id"] for s in derived["sensors"]] == [11, 22]
