"""The Trust Score (v1): a Sensor's 0-100 data-reporting-health score.

Pure functions, no I/O — the primary TDD seam (PRD Testing Decisions). Given one
Sensor's windowed summary fields, `score_sensor` returns the three v1 checks, the
graded score, and the "failed >=1 SLA" flag everything rolls up from.

Checks (CONTEXT.md glossary; thresholds per PRD / docs/adr/0002):
  - Staleness     FAIL if silent > 24h (raw last-seen; conservative re: ingestion lag)
  - Completeness  FAIL if trailing-30-day percentComplete < 90%   (windowed)
  - Plausibility  FAIL if window min < 0 or max > 1000 ug/m3       (windowed)

Score = 100 * (w_completeness*completeness_c + w_staleness*staleness_c + w_plausibility*plausibility_c)
where completeness_c = clamp(percentComplete/100, 0, 1),
      staleness_c    = clamp(1 - hours_since_last/24, 0, 1),
      plausibility_c = 1.0 if the window is plausible else 0.0.
Weights live in the single tunable TRUST_WEIGHTS config value."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from src.staleness import is_stale

# --- tunable configuration ----------------------------------------------------

# The one knob (PRD: "expose them as a single config so they're tunable once the
# score distribution is visible"). Keys are the check names; values must sum to 1.0.
TRUST_WEIGHTS: dict[str, float] = {
    "completeness": 0.40,
    "staleness": 0.40,
    "plausibility": 0.20,
}

# Check thresholds — deliberately conservative (docs/adr/0002).
STALE_HOURS = 24
COMPLETENESS_FLOOR_PCT = 90.0
PLAUSIBLE_MIN = 0.0
PLAUSIBLE_MAX = 1000.0

# Canonical order for reporting failed checks.
CHECKS = ("staleness", "completeness", "plausibility")


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


# --- composite Trust Score ----------------------------------------------------

def score_sensor(
    datetime_last: Optional[datetime],
    percent_complete: Optional[float],
    window_min: Optional[float],
    window_max: Optional[float],
    now: datetime,
    *,
    weights: dict[str, float] = TRUST_WEIGHTS,
) -> dict[str, Any]:
    """Grade one Sensor's reporting health from its windowed summary fields.

    Returns a JSON-serializable dict: `trust_score` (0-100, one decimal),
    `failed_checks` (the failing check names in canonical order), and `failed_any`
    ("failed >=1 SLA", the hero driver).
    """
    stale = datetime_last is None or is_stale(datetime_last, now, STALE_HOURS)
    incomplete = is_incomplete(percent_complete)
    implausible = is_implausible(window_min, window_max)

    # Graded components, each in [0, 1].
    if datetime_last is None:
        staleness_c = 0.0
    else:
        hours_since = (now - datetime_last).total_seconds() / 3600.0
        staleness_c = _clamp(1.0 - hours_since / STALE_HOURS)
    completeness_c = _clamp((percent_complete or 0.0) / 100.0)
    plausibility_c = 0.0 if implausible else 1.0

    trust_score = 100.0 * (
        weights["completeness"] * completeness_c
        + weights["staleness"] * staleness_c
        + weights["plausibility"] * plausibility_c
    )

    failed = {"staleness": stale, "completeness": incomplete, "plausibility": implausible}
    failed_checks = [name for name in CHECKS if failed[name]]

    return {
        "trust_score": round(trust_score, 1),
        "failed_checks": failed_checks,
        "failed_any": bool(failed_checks),
    }
