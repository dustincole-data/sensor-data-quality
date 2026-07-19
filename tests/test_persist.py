"""Durable output + fallback: the derived JSON is only ever replaced by a valid,
non-empty result, and a rolling 90-day aggregate history is appended each run.

All offline (T5 criterion): the pure gate/entry/append functions and the disk write
(against tmp_path) are exercised with hand-built derived dicts — no live OpenAQ calls.
The load-bearing guarantee is that a loader failure or empty result must NOT overwrite
the last-good JSON."""
import json
from datetime import datetime, timezone

from src.persist import (
    append_history,
    build_history_entry,
    is_valid_derived,
    persist_run,
)

NOW = datetime(2026, 7, 19, 2, 0, 0, tzinfo=timezone.utc)


def _derived(sensors_scored=2, failure_rate=50.0, sensors=None):
    """A minimal derived dict in the shape loader.build_derived emits."""
    if sensors is None:
        sensors = [
            {"sensor_id": 1, "provider": "AirNow", "trust_score": 90.0, "failed_any": False},
            {"sensor_id": 2, "provider": "AirNow", "trust_score": 40.0, "failed_any": True},
        ]
    return {
        "generated_at": NOW.isoformat(),
        "national": {"sensors_scored": sensors_scored, "sensors_failed": 1,
                     "failure_rate_pct": failure_rate},
        "sensors": sensors,
    }


# --- is_valid_derived: the non-empty / not-broken gate ------------------------

def test_valid_derived_with_scored_sensors_is_valid():
    assert is_valid_derived(_derived()) is True


def test_empty_result_is_invalid():
    # OpenAQ returned nothing this run: zero sensors scored -> must not overwrite.
    assert is_valid_derived(_derived(sensors_scored=0, sensors=[])) is False


def test_broken_result_is_invalid():
    # A malformed / partially-written dict (missing national, not a dict) is invalid.
    assert is_valid_derived({}) is False
    assert is_valid_derived(None) is False
    assert is_valid_derived({"national": {"sensors_scored": 3}, "sensors": []}) is False


# --- persist_run: safe write, retain last-good on failure --------------------

def test_persist_writes_derived_and_history_when_valid(tmp_path):
    derived_path = tmp_path / "trust_index.json"
    history_path = tmp_path / "history.json"

    written = persist_run(_derived(), NOW, derived_path=derived_path, history_path=history_path)

    assert written is True
    assert json.loads(derived_path.read_text())["national"]["failure_rate_pct"] == 50.0
    assert history_path.exists()


def test_empty_result_retains_last_good_byte_for_byte(tmp_path):
    # The T5 guarantee: a simulated failure (empty result) must NOT overwrite the
    # last-good JSON with a broken/empty file.
    derived_path = tmp_path / "trust_index.json"
    history_path = tmp_path / "history.json"
    last_good = json.dumps(_derived(failure_rate=42.0), indent=2)
    derived_path.write_text(last_good, encoding="utf-8")

    written = persist_run(_derived(sensors_scored=0, sensors=[]), NOW,
                          derived_path=derived_path, history_path=history_path)

    assert written is False
    assert derived_path.read_text(encoding="utf-8") == last_good  # untouched
    assert not history_path.exists()  # no history appended on a retained run


# --- build_history_entry: failure-rate + per-provider medians ----------------

def test_history_entry_carries_failure_rate_and_date():
    entry = build_history_entry(_derived(failure_rate=68.0), NOW)
    assert entry["date"] == "2026-07-19"
    assert entry["failure_rate_pct"] == 68.0
    assert entry["sensors_scored"] == 2


def test_history_entry_provider_medians_are_median_trust_score_per_provider():
    sensors = [
        {"sensor_id": 1, "provider": "AirNow", "trust_score": 90.0},
        {"sensor_id": 2, "provider": "AirNow", "trust_score": 70.0},   # AirNow median 80
        {"sensor_id": 3, "provider": "PurpleAir", "trust_score": 40.0},
        {"sensor_id": 4, "provider": None, "trust_score": 55.0},        # -> "Unknown"
    ]
    entry = build_history_entry(_derived(sensors=sensors), NOW)
    assert entry["provider_medians"] == {"AirNow": 80.0, "PurpleAir": 40.0, "Unknown": 55.0}


# --- append_history: idempotent per day + 90-day retention -------------------

def test_append_replaces_same_day_entry_rather_than_duplicating():
    day1 = {"date": "2026-07-19", "failure_rate_pct": 60.0}
    rerun = {"date": "2026-07-19", "failure_rate_pct": 68.0}
    rows = append_history([day1], rerun)
    assert len(rows) == 1
    assert rows[0]["failure_rate_pct"] == 68.0


def test_append_drops_entries_older_than_the_retention_window():
    old = {"date": "2026-01-01", "failure_rate_pct": 10.0}   # ~200 days before NOW
    recent = {"date": "2026-07-10", "failure_rate_pct": 20.0}
    today = {"date": "2026-07-19", "failure_rate_pct": 30.0}
    rows = append_history([old, recent], today, retention_days=90)
    dates = [r["date"] for r in rows]
    assert "2026-01-01" not in dates          # trimmed
    assert dates == ["2026-07-10", "2026-07-19"]  # kept, sorted


def test_append_drops_a_corrupt_row_instead_of_crashing():
    # A malformed existing row (no parseable date) must not abort an otherwise-good
    # run — it is dropped, matching the module's "never abort a good run" contract.
    corrupt = {"failure_rate_pct": 99.0}          # missing "date"
    bad_date = {"date": "not-a-date", "failure_rate_pct": 88.0}
    good = {"date": "2026-07-10", "failure_rate_pct": 20.0}
    today = {"date": "2026-07-19", "failure_rate_pct": 30.0}
    rows = append_history([corrupt, bad_date, good], today)
    assert [r["date"] for r in rows] == ["2026-07-10", "2026-07-19"]


def test_persist_self_heals_a_corrupt_history_file(tmp_path):
    derived_path = tmp_path / "trust_index.json"
    history_path = tmp_path / "history.json"
    # A history file whose rows are junk must not block publishing a good run.
    history_path.write_text(json.dumps(
        {"retention_days": 90, "history": [{"oops": True}]}), encoding="utf-8")

    written = persist_run(_derived(), NOW,
                          derived_path=derived_path, history_path=history_path)

    assert written is True
    hist = json.loads(history_path.read_text())
    assert [r["date"] for r in hist["history"]] == ["2026-07-19"]  # good row, junk dropped


def test_persist_appends_across_runs(tmp_path):
    derived_path = tmp_path / "trust_index.json"
    history_path = tmp_path / "history.json"
    day1 = datetime(2026, 7, 18, 2, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 7, 19, 2, 0, 0, tzinfo=timezone.utc)

    persist_run(_derived(failure_rate=60.0), day1,
                derived_path=derived_path, history_path=history_path)
    persist_run(_derived(failure_rate=68.0), day2,
                derived_path=derived_path, history_path=history_path)

    hist = json.loads(history_path.read_text())
    assert hist["retention_days"] == 90
    assert [r["date"] for r in hist["history"]] == ["2026-07-18", "2026-07-19"]
