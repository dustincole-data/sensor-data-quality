"""The full Trust Score is the T3 seam: a pure function that turns one Sensor's
windowed summary fields (datetime_last, percentComplete, min, max, now) into the
three pass/fail checks + a graded 0-100 score + the "failed >=1 SLA" flag.

Boundaries are pinned by the ticket/PRD: staleness 23h/25h, completeness 89%/91%,
plausibility -1 / 1000 / 1001. Expected scores are hand-worked from the PRD formula
100 * (0.40*completeness + 0.40*staleness + 0.20*plausibility), not recomputed the
way the code does."""
from datetime import datetime, timedelta, timezone

from src.scoring import (
    TRUST_WEIGHTS,
    is_implausible,
    is_incomplete,
    score_sensor,
)

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def _score(hours_ago=6, percent_complete=100.0, window_min=5.0, window_max=30.0, weights=None):
    """score_sensor for a Sensor last seen `hours_ago` (None = never reported)."""
    last = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return score_sensor(
        datetime_last=last,
        percent_complete=percent_complete,
        window_min=window_min,
        window_max=window_max,
        now=NOW,
        weights=weights or TRUST_WEIGHTS,
    )


# --- completeness predicate: FAIL when trailing-30d percentComplete < 90 --------

def test_completeness_89pct_fails():
    assert is_incomplete(89.0) is True


def test_completeness_91pct_passes():
    assert is_incomplete(91.0) is False


def test_completeness_exactly_90pct_passes_boundary_is_strictly_less():
    # PRD: "< 90%" -> exactly 90 is still complete.
    assert is_incomplete(90.0) is False


# --- plausibility predicate: FAIL when window min < 0 or max > 1000 -------------

def test_plausibility_min_negative_one_fails():
    assert is_implausible(-1.0, 30.0) is True


def test_plausibility_max_exactly_1000_passes_boundary_is_strictly_greater():
    assert is_implausible(5.0, 1000.0) is False


def test_plausibility_max_1001_fails():
    assert is_implausible(5.0, 1001.0) is True


def test_plausibility_min_zero_passes():
    assert is_implausible(0.0, 30.0) is False


def test_plausibility_absent_window_cannot_be_implausible():
    # No values in the window (Sensor silent) -> can't be a garbage reading.
    assert is_implausible(None, None) is False


# --- staleness boundary, surfaced through the composite ------------------------

def test_staleness_23h_is_not_a_failed_check():
    assert "staleness" not in _score(hours_ago=23)["failed_checks"]


def test_staleness_25h_is_a_failed_check():
    assert "staleness" in _score(hours_ago=25)["failed_checks"]


def test_staleness_exactly_24h_is_not_stale():
    assert "staleness" not in _score(hours_ago=24)["failed_checks"]


def test_never_reported_sensor_fails_staleness():
    assert "staleness" in _score(hours_ago=None)["failed_checks"]


# --- graded score math (hand-worked from the PRD formula) ---------------------

def test_perfect_sensor_scores_100():
    # pct 100 -> 1.0 ; 0h stale -> 1.0 ; plausible -> 1.0 ; 100*(0.4+0.4+0.2)=100
    result = _score(hours_ago=0, percent_complete=100.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 100.0
    assert result["failed_checks"] == []
    assert result["failed_any"] is False


def test_graded_score_blends_all_three_components():
    # completeness 96 -> 0.96 ; 6h stale -> 1-6/24 = 0.75 ; plausible -> 1.0
    # 100 * (0.40*0.96 + 0.40*0.75 + 0.20*1.0) = 100 * 0.884 = 88.4
    result = _score(hours_ago=6, percent_complete=96.0, window_min=4.3, window_max=37.0)
    assert result["trust_score"] == 88.4
    assert result["failed_any"] is False


def test_incomplete_sensor_is_graded_down_and_fails_completeness():
    # completeness 50 -> 0.5 (FAIL, <90) ; 12h stale -> 0.5 ; plausible -> 1.0
    # 100 * (0.40*0.5 + 0.40*0.5 + 0.20*1.0) = 60.0
    result = _score(hours_ago=12, percent_complete=50.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 60.0
    assert result["failed_checks"] == ["completeness"]
    assert result["failed_any"] is True


def test_staleness_component_clamps_at_zero_for_very_stale():
    # 100h stale -> 1-100/24 < 0 -> clamped to 0 ; completeness/plausibility perfect.
    # 100 * (0.40*1.0 + 0.40*0.0 + 0.20*1.0) = 60.0 ; and staleness FAILS.
    result = _score(hours_ago=100, percent_complete=100.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 60.0
    assert "staleness" in result["failed_checks"]


def test_completeness_component_caps_at_one_when_pct_exceeds_100():
    # Defensive: a >100 windowed pct never pushes the score above 100.
    result = _score(hours_ago=0, percent_complete=120.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 100.0


# --- "failed >=1 SLA" flag ----------------------------------------------------

def test_failed_checks_lists_every_broken_check_in_canonical_order():
    # stale (30h) + incomplete (40) + implausible (max 2000): all three fail, in order.
    result = _score(hours_ago=30, percent_complete=40.0, window_min=-2.0, window_max=2000.0)
    assert result["failed_checks"] == ["staleness", "completeness", "plausibility"]
    assert result["failed_any"] is True


def test_single_failure_still_trips_failed_any():
    result = _score(hours_ago=6, percent_complete=100.0, window_min=-0.5, window_max=30.0)
    assert result["failed_checks"] == ["plausibility"]
    assert result["failed_any"] is True


# --- weights are one tunable config value -------------------------------------

def test_weights_are_tunable_via_the_config_value():
    # All weight on completeness -> score == completeness_component * 100.
    only_completeness = {"completeness": 1.0, "staleness": 0.0, "plausibility": 0.0}
    result = _score(hours_ago=100, percent_complete=73.0, window_min=-9.0, window_max=30.0,
                    weights=only_completeness)
    assert result["trust_score"] == 73.0


def test_default_weights_sum_to_one():
    assert round(sum(TRUST_WEIGHTS.values()), 6) == 1.0
