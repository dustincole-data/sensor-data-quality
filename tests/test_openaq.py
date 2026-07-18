"""Parse helpers read the exact OpenAQ v3 shapes captured by the T1 spike.
Tested against the committed fixtures so they run fully offline (no live calls).
Shapes/gotchas: tests/fixtures/README.md and .scratch/.../T1-spike-findings.md."""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.openaq import extract_pm25_sensors, parse_datetime_last

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
