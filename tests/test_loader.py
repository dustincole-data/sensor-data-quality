"""The loader turns Sensor records into the derived JSON the page consumes.

`build_derived` is pure (records + now -> dict), so the scoring + national stale-rate
math + JSON shape are all tested offline. `collect_and_build` is exercised offline via
a fixture-backed fake client — no live OpenAQ calls in the suite (ticket criterion #4)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.loader import build_derived, collect_and_build

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "openaq"


def _rec(sensor_id, hours_ago=None, **extra):
    """A Sensor record as `extract_pm25_sensors` yields, plus the datetime_last the
    loader attaches after the per-Sensor detail call. hours_ago=None => never reported."""
    dt = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return {"sensor_id": sensor_id, "location": f"loc-{sensor_id}",
            "provider": "AirNow", "datetime_last": dt, **extra}


# --- build_derived: national stale-rate + per-Sensor flag -------------------

def test_national_stale_rate_is_share_of_stale_sensors():
    derived = build_derived([_rec(1, hours_ago=1), _rec(2, hours_ago=30)], NOW)
    assert derived["national"]["sensors_scored"] == 2
    assert derived["national"]["stale"] == 1
    assert derived["national"]["stale_rate_pct"] == 50.0


def test_per_sensor_stale_flag_matches_the_24h_check():
    derived = build_derived([_rec(1, hours_ago=23), _rec(2, hours_ago=25)], NOW)
    by_id = {s["sensor_id"]: s for s in derived["sensors"]}
    assert by_id[1]["stale"] is False
    assert by_id[2]["stale"] is True


def test_sensor_that_never_reported_is_stale_with_null_datetime():
    derived = build_derived([_rec(9, hours_ago=None)], NOW)
    sensor = derived["sensors"][0]
    assert sensor["stale"] is True
    assert sensor["datetime_last"] is None


def test_derived_carries_reported_datetime_as_iso_utc_string():
    derived = build_derived([_rec(1, hours_ago=1)], NOW)
    # JSON-serializable: datetimes become ISO strings, not datetime objects.
    assert derived["sensors"][0]["datetime_last"] == "2026-07-18T11:00:00+00:00"
    json.dumps(derived)  # must not raise


def test_derived_has_metadata_shape_the_page_reads():
    derived = build_derived([_rec(1, hours_ago=1)], NOW)
    assert derived["check"] == "staleness"
    assert derived["threshold_hours"] == 24
    assert derived["generated_at"] == "2026-07-18T12:00:00+00:00"
    assert "OpenAQ" in derived["attribution"]


def test_empty_panel_reports_zero_rate_not_a_crash():
    derived = build_derived([], NOW)
    assert derived["national"] == {"sensors_scored": 0, "stale": 0, "stale_rate_pct": 0.0}


def test_stale_rate_rounds_to_one_decimal():
    # 1 of 3 stale -> 33.333... -> 33.3
    derived = build_derived([_rec(1, 1), _rec(2, 1), _rec(3, 30)], NOW)
    assert derived["national"]["stale_rate_pct"] == 33.3


# --- collect_and_build: offline end-to-end via a fake client ----------------

class FakeClient:
    """Stands in for the live OpenAQClient, serving the committed T1 fixtures so the
    loader's collect->score->build path runs with zero network access."""

    def __init__(self):
        self._page = json.loads(
            (FIXTURES / "locations_us_pm25_page.sample.json").read_text(encoding="utf-8"))
        self._detail = json.loads(
            (FIXTURES / "sensor_detail.sample.json").read_text(encoding="utf-8"))

    def iter_location_pages(self, sample_size):
        yield self._page

    def get_sensor_detail(self, sensor_id):
        # Reuse the one detail fixture, stamping the requested id (fixture only has 268).
        detail = json.loads(json.dumps(self._detail))
        detail["results"][0]["id"] = sensor_id
        return detail


def test_collect_and_build_scores_fixture_sensors_offline():
    derived = collect_and_build(FakeClient(), NOW, sample_size=3)
    assert [s["sensor_id"] for s in derived["sensors"]] == [268, 2071327, 2071333]
    assert derived["national"]["sensors_scored"] == 3
    # Fixture datetimeLast is 2026-07-18T11:00Z (1h before NOW) -> all fresh.
    assert derived["national"]["stale"] == 0


class PagedClient:
    """Two single-sensor location pages then exhaustion, to cover collect_and_build's
    multi-page accumulation + `page += 1` continuation (offline)."""

    def __init__(self):
        self._detail = json.loads(
            (FIXTURES / "sensor_detail.sample.json").read_text(encoding="utf-8"))

    def iter_location_pages(self, sample_size):
        yield {"results": [{"name": "L1", "provider": {"name": "P"},
                            "sensors": [{"id": 11, "parameter": {"id": 2}}]}]}
        yield {"results": [{"name": "L2", "provider": {"name": "P"},
                            "sensors": [{"id": 22, "parameter": {"id": 2}}]}]}
        yield {"results": []}  # exhausted

    def get_sensor_detail(self, sensor_id):
        detail = json.loads(json.dumps(self._detail))
        detail["results"][0]["id"] = sensor_id
        return detail


def test_collect_and_build_accumulates_across_pages_until_sample_size():
    derived = collect_and_build(PagedClient(), NOW, sample_size=2)
    # One PM2.5 sensor per page -> must advance to page 2 to fill the sample of 2.
    assert [s["sensor_id"] for s in derived["sensors"]] == [11, 22]
