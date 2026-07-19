"""Parse helpers read the exact OpenAQ v3 shapes captured by the T1 spike.
Tested against the committed fixtures so they run fully offline (no live calls).
Shapes/gotchas: tests/fixtures/README.md and .scratch/.../T1-spike-findings.md."""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.openaq import extract_pm25_sensors, parse_datetime_last, summarize_days_window

FIXTURES = Path(__file__).parent / "fixtures" / "openaq"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_extract_pm25_sensors_picks_only_pm25_across_locations():
    page = _load("locations_us_pm25_page.sample.json")
    sensors = extract_pm25_sensors(page)

    # 3 Locations in the fixture, one PM2.5 Sensor each (the other params are dropped).
    assert [s["sensor_id"] for s in sensors] == [268, 2071327, 2071333]


def test_extract_pm25_sensors_carries_display_context():
    page = _load("locations_us_pm25_page.sample.json")
    first = extract_pm25_sensors(page)[0]

    assert first["location"] == "Houston Deer Park C3"
    assert first["provider"] == "AirNow"
    assert first["coordinates"] == {"latitude": 29.670025, "longitude": -95.128508}


def test_extract_pm25_sensors_empty_page_yields_nothing():
    assert extract_pm25_sensors({"results": []}) == []


def test_parse_datetime_last_reads_utc_as_aware_datetime():
    detail = _load("sensor_detail.sample.json")
    assert parse_datetime_last(detail) == datetime(2026, 7, 18, 11, 0, 0, tzinfo=timezone.utc)


def test_parse_datetime_last_missing_field_is_none():
    # A Sensor that never reported has no datetimeLast — the loader treats None as stale.
    assert parse_datetime_last({"results": [{"id": 1}]}) is None
    assert parse_datetime_last({"results": []}) is None


# --- summarize_days_window: the T3 windowed scoring inputs ---------------------
# One /v3/sensors/{id}/days call yields BOTH windowed completeness AND plausibility
# min/max, plus a day-resolution last-seen (docs/adr/0002). date_from/date_to, not
# datetime_*. Asserted against the committed trailing-window fixture (id 268).

def test_summarize_days_window_completeness_is_observed_over_expected():
    window = summarize_days_window(_load("sensor_days_window.sample.json"))
    # 31 daily records: 30 full (24/24) + one 23/24 -> 743/744 -> 99.9%.
    assert window["percent_complete"] == 99.9


def test_summarize_days_window_min_max_span_the_whole_window():
    window = summarize_days_window(_load("sensor_days_window.sample.json"))
    assert window["window_min"] == 2.8
    assert window["window_max"] == 37.0


def test_summarize_days_window_last_seen_is_the_newest_day_end():
    window = summarize_days_window(_load("sensor_days_window.sample.json"))
    # Newest record's coverage end (day-resolution last-seen), tz-aware UTC.
    assert window["datetime_last"] == datetime(2026, 7, 18, 5, 0, 0, tzinfo=timezone.utc)


def test_summarize_days_window_ignores_record_order():
    # OpenAQ can return records oldest- or newest-first; last-seen is the max, not [-1].
    older = {"period": {"datetimeTo": {"utc": "2026-07-01T05:00:00Z"}},
             "coverage": {"expectedCount": 24, "observedCount": 24,
                          "datetimeTo": {"utc": "2026-07-01T05:00:00Z"}},
             "summary": {"min": 3.0, "max": 9.0}}
    newer = {"period": {"datetimeTo": {"utc": "2026-07-10T05:00:00Z"}},
             "coverage": {"expectedCount": 24, "observedCount": 24,
                          "datetimeTo": {"utc": "2026-07-10T05:00:00Z"}},
             "summary": {"min": 1.0, "max": 12.0}}
    window = summarize_days_window({"results": [newer, older]})  # newest first
    assert window["datetime_last"] == datetime(2026, 7, 10, 5, 0, 0, tzinfo=timezone.utc)


def test_summarize_days_window_empty_window_is_fully_incomplete():
    # A Sensor silent across the whole window: no data to plausibility-check, 0% complete.
    window = summarize_days_window({"results": []})
    assert window == {"datetime_last": None, "percent_complete": 0.0,
                      "window_min": None, "window_max": None}


# --- T4: location exclusions (licenses + Kentucky/Louisville) ----------------

def test_should_exclude_location_if_any_license_forbids_redistribution():
    from src.openaq import should_exclude_location

    # Location with a license that forbids redistribution.
    location = {
        "name": "Some Site",
        "coordinates": {"latitude": 29.76, "longitude": -95.37},
        "licenses": [
            {"name": "Restricted", "redistributionAllowed": False}
        ]
    }
    assert should_exclude_location(location) is True


def test_should_not_exclude_location_if_licenses_allow_redistribution():
    from src.openaq import should_exclude_location

    location = {
        "name": "Some Site",
        "coordinates": {"latitude": 29.76, "longitude": -95.37},
        "licenses": [
            {"name": "Public Domain", "redistributionAllowed": True}
        ]
    }
    assert should_exclude_location(location) is False


def test_should_exclude_location_in_louisville():
    from src.openaq import should_exclude_location

    location = {
        "name": "Downtown Louisville Site",
        "coordinates": {"latitude": 38.25, "longitude": -85.76},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(location) is True


def test_should_exclude_location_in_kentucky():
    from src.openaq import should_exclude_location

    # Eastern Kentucky (Lexington).
    location = {
        "name": "Lexington Site",
        "coordinates": {"latitude": 38.05, "longitude": -84.27},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(location) is True


def test_should_exclude_location_in_western_kentucky():
    from src.openaq import should_exclude_location

    # Western Kentucky (Paducah, lon -88.6) — must be excluded too. A too-narrow
    # bounding box that only covered eastern KY would leak this COI exclusion.
    paducah = {
        "name": "Paducah Site",
        "coordinates": {"latitude": 37.08, "longitude": -88.60},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(paducah) is True

    # Bowling Green (lon -86.42) — also western/central KY.
    bowling_green = {
        "name": "Bowling Green Site",
        "coordinates": {"latitude": 36.99, "longitude": -86.42},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(bowling_green) is True


def test_should_not_exclude_location_in_other_states():
    from src.openaq import should_exclude_location

    location = {
        "name": "Houston Site",
        "coordinates": {"latitude": 29.76, "longitude": -95.37},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(location) is False


# --- T4: 429 Retry-After parsing (offline; the backoff itself needs no network) ---

class _FakeResp:
    def __init__(self, headers):
        self.headers = headers


def test_retry_after_reads_integer_seconds():
    from src.openaq import OpenAQClient
    assert OpenAQClient._retry_after_seconds(_FakeResp({"retry-after": "30"})) == 30


def test_retry_after_defaults_when_header_absent():
    from src.openaq import OpenAQClient
    assert OpenAQClient._retry_after_seconds(_FakeResp({})) == 60


def test_retry_after_defaults_on_http_date_form():
    # Retry-After may legally be an HTTP-date; int() would crash, so we fall back.
    from src.openaq import OpenAQClient
    resp = _FakeResp({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert OpenAQClient._retry_after_seconds(resp) == 60


