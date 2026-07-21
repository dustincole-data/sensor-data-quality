"""The loader turns Sensor records into the derived JSON the page consumes.

`build_derived` is pure (records + now -> dict), so the full Trust Score, the
national failure-rate, and the JSON shape are all tested offline. `collect_and_build`
is exercised offline via fixture-backed fake clients — no live OpenAQ calls in the
suite (ticket criterion). T3 reads one /v3/sensors/{id}/days call per Sensor for
windowed completeness + plausibility (docs/adr/0002)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.loader import build_derived, collect_and_build
from src.scoring import TRUST_WEIGHTS

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "openaq"


def _rec(sensor_id, hours_ago=6, percent_complete=100.0, window_min=5.0, window_max=30.0,
         daily_means=None, **extra):
    """A scored-ready Sensor record: display context + the windowed fields the loader
    attaches from the /days call. hours_ago=None => never reported (empty window)."""
    dt = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return {"sensor_id": sensor_id, "location": f"loc-{sensor_id}", "provider": "AirNow",
            "datetime_last": dt, "percent_complete": percent_complete,
            "window_min": window_min, "window_max": window_max,
            "daily_means": daily_means, **extra}


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
    derived = build_derived([_rec(1, window_min=-6.0, window_max=1500.0)], NOW)
    sensor = derived["sensors"][0]
    assert "window_min" not in sensor and "window_max" not in sensor
    # ...yet the plausibility outcome + an auditable reason still surface (A1 F9).
    assert "plausibility" in sensor["failed_checks"]
    assert sensor["plausibility_reason"] == "below_floor"


def test_healthy_sensor_has_no_plausibility_reason():
    sensor = build_derived([_rec(1)], NOW)["sensors"][0]
    assert sensor["plausibility_reason"] is None


def test_build_derived_wires_drift_from_the_daily_series():
    # A drifting daily series (recent level 5 sigma from baseline) fails drift; the raw
    # series is never published (a measurement value), only the drift outcome.
    drifting = [8.0, 12.0] * 5 + [20.0] * 7
    sensor = build_derived([_rec(1, daily_means=drifting)], NOW)["sensors"][0]
    assert "drift" in sensor["failed_checks"]
    assert "daily_means" not in sensor


def test_per_sensor_carries_coordinates_for_the_map():
    # T6/ADR-0005: the hero map projects each Sensor's Location coordinates, so the
    # derived JSON must carry them (lat/lon) — display context, never a measurement.
    coords = {"latitude": 29.76, "longitude": -95.37}
    derived = build_derived([_rec(1, coordinates=coords)], NOW)
    assert derived["sensors"][0]["coordinates"] == coords


def test_missing_coordinates_emit_null_so_unmappable_sensors_are_counted_not_dropped():
    # ADR-0005: a Sensor with no coordinates is excluded from the map but still scored
    # and counted (the unmappable count is disclosed). Emit null — never drop the row.
    derived = build_derived([_rec(1)], NOW)  # _rec attaches no coordinates
    sensor = derived["sensors"][0]
    assert sensor["coordinates"] is None
    assert derived["national"]["sensors_scored"] == 1  # still in the aggregate


def test_derived_has_metadata_shape_the_page_reads():
    derived = build_derived([_rec(1)], NOW)
    assert derived["checks"] == ["staleness", "completeness", "plausibility", "drift"]
    assert derived["weights"] == TRUST_WEIGHTS
    assert derived["thresholds"]["stale_hours"] == 24
    assert derived["thresholds"]["completeness_floor_pct"] == 90.0
    assert derived["thresholds"]["plausible_min"] == -5.0
    assert derived["thresholds"]["plausible_max"] == 10000.0
    assert derived["generated_at"] == "2026-07-18T12:00:00+00:00"
    assert "OpenAQ" in derived["attribution"]


def test_derived_carries_drift_thresholds_and_a_provisional_weights_note():
    derived = build_derived([_rec(1)], NOW)
    assert derived["thresholds"]["drift_z"] == 3.0
    assert derived["thresholds"]["drift_recent_days"] == 7
    assert derived["thresholds"]["drift_min_baseline_days"] == 10
    # F13: the weights must be labelled provisional so 0.25x4 isn't read as settled.
    assert "provisional" in derived["weights_note"].lower()


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

    def iter_location_pages(self):
        yield self._page

    def get_sensor_days(self, sensor_id, date_from, date_to):
        self.requested_days.append((sensor_id, date_from, date_to))
        return self._days  # same healthy window fixture for every id


def test_collect_and_build_scores_fixture_sensors_offline():
    derived = collect_and_build(FakeClient(), NOW, sample_size=3)
    assert [s["sensor_id"] for s in derived["sensors"]] == [268, 2071327, 2071333]
    assert derived["national"]["sensors_scored"] == 3
    # Fixture window is healthy: 99.9% complete, plausible, ~1h since the station's
    # minute-resolution last-seen (A1 F5), and its recent level sits ~0.3 sigma from
    # baseline (no drift) -> passes all four checks and reaches the "excellent" band.
    assert derived["national"]["sensors_failed"] == 0
    assert derived["sensors"][0]["trust_score"] == 96.3


def test_collect_and_build_queries_a_30_day_window_by_date_not_datetime():
    client = FakeClient()
    collect_and_build(client, NOW, sample_size=1)
    _sensor_id, date_from, date_to = client.requested_days[0]
    # 30-day trailing window, YYYY-MM-DD (date_*, never datetime_*; docs/adr/0002).
    assert (date_from, date_to) == ("2026-06-18", "2026-07-18")


def test_collect_and_build_includes_exclusion_counts():
    derived = collect_and_build(FakeClient(), NOW, sample_size=3)
    assert "exclusions" in derived
    assert "by_redistribution_policy" in derived["exclusions"]
    # Fixture has no exclusions (Texas locations, public licenses).
    assert derived["exclusions"]["by_redistribution_policy"] == 0


class PagedClient:
    """Two single-sensor location pages then exhaustion, to cover collect_and_build's
    multi-page accumulation + pagination continuation (offline)."""

    def __init__(self):
        self._days = json.loads(
            (FIXTURES / "sensor_days_window.sample.json").read_text(encoding="utf-8"))

    def iter_location_pages(self):
        yield {"results": [{"name": "L1", "provider": {"name": "P"}, "licenses": [],
                            "coordinates": {"latitude": 29.76, "longitude": -95.37},
                            "sensors": [{"id": 11, "parameter": {"id": 2}}]}]}
        yield {"results": [{"name": "L2", "provider": {"name": "P"}, "licenses": [],
                            "coordinates": {"latitude": 29.76, "longitude": -95.37},
                            "sensors": [{"id": 22, "parameter": {"id": 2}}]}]}
        yield {"results": []}  # exhausted

    def get_sensor_days(self, sensor_id, date_from, date_to):
        return self._days


def test_collect_and_build_accumulates_across_pages_until_sample_size():
    derived = collect_and_build(PagedClient(), NOW, sample_size=2)
    # One PM2.5 sensor per page -> must advance to page 2 to fill the sample of 2.
    assert [s["sensor_id"] for s in derived["sensors"]] == [11, 22]


def test_collect_and_build_passes_location_coordinates_through_for_the_map():
    # The map projects each Sensor's Location coordinates; they must survive the whole
    # collect->build path (offline), not merely the pure build_derived pass.
    derived = collect_and_build(PagedClient(), NOW, sample_size=1)
    assert derived["sensors"][0]["coordinates"] == {"latitude": 29.76, "longitude": -95.37}


# --- T4/A5c: exclusions (licenses only) applied during collection -------------

class ExcludingClient:
    """Mock client with locations that trigger different exclusion rules."""

    def __init__(self):
        self._days = json.loads(
            (FIXTURES / "sensor_days_window.sample.json").read_text(encoding="utf-8"))

    def iter_location_pages(self):
        yield {
            "results": [
                # Texas location with public license -> included
                {"name": "TX Site", "provider": {"name": "P1"}, "licenses": [
                    {"name": "Public", "redistributionAllowed": True}
                ], "coordinates": {"latitude": 29.76, "longitude": -95.37},
                 "sensors": [{"id": 101, "parameter": {"id": 2}}]},
                # Kentucky location -> no longer excluded (ADR-0001 superseded, A5c)
                {"name": "KY Site", "provider": {"name": "P2"}, "licenses": [
                    {"name": "Public", "redistributionAllowed": True}
                ], "coordinates": {"latitude": 38.05, "longitude": -84.27},
                 "sensors": [{"id": 102, "parameter": {"id": 2}}]},
                # Site with restricted license -> excluded
                {"name": "Restricted Site", "provider": {"name": "P3"}, "licenses": [
                    {"name": "Restricted", "redistributionAllowed": False}
                ], "coordinates": {"latitude": 35.76, "longitude": -90.37},
                 "sensors": [{"id": 103, "parameter": {"id": 2}}]},
            ]
        }

    def get_sensor_days(self, sensor_id, date_from, date_to):
        return self._days


def test_exclusions_are_applied_and_counted():
    derived = collect_and_build(ExcludingClient(), NOW)
    # Texas AND Kentucky sensors are scored now; only the restricted-license site excludes.
    assert [s["sensor_id"] for s in derived["sensors"]] == [101, 102]
    assert derived["exclusions"]["by_redistribution_policy"] == 1
    assert "by_location_ky_louisville" not in derived["exclusions"]


def test_sensor_carries_provider_attribution():
    derived = collect_and_build(FakeClient(), NOW, sample_size=1)
    sensor = derived["sensors"][0]
    # The fixture location has attribution in its license.
    assert "provider_attribution" in sensor
    # Should be the organization name from the fixture.
    assert sensor["provider_attribution"] == "Unknown Governmental Organization"


# --- A5b F3: abort-resilience (one bad Sensor must not nuke a multi-hour run) ---

def _bare_loc(sensor_id):
    """A minimal single-PM2.5-Sensor Location page result (no datetimeLast)."""
    return {"name": f"L{sensor_id}", "provider": {"name": "P"}, "licenses": [],
            "coordinates": {"latitude": 29.76, "longitude": -95.37},
            "sensors": [{"id": sensor_id, "parameter": {"id": 2}}]}


class OneBadSensorClient:
    """Middle Sensor raises on /days — a non-retryable 4xx or a 5xx past the client's
    retries. The run must skip it and score the rest, never abort (A1 F3, 2026-07-20)."""

    def __init__(self):
        self._days = json.loads(
            (FIXTURES / "sensor_days_window.sample.json").read_text(encoding="utf-8"))

    def iter_location_pages(self):
        yield {"results": [_bare_loc(11), _bare_loc(22), _bare_loc(33)]}

    def get_sensor_days(self, sensor_id, date_from, date_to):
        if sensor_id == 22:
            raise RuntimeError("simulated upstream 500 past retries")
        return self._days


def test_collect_and_build_skips_a_raising_sensor_instead_of_aborting():
    derived = collect_and_build(OneBadSensorClient(), NOW)
    # The bad Sensor is dropped; the run completes and scores the survivors.
    assert [s["sensor_id"] for s in derived["sensors"]] == [11, 33]
    # ...and the skip is surfaced for transparency (published in the derived JSON).
    assert derived["skipped"] == 1


class AllBadClient:
    """Every Sensor raises — a systemic upstream outage, not one bad Sensor. Past the
    skip ceiling the run must abort so persist_run retains last-good rather than
    publishing a garbage panel (A1 F3)."""

    def iter_location_pages(self):
        yield {"results": [_bare_loc(i) for i in range(60)]}

    def get_sensor_days(self, sensor_id, date_from, date_to):
        raise RuntimeError("simulated total upstream outage")


def test_collect_and_build_aborts_when_skips_exceed_the_ceiling():
    # A widespread outage aborts with a clear "too many skips" signal — distinct from a
    # single Sensor's raw error, so a flood can't quietly publish an empty/garbage panel.
    with pytest.raises(RuntimeError, match="skipped"):
        collect_and_build(AllBadClient(), NOW)


# --- A5b F5: staleness reads the location's minute-resolution last-seen ---------

def _iso_z(dt):
    return dt.isoformat().replace("+00:00", "Z")


class StationFreshDaysStaleClient:
    """The Location reports a minute-resolution datetimeLast an hour ago, but its /days
    newest coverage end (day-resolution) is 30h old. Freshness must read the finer
    station last-seen, or a normally-reporting Sensor false-FAILs the 24h staleness
    bar and the "excellent" band stays unreachable (A1 F5)."""

    def __init__(self, station_last, days_end):
        self._station_last = station_last
        self._days_end = days_end

    def iter_location_pages(self):
        yield {"results": [{
            "name": "L1", "provider": {"name": "P"}, "licenses": [],
            "coordinates": {"latitude": 29.76, "longitude": -95.37},
            "datetimeLast": {"utc": _iso_z(self._station_last)},
            "sensors": [{"id": 1, "parameter": {"id": 2}}],
        }]}

    def get_sensor_days(self, sensor_id, date_from, date_to):
        # One healthy day whose coverage end is the coarse, 30h-old day boundary.
        return {"results": [{
            "summary": {"min": 5.0, "max": 20.0, "avg": 10.0},
            "coverage": {"expectedCount": 24, "observedCount": 24,
                         "percentComplete": 100.0, "datetimeTo": {"utc": _iso_z(self._days_end)}},
        }]}


def test_staleness_reads_location_last_seen_not_the_coarse_days_end():
    station_last = NOW - timedelta(hours=1)   # reported an hour ago (minute-resolution)
    days_end = NOW - timedelta(hours=30)      # coarse day boundary, >24h old
    derived = collect_and_build(
        StationFreshDaysStaleClient(station_last, days_end), NOW, sample_size=1)
    sensor = derived["sensors"][0]
    # The finer station last-seen wins: published freshness + the staleness check both
    # reflect "reported an hour ago", not the 30h-old day bucket -> not falsely stale.
    assert sensor["datetime_last"] == station_last.isoformat()
    assert "staleness" not in sensor["failed_checks"]


def test_missing_location_last_seen_falls_back_to_the_days_end():
    # Robustness: a Location with no datetimeLast still scores off the /days day boundary
    # rather than being dropped or forced stale (A5b is a robustness ticket).
    days_end = NOW - timedelta(hours=6)
    client = StationFreshDaysStaleClient(NOW, days_end)
    # Drop the datetimeLast the fresh-station client would emit.
    client.iter_location_pages = lambda: iter([{"results": [{
        "name": "L1", "provider": {"name": "P"}, "licenses": [],
        "coordinates": {"latitude": 29.76, "longitude": -95.37},
        "sensors": [{"id": 1, "parameter": {"id": 2}}],
    }]}])
    sensor = collect_and_build(client, NOW, sample_size=1)["sensors"][0]
    assert sensor["datetime_last"] == days_end.isoformat()
    assert "staleness" not in sensor["failed_checks"]
