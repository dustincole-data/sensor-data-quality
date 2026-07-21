"""The Trust Score: a Sensor's 0-100 data-reporting-health score.

Pure functions, no I/O — the primary TDD seam (PRD Testing Decisions). Given one
Sensor's windowed summary fields, `score_sensor` returns the four checks, the graded
score, and the "failed >=1 check" flag everything rolls up from.

Checks (CONTEXT.md glossary; thresholds per PRD / docs/adr/0002, docs/adr/0006):
  - Staleness     FAIL if silent > 24h (raw last-seen; conservative re: ingestion lag)
  - Completeness  FAIL if trailing-30-day percentComplete < 90%   (windowed)
  - Plausibility  FAIL if window min < -5 or max > 10000 ug/m3     (data-sanity bound)
  - Drift         FAIL if the recent level is >= 3 sigma from the Sensor's own baseline

Score = 100 * (w_completeness*completeness_c + w_staleness*staleness_c
               + w_plausibility*plausibility_c + w_drift*drift_c)
where completeness_c = clamp(percentComplete/100, 0, 1),
      staleness_c    = clamp(1 - hours_since_last/24, 0, 1),
      plausibility_c = 1.0 if the window is plausible else 0.0,
      drift_c        = 1.0 if drift can't be judged, else clamp(1 - |z|/3, 0, 1).
Weights live in the single tunable TRUST_WEIGHTS config value."""
from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any, Optional

from src.staleness import is_stale

# --- tunable configuration ----------------------------------------------------

# The one knob (PRD: "expose them as a single config so they're tunable once the
# score distribution is visible"). Keys are the check names; values must sum to 1.0.
# Equal until the score distribution (full-panel A6 run) justifies otherwise: the two
# dropout views (staleness+completeness) share 0.50 instead of the old 0.80, and drift
# earns real, co-equal weight (ADR-0006). PROVISIONAL — tunable once the distribution is
# visible; surfaced to the page via WEIGHTS_NOTE.
TRUST_WEIGHTS: dict[str, float] = {
    "completeness": 0.25,
    "staleness": 0.25,
    "plausibility": 0.25,
    "drift": 0.25,
}

WEIGHTS_NOTE = (
    "Weights are provisional and equal across the four checks — they will be tuned once "
    "the full-panel score distribution is visible. Staleness and completeness are "
    "correlated views of dropout."
)

# Check thresholds — deliberately conservative (docs/adr/0002, docs/adr/0006).
STALE_HOURS = 24
COMPLETENESS_FLOOR_PCT = 90.0
# Plausibility is a data-sanity bound, not a physics claim (ADR-0006). Low bound sits
# below the documented -4 to -5 ug/m3 optical-PM noise floor (ADR-0002 Update) so benign
# near-zero noise no longer fails; high bound is a value no real *ambient* reading reaches
# (even record wildfire), a stuck-high/sentinel guard, not a judgment on extreme air.
PLAUSIBLE_MIN = -5.0
PLAUSIBLE_MAX = 10000.0

# Drift (ADR-0006): a rolling z-score of the recent reported level vs the Sensor's own
# trailing Baseline of daily means. Compares the last DRIFT_RECENT_DAYS daily means to
# the DRIFT_MIN_BASELINE_DAYS+ days before them; FAIL when |z| >= DRIFT_Z.
DRIFT_Z = 3.0
DRIFT_RECENT_DAYS = 7
DRIFT_MIN_BASELINE_DAYS = 10

# Canonical order for reporting failed checks.
CHECKS = ("staleness", "completeness", "plausibility", "drift")


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# --- individual checks (pure predicates) --------------------------------------

def is_incomplete(percent_complete: Optional[float], floor_pct: float = COMPLETENESS_FLOOR_PCT) -> bool:
    """True when trailing-window completeness is below the floor (default 90%).

    A missing value (Sensor silent across the whole window) counts as incomplete.
    Boundary is strictly-less: exactly the floor still passes.
    """
    if percent_complete is None:
        return True
    return percent_complete < floor_pct


def is_implausible(
    window_min: Optional[float],
    window_max: Optional[float],
    lo: float = PLAUSIBLE_MIN,
    hi: float = PLAUSIBLE_MAX,
) -> bool:
    """True when the window holds a physically impossible PM2.5 reading.

    FAIL if min < 0 or max > 1000 ug/m3. Absent values (an empty window) cannot be
    a garbage reading, so they pass — dropout is caught by staleness/completeness.
    Boundaries are strict: min == 0 and max == 1000 both pass.
    """
    if window_min is not None and window_min < lo:
        return True
    if window_max is not None and window_max > hi:
        return True
    return False


def plausibility_reason(
    window_min: Optional[float],
    window_max: Optional[float],
    lo: float = PLAUSIBLE_MIN,
    hi: float = PLAUSIBLE_MAX,
) -> Optional[str]:
    """Which bound a Sensor broke, as a derived label — or None if it passed.

    Makes the plausibility failure auditable in the published JSON (A1 F9) WITHOUT
    emitting the raw window min/max (the CLAUDE.md never-publish-raw-values constraint).
    Low bound takes precedence when both break.
    """
    if window_min is not None and window_min < lo:
        return "below_floor"
    if window_max is not None and window_max > hi:
        return "above_ceiling"
    return None


def drift_z(
    daily_means: Optional[list[float]],
    recent_days: int = DRIFT_RECENT_DAYS,
    min_baseline_days: int = DRIFT_MIN_BASELINE_DAYS,
) -> Optional[float]:
    """The recent reported level's z-score against the Sensor's own trailing Baseline.

    Splits the chronological `daily_means` series into a Baseline (all but the last
    `recent_days`) and a recent window (the last `recent_days`), then returns how many
    Baseline standard deviations the recent mean sits from the Baseline mean.

    Returns None when the check can't be computed: fewer than `recent_days +
    min_baseline_days` points, or a Baseline with zero spread (no scale to judge a shift
    against). A None z means "insufficient evidence" — the Sensor passes Drift (dropout
    is caught by staleness/completeness).
    """
    if not daily_means or len(daily_means) < recent_days + min_baseline_days:
        return None
    baseline = daily_means[:-recent_days]
    recent = daily_means[-recent_days:]
    sigma = statistics.pstdev(baseline)
    if sigma == 0:
        return None
    return (statistics.fmean(recent) - statistics.fmean(baseline)) / sigma


def is_drifting(
    daily_means: Optional[list[float]],
    recent_days: int = DRIFT_RECENT_DAYS,
    min_baseline_days: int = DRIFT_MIN_BASELINE_DAYS,
    z_threshold: float = DRIFT_Z,
) -> bool:
    """True when the recent level has shifted >= `z_threshold` sigmas from Baseline.

    Symmetric: a sharp drop drifts just as a sharp rise does. Insufficient evidence
    (drift_z is None) is not drift.
    """
    z = drift_z(daily_means, recent_days, min_baseline_days)
    return z is not None and abs(z) >= z_threshold


# --- composite Trust Score ----------------------------------------------------

def score_sensor(
    datetime_last: Optional[datetime],
    percent_complete: Optional[float],
    window_min: Optional[float],
    window_max: Optional[float],
    now: datetime,
    *,
    daily_means: Optional[list[float]] = None,
    weights: dict[str, float] = TRUST_WEIGHTS,
) -> dict[str, Any]:
    """Grade one Sensor's reporting health from its windowed summary fields.

    `daily_means` is the Sensor's chronological per-day mean series (for the drift
    check); None/too-short means drift can't be judged and the Sensor passes it.

    Returns a JSON-serializable dict: `trust_score` (0-100, one decimal),
    `failed_checks` (the failing check names in canonical order), and `failed_any`
    ("failed >=1 check", the hero driver).
    """
    stale = datetime_last is None or is_stale(datetime_last, now, STALE_HOURS)
    incomplete = is_incomplete(percent_complete)
    implausible = is_implausible(window_min, window_max)
    z = drift_z(daily_means)
    drifting = z is not None and abs(z) >= DRIFT_Z

    # Graded components, each in [0, 1].
    if datetime_last is None:
        staleness_c = 0.0
    else:
        hours_since = (now - datetime_last).total_seconds() / 3600.0
        staleness_c = _clamp(1.0 - hours_since / STALE_HOURS)
    completeness_c = _clamp((percent_complete or 0.0) / 100.0)
    plausibility_c = 0.0 if implausible else 1.0
    # Insufficient evidence (z is None) scores a full 1.0 — no penalty for a Sensor we
    # can't yet judge; only a measured shift grades it down, hitting 0 at the fail bar.
    drift_c = 1.0 if z is None else _clamp(1.0 - abs(z) / DRIFT_Z)

    trust_score = 100.0 * (
        weights["completeness"] * completeness_c
        + weights["staleness"] * staleness_c
        + weights["plausibility"] * plausibility_c
        + weights["drift"] * drift_c
    )

    failed = {"staleness": stale, "completeness": incomplete,
              "plausibility": implausible, "drift": drifting}
    failed_checks = [name for name in CHECKS if failed[name]]

    return {
        "trust_score": round(trust_score, 1),
        "failed_checks": failed_checks,
        "failed_any": bool(failed_checks),
    }
