"""The full Trust Score is the T3 seam: a pure function that turns one Sensor's
windowed summary fields (datetime_last, percentComplete, min, max, now) into the
three pass/fail checks + a graded 0-100 score + the "failed >=1 SLA" flag.

Boundaries are pinned by the ticket/PRD: staleness 23h/25h, completeness 89%/91%,
plausibility -1 / 1000 / 1001. Expected scores are hand-worked from the PRD formula
100 * (0.40*completeness + 0.40*staleness + 0.20*plausibility), not recomputed the
way the code does."""
from datetime import datetime, timedelta, timezone

from src.scoring import (
    DRIFT_Z,
    TRUST_WEIGHTS,
    drift_z,
    is_drifting,
    is_implausible,
    is_incomplete,
    plausibility_reason,
    score_sensor,
)

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


def _score(hours_ago=6, percent_complete=100.0, window_min=5.0, window_max=30.0,
           daily_means=None, weights=None):
    """score_sensor for a Sensor last seen `hours_ago` (None = never reported)."""
    last = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return score_sensor(
        datetime_last=last,
        percent_complete=percent_complete,
        window_min=window_min,
        window_max=window_max,
        now=NOW,
        daily_means=daily_means,
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


# --- plausibility predicate: a data-sanity bound, softened (ADR-0006) -----------
# FAIL only when window min < -5.0 (below the optical-PM noise floor) or max > 10000
# (beyond any real ambient value). Benign sub-zero noise and real wildfire extremes pass.

def test_plausibility_mild_negative_noise_passes():
    # -1 ug/m3 is routine optical-PM noise near the detection limit, not a garbage read
    # (A1 F1: the old min<0 bound mass-false-positived on exactly this).
    assert is_implausible(-1.0, 30.0) is False


def test_plausibility_below_noise_floor_fails():
    # Below the documented -4 to -5 noise floor -> a genuine sensor fault.
    assert is_implausible(-6.0, 30.0) is True


def test_plausibility_min_exactly_floor_passes_boundary_is_strictly_less():
    assert is_implausible(-5.0, 30.0) is False


def test_plausibility_real_wildfire_extreme_passes():
    # PM2.5 above 1000 genuinely occurs in wildfire plumes (A1 F2) -> not "bad data".
    assert is_implausible(5.0, 1500.0) is False


def test_plausibility_max_exactly_ceiling_passes_boundary_is_strictly_greater():
    assert is_implausible(5.0, 10000.0) is False


def test_plausibility_impossible_high_fails():
    # A value no real ambient reading reaches -> a stuck-high / sentinel fault.
    assert is_implausible(5.0, 10001.0) is True


def test_plausibility_absent_window_cannot_be_implausible():
    # No values in the window (Sensor silent) -> can't be a garbage reading.
    assert is_implausible(None, None) is False


def test_plausibility_reason_names_which_bound_broke_without_raw_values():
    # F9: the failure driver is auditable as a derived label, not a raw measurement.
    assert plausibility_reason(-6.0, 30.0) == "below_floor"
    assert plausibility_reason(5.0, 10001.0) == "above_ceiling"
    assert plausibility_reason(-1.0, 30.0) is None   # benign noise, no failure
    assert plausibility_reason(None, None) is None


# --- drift: rolling z-score of the recent level vs the Sensor's own baseline ----
# A constructed baseline whose mean/stdev are known by hand, so expected z-scores
# come from an independent source, not from re-running the code's own formula.
# baseline [8,12]*5 -> mean 10.0, population stdev 2.0 (every deviation is +-2).

BASELINE_MEAN10_SD2 = [8.0, 12.0] * 5  # 10 days, mean 10.0, pstdev 2.0


def test_drift_z_measures_recent_level_shift_in_sigmas():
    # recent 7 days all 20 -> recent mean 20; z = (20 - 10) / 2 = 5.0.
    series = BASELINE_MEAN10_SD2 + [20.0] * 7
    assert drift_z(series) == 5.0


def test_is_drifting_true_at_the_z_threshold_boundary():
    # recent mean 16 -> z = (16 - 10) / 2 = 3.0 == DRIFT_Z (>= is drift).
    assert DRIFT_Z == 3.0
    assert is_drifting(BASELINE_MEAN10_SD2 + [16.0] * 7) is True


def test_is_drifting_false_just_below_the_threshold():
    # recent mean 15 -> z = (15 - 10) / 2 = 2.5 < 3.0.
    assert is_drifting(BASELINE_MEAN10_SD2 + [15.0] * 7) is False


def test_is_drifting_is_symmetric_a_sharp_drop_also_drifts():
    # recent mean 4 -> z = (4 - 10) / 2 = -3.0 -> |z| = 3.0 -> drift.
    assert is_drifting(BASELINE_MEAN10_SD2 + [4.0] * 7) is True


def test_drift_insufficient_history_is_not_drift():
    # Too few points for a Baseline (need recent 7 + >=10 baseline) -> can't judge.
    short = [10.0, 12.0, 8.0] + [20.0] * 7  # only 3 baseline days
    assert drift_z(short) is None
    assert is_drifting(short) is False


def test_drift_flat_baseline_has_no_scale_to_judge_against():
    # A zero-spread Baseline gives no sigma -> None, not a divide-by-zero (a true
    # flatline is a separate, deferred check; here we simply can't compute drift).
    flat = [10.0] * 10 + [20.0] * 7
    assert drift_z(flat) is None
    assert is_drifting(flat) is False


def test_drift_empty_series_is_not_drift():
    assert drift_z([]) is None
    assert drift_z(None) is None
    assert is_drifting(None) is False


# --- staleness boundary, surfaced through the composite ------------------------

def test_staleness_23h_is_not_a_failed_check():
    assert "staleness" not in _score(hours_ago=23)["failed_checks"]


def test_staleness_25h_is_a_failed_check():
    assert "staleness" in _score(hours_ago=25)["failed_checks"]


def test_staleness_exactly_24h_is_not_stale():
    assert "staleness" not in _score(hours_ago=24)["failed_checks"]


def test_never_reported_sensor_fails_staleness():
    assert "staleness" in _score(hours_ago=None)["failed_checks"]


# --- drift, surfaced through the composite -------------------------------------

def test_drifting_sensor_fails_the_drift_check():
    # A healthy-but-drifting Sensor (recent level jumped 5 sigma from its baseline).
    result = _score(daily_means=BASELINE_MEAN10_SD2 + [20.0] * 7)
    assert "drift" in result["failed_checks"]
    assert result["failed_any"] is True


def test_healthy_series_passes_drift():
    # recent mean 11 -> z 0.5 -> not drift; a healthy series doesn't fail.
    result = _score(daily_means=BASELINE_MEAN10_SD2 + [11.0] * 7)
    assert "drift" not in result["failed_checks"]


def test_sensor_without_a_daily_series_passes_drift():
    # Back-compat / insufficient evidence: no series -> drift can't fire.
    assert "drift" not in _score(daily_means=None)["failed_checks"]


def test_drift_component_grades_the_score():
    # recent mean 13 -> z = (13 - 10) / 2 = 1.5 ; drift_c = clamp(1 - 1.5/3) = 0.5.
    # Everything else perfect: 100 * (0.25*1 + 0.25*1 + 0.25*1 + 0.25*0.5) = 87.5.
    result = _score(hours_ago=0, percent_complete=100.0, window_min=5.0, window_max=30.0,
                    daily_means=BASELINE_MEAN10_SD2 + [13.0] * 7)
    assert result["trust_score"] == 87.5


# --- graded score math (hand-worked from the PRD formula) ---------------------

def test_perfect_sensor_scores_100():
    # pct 100 -> 1.0 ; 0h stale -> 1.0 ; plausible -> 1.0 ; 100*(0.4+0.4+0.2)=100
    result = _score(hours_ago=0, percent_complete=100.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 100.0
    assert result["failed_checks"] == []
    assert result["failed_any"] is False


def test_graded_score_blends_all_four_components():
    # completeness 96 -> 0.96 ; 6h stale -> 1-6/24 = 0.75 ; plausible -> 1.0 ;
    # no series -> drift can't be judged -> 1.0.
    # 100 * (0.25*0.96 + 0.25*0.75 + 0.25*1.0 + 0.25*1.0) = 100 * 0.9275 = 92.8
    result = _score(hours_ago=6, percent_complete=96.0, window_min=4.3, window_max=37.0)
    assert result["trust_score"] == 92.8
    assert result["failed_any"] is False


def test_incomplete_sensor_is_graded_down_and_fails_completeness():
    # completeness 50 -> 0.5 (FAIL, <90) ; 12h stale -> 0.5 ; plausible -> 1.0 ; drift 1.0
    # 100 * (0.25*0.5 + 0.25*0.5 + 0.25*1.0 + 0.25*1.0) = 75.0
    result = _score(hours_ago=12, percent_complete=50.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 75.0
    assert result["failed_checks"] == ["completeness"]
    assert result["failed_any"] is True


def test_staleness_component_clamps_at_zero_for_very_stale():
    # 100h stale -> 1-100/24 < 0 -> clamped to 0 ; completeness/plausibility/drift perfect.
    # 100 * (0.25*1.0 + 0.25*0.0 + 0.25*1.0 + 0.25*1.0) = 75.0 ; and staleness FAILS.
    result = _score(hours_ago=100, percent_complete=100.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 75.0
    assert "staleness" in result["failed_checks"]


def test_completeness_component_caps_at_one_when_pct_exceeds_100():
    # Defensive: a >100 windowed pct never pushes the score above 100.
    result = _score(hours_ago=0, percent_complete=120.0, window_min=5.0, window_max=30.0)
    assert result["trust_score"] == 100.0


# --- "failed >=1 SLA" flag ----------------------------------------------------

def test_failed_checks_lists_every_broken_check_in_canonical_order():
    # stale (30h) + incomplete (40) + implausible (min -6 < -5): all three fail, in order.
    result = _score(hours_ago=30, percent_complete=40.0, window_min=-6.0, window_max=30.0)
    assert result["failed_checks"] == ["staleness", "completeness", "plausibility"]
    assert result["failed_any"] is True


def test_single_failure_still_trips_failed_any():
    result = _score(hours_ago=6, percent_complete=100.0, window_min=-6.0, window_max=30.0)
    assert result["failed_checks"] == ["plausibility"]
    assert result["failed_any"] is True


# --- weights are one tunable config value -------------------------------------

def test_weights_are_tunable_via_the_config_value():
    # All weight on completeness -> score == completeness_component * 100.
    only_completeness = {"completeness": 1.0, "staleness": 0.0, "plausibility": 0.0, "drift": 0.0}
    result = _score(hours_ago=100, percent_complete=73.0, window_min=-9.0, window_max=30.0,
                    weights=only_completeness)
    assert result["trust_score"] == 73.0


def test_default_weights_sum_to_one():
    assert round(sum(TRUST_WEIGHTS.values()), 6) == 1.0
