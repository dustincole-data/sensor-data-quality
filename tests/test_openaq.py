"""Parse helpers read the exact OpenAQ v3 shapes captured by the T1 spike.
Tested against the committed fixtures so they run fully offline (no live calls).
Shapes/gotchas: tests/fixtures/README.md and .scratch/.../T1-spike-findings.md."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


def test_extract_pm25_sensors_reads_location_last_seen_for_freshness():
    # F5: the Sensor's freshness (for the staleness check) is the Location's minute-
    # resolution datetimeLast on the /locations page — no extra call — not the coarse
    # /days coverage end. Absent datetimeLast -> None (the loader treats None as stale).
    page = _load("locations_us_pm25_page.sample.json")
    first = extract_pm25_sensors(page)[0]
    assert first["datetime_last"] == datetime(2026, 7, 18, 11, 0, 0, tzinfo=timezone.utc)

    no_last = extract_pm25_sensors(
        {"results": [{"name": "L", "sensors": [{"id": 9, "parameter": {"id": 2}}]}]})
    assert no_last[0]["datetime_last"] is None


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
                      "window_min": None, "window_max": None, "daily_means": []}


def test_summarize_days_window_retains_chronological_daily_means():
    # The per-day mean series feeds the drift check (docs/adr/0006). 31 daily records.
    window = summarize_days_window(_load("sensor_days_window.sample.json"))
    assert len(window["daily_means"]) == 31
    # Endpoints: oldest day (2026-06-17) avg first, newest day (2026-07-17) avg last.
    assert window["daily_means"][0] == pytest.approx(8.370833, abs=1e-4)
    assert window["daily_means"][-1] == pytest.approx(14.683333, abs=1e-4)


def test_summarize_days_window_daily_means_are_ordered_oldest_first():
    # Records may arrive newest-first; the series must still be chronological so the
    # drift baseline (older days) and recent window (newer days) split correctly.
    older = {"period": {"datetimeTo": {"utc": "2026-07-01T05:00:00Z"}},
             "coverage": {"expectedCount": 24, "observedCount": 24,
                          "datetimeTo": {"utc": "2026-07-01T05:00:00Z"}},
             "summary": {"min": 3.0, "max": 9.0, "avg": 6.0}}
    newer = {"period": {"datetimeTo": {"utc": "2026-07-10T05:00:00Z"}},
             "coverage": {"expectedCount": 24, "observedCount": 24,
                          "datetimeTo": {"utc": "2026-07-10T05:00:00Z"}},
             "summary": {"min": 1.0, "max": 12.0, "avg": 7.0}}
    window = summarize_days_window({"results": [newer, older]})  # newest first
    assert window["daily_means"] == [6.0, 7.0]  # older (6.0) then newer (7.0)


# --- T4/A5c: location exclusions (licenses only; the Kentucky/Louisville geo
# exclusion was removed 2026-07-20, no COI, ADR-0001 superseded) --------------

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


def test_should_not_exclude_kentucky_or_neighbor_state_locations():
    # A5c: the KY/Louisville geo exclusion is gone (no COI, Dustin's call; ADR-0001
    # superseded). Also verifies A1 F7: the removed bounding box used to mislabel
    # neighbor-state Sensors (Cincinnati OH) as KY exclusions — that's moot now.
    from src.openaq import should_exclude_location

    louisville = {
        "name": "Downtown Louisville Site",
        "coordinates": {"latitude": 38.25, "longitude": -85.76},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(louisville) is False

    lexington = {
        "name": "Lexington Site",
        "coordinates": {"latitude": 38.05, "longitude": -84.27},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(lexington) is False

    # Cincinnati OH — inside the old bbox's over-inclusive top edge (A1 F7).
    cincinnati = {
        "name": "Cincinnati Site",
        "coordinates": {"latitude": 39.10, "longitude": -84.51},
        "licenses": [{"name": "Public", "redistributionAllowed": True}]
    }
    assert should_exclude_location(cincinnati) is False


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


# --- transient-failure retries in _get: a 5xx must NOT abort the full-Panel run ---
# 2026-07-20 regression: one /sensors/{id}/days 500 crashed a ~1.5h run and nothing
# committed. _get now retries transient 5xx just as it already retried 429. Driven with
# a fake session so it stays offline; time.sleep is patched so the backoff costs no wall
# time.

class _FakeGetResp:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"{self.status_code} Error", response=self)


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def _client_with(responses, monkeypatch):
    from src.openaq import OpenAQClient
    monkeypatch.setattr("src.openaq.time.sleep", lambda *_: None)  # no real backoff wait
    client = OpenAQClient(api_key="test", stagger_interval=0)
    client._session = _FakeSession(responses)
    return client


def test_get_retries_transient_500_then_succeeds(monkeypatch):
    client = _client_with(
        [_FakeGetResp(500), _FakeGetResp(200, {"results": [{"ok": True}]})], monkeypatch
    )
    assert client._get("/sensors/1/days", {}) == {"results": [{"ok": True}]}
    assert client._session.calls == 2  # first 500 retried, second 200 returned


def test_get_gives_up_after_persistent_5xx(monkeypatch):
    import requests
    client = _client_with([_FakeGetResp(503) for _ in range(4)], monkeypatch)
    with pytest.raises(requests.exceptions.HTTPError):
        client._get("/sensors/1/days", {})
    assert client._session.calls == 4  # MAX_RETRIES (3) + 1 attempt, then raise


def test_backoff_honors_retry_after_for_429_but_is_short_for_5xx():
    from src.openaq import OpenAQClient
    # 429 -> honor the Retry-After rate-limit window.
    assert OpenAQClient._backoff_seconds(_FakeGetResp(429, headers={"retry-after": "30"}), 0) == 30
    # 5xx -> short capped exponential (1, 2, 4, 8), never the 60s rate-limit default.
    r500 = _FakeGetResp(500)
    assert OpenAQClient._backoff_seconds(r500, 0) == 1
    assert OpenAQClient._backoff_seconds(r500, 2) == 4
    assert OpenAQClient._backoff_seconds(r500, 9) == 8  # capped


