"""Durable output + fallback for the daily run (T5).

The loader produces a fresh `derived` dict each run; this module is the only thing
that writes it to disk, and it writes **defensively**:

  - `is_valid_derived`  the gate: a result must be a non-empty, well-formed scoring
    of real Sensors before it may replace the committed JSON.
  - `persist_run`       writes the derived JSON + appends the history ONLY when the
    result passes the gate; otherwise the last-good files are left untouched. Writes
    are atomic (temp + os.replace) so a crash mid-write can't corrupt last-good.

On a loader failure or empty result the daily cron therefore keeps serving the last
good JSON rather than publishing a broken/empty file (T5 criterion).

Alongside the point-in-time JSON it maintains a rolling **90-day aggregate history**
(`history.json`): one entry per day carrying the national failure-rate and each
provider's median Trust Score, for the page's 90-day trend."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Optional

# data/derived/ — committed; raw pulls (data/raw/) never are.
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "derived"
DERIVED_PATH = DATA_DIR / "trust_index.json"
HISTORY_PATH = DATA_DIR / "history.json"

HISTORY_RETENTION_DAYS = 90

# Scary-wrong guard (A1 F4). is_valid_derived only proves a run is STRUCTURALLY sound —
# an all-dead upstream (empty-but-200 for every Sensor) scores ~100% failed, is
# structurally valid, and would overwrite last-good with a maximally-alarming headline.
# So publishing also requires the headline be plausible: under an absolute ceiling, and —
# when comparing the SAME panel — not swinging implausibly far from last-good. A panel
# change (e.g. sample -> full at A6) is not a comparable swing, so only the ceiling
# applies there. A held run retains last-good pending manual confirmation.
FAILURE_RATE_CEILING_PCT = 90.0
FAILURE_RATE_JUMP_PP = 30.0


def is_valid_derived(derived: Any) -> bool:
    """True if `derived` is a well-formed, non-empty scoring (structurally sound).

    Guards the last-good JSON against an empty result (zero Sensors scored) or a
    malformed dict (a partial write, a failure that produced junk). Structural only —
    the scary-wrong headline guard is `is_publishable`.
    """
    if not isinstance(derived, dict):
        return False
    national = derived.get("national")
    sensors = derived.get("sensors")
    if not isinstance(national, dict) or not isinstance(sensors, list) or not sensors:
        return False
    scored = national.get("sensors_scored")
    return isinstance(scored, int) and scored > 0


def _failure_rate(derived: Any) -> Optional[float]:
    """The national failure-rate of a derived dict, or None if absent/malformed."""
    national = derived.get("national") if isinstance(derived, dict) else None
    rate = national.get("failure_rate_pct") if isinstance(national, dict) else None
    return rate if isinstance(rate, (int, float)) else None


def is_publishable(derived: Any, last_good: Optional[dict[str, Any]]) -> bool:
    """True if `derived` is safe to publish: structurally sound AND not scary-wrong.

    Beyond is_valid_derived, holds a run whose headline is implausible — above the
    absolute ceiling, or (same panel only) swinging more than `FAILURE_RATE_JUMP_PP`
    from `last_good`. `last_good` is the currently-committed derived dict, or None on a
    first run. Holding means "retain last-good pending manual confirm", not "discard".
    """
    if not is_valid_derived(derived):
        return False
    rate = _failure_rate(derived)
    if rate is None:
        return False
    if rate > FAILURE_RATE_CEILING_PCT:
        return False
    last_rate = _failure_rate(last_good) if last_good is not None else None
    same_panel = last_good is not None and last_good.get("panel") == derived.get("panel")
    if same_panel and last_rate is not None and abs(rate - last_rate) > FAILURE_RATE_JUMP_PP:
        return False
    return True


def build_history_entry(derived: dict[str, Any], now: datetime) -> dict[str, Any]:
    """One day's aggregate row: date, national failure-rate, per-provider medians.

    The median is over each provider's Sensor Trust Scores — the rollup the provider
    leaderboard and the 90-day trend read. Sensors with no provider group under
    "Unknown"; Sensors with no score are skipped.
    """
    by_provider: dict[str, list[float]] = {}
    for sensor in derived.get("sensors", []):
        score = sensor.get("trust_score")
        if score is None:
            continue
        provider = sensor.get("provider") or "Unknown"
        by_provider.setdefault(provider, []).append(score)

    provider_medians = {
        provider: round(median(scores), 1)
        for provider, scores in sorted(by_provider.items())
    }
    national = derived.get("national", {})
    return {
        "date": now.date().isoformat(),
        "failure_rate_pct": national.get("failure_rate_pct"),
        "sensors_scored": national.get("sensors_scored"),
        # Provenance: the full Panel vs a bounded sample run write to the same history,
        # so the trend can tell an honest full-Panel day from a smoke-test aggregate.
        "panel": derived.get("panel"),
        "provider_medians": provider_medians,
    }


def _entry_date(entry: dict[str, Any]) -> Optional[date]:
    """An entry's ISO date, or None when missing/malformed (a corrupt row we skip)."""
    try:
        return date.fromisoformat(entry["date"])
    except (KeyError, TypeError, ValueError):
        return None


def append_history(history: list[dict[str, Any]], entry: dict[str, Any],
                   retention_days: int = HISTORY_RETENTION_DAYS) -> list[dict[str, Any]]:
    """Append `entry`, replacing any same-date row, then drop rows older than the
    retention window. Idempotent per day: a second run on the same date overwrites
    that day's row rather than duplicating it. Returned rows are sorted by date.

    Malformed existing rows (missing/unparseable date) are dropped rather than raised
    on, so one corrupt row can never abort an otherwise-good run (the module contract).
    """
    entry_date = date.fromisoformat(entry["date"])  # entry is built by us — trusted
    cutoff = entry_date - timedelta(days=retention_days)

    kept = [e for e in history if e.get("date") != entry["date"]
            and (d := _entry_date(e)) is not None and d >= cutoff]
    kept.append(entry)
    kept.sort(key=lambda e: e["date"])
    return kept


def _read_history(path: Path) -> list[dict[str, Any]]:
    """Existing history rows, or [] when absent/corrupt (never abort a good run)."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = data.get("history") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def _read_last_good(path: Path) -> Optional[dict[str, Any]]:
    """The currently-committed derived JSON, or None if absent/corrupt. Used to compare
    a fresh run against last-good for the scary-wrong guard (never aborts a good run)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON via a temp file + os.replace so last-good is never half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def persist_run(derived: Any, now: datetime,
                derived_path: Path = DERIVED_PATH,
                history_path: Path = HISTORY_PATH,
                retention_days: int = HISTORY_RETENTION_DAYS) -> bool:
    """Publish `derived` + append history, but only if it passes the validity gate.

    Returns True when the files were written, False when the run was retained (the
    last-good JSON left untouched). This is the T5 fallback: a failed/empty run does not
    overwrite good data — extended by the F4 scary-wrong guard, which also holds a
    structurally-valid run whose headline is implausible (vs last-good).
    """
    if not is_publishable(derived, _read_last_good(derived_path)):
        return False

    _atomic_write_json(derived_path, derived)

    rows = append_history(_read_history(history_path),
                          build_history_entry(derived, now),
                          retention_days=retention_days)
    _atomic_write_json(history_path, {
        "generated_at": now.isoformat(),
        "retention_days": retention_days,
        "history": rows,
    })
    return True
