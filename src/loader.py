"""Loader: OpenAQ live -> Trust Score -> derived JSON. T3 ships the full score.

Split into a pure core and a thin live shell so the whole scoring path is tested
offline (docs/adr/0002, docs/adr/0003):
  - build_derived(records, now)      pure: records -> derived dict (national + per-Sensor)
  - collect_and_build(client, now)   orchestration over an injectable client (fixture or live)
  - run()                            wires the live OpenAQClient and writes the JSON file

Each Sensor is scored on three checks (staleness/completeness/plausibility) from one
/v3/sensors/{id}/days call — windowed completeness + plausibility min/max + a
day-resolution last-seen (docs/adr/0002). Only *derived* QA metrics are emitted —
never a raw measurement value (CLAUDE.md hard constraint): the window min/max are
consumed internally for the plausibility check but the published JSON carries only
the pass/fail outcome (in `failed_checks`), not the readings themselves."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from src.openaq import extract_pm25_sensors, summarize_days_window
from src.scoring import (
    COMPLETENESS_FLOOR_PCT,
    PLAUSIBLE_MAX,
    PLAUSIBLE_MIN,
    STALE_HOURS,
    TRUST_WEIGHTS,
    score_sensor,
)

WINDOW_DAYS = 30
PANEL_LABEL = "US PM2.5 (T3 sample)"
ATTRIBUTION = "Air-quality data via OpenAQ and its upstream providers (CC BY 4.0 unless a provider specifies otherwise)."

# Repo-root/data/derived/trust_index.json — committed; raw pulls never are.
DERIVED_PATH = Path(__file__).resolve().parent.parent / "data" / "derived" / "trust_index.json"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _window_bounds(now: datetime, window_days: int = WINDOW_DAYS) -> tuple[str, str]:
    """The trailing `window_days` window as OpenAQ `date_from`/`date_to` (YYYY-MM-DD)."""
    date_to = now.date()
    date_from = date_to - timedelta(days=window_days)
    return date_from.isoformat(), date_to.isoformat()


def build_derived(records: list[dict[str, Any]], now: datetime,
                  weights: dict[str, float] = TRUST_WEIGHTS) -> dict[str, Any]:
    """Score each record's Trust Score and roll up the national failure-rate.

    A record is `{sensor_id, location, provider, datetime_last, percent_complete,
    window_min, window_max}` (datetime_last/min/max may be None for a silent Sensor).
    Output is JSON-serializable. The hero is the share failing >=1 SLA.
    """
    sensors: list[dict[str, Any]] = []
    for r in records:
        result = score_sensor(
            datetime_last=r.get("datetime_last"),
            percent_complete=r.get("percent_complete"),
            window_min=r.get("window_min"),
            window_max=r.get("window_max"),
            now=now,
            weights=weights,
        )
        sensors.append(
            {
                "sensor_id": r["sensor_id"],
                "location": r.get("location"),
                "provider": r.get("provider"),
                "datetime_last": _iso(r.get("datetime_last")),
                "percent_complete": r.get("percent_complete"),
                "trust_score": result["trust_score"],
                "failed_checks": result["failed_checks"],
                "failed_any": result["failed_any"],
            }
        )

    scored = len(sensors)
    failed = sum(1 for s in sensors if s["failed_any"])
    failure_rate = round(failed / scored * 100, 1) if scored else 0.0

    return {
        "generated_at": now.isoformat(),
        "panel": PANEL_LABEL,
        "checks": ["staleness", "completeness", "plausibility"],
        "thresholds": {
            "stale_hours": STALE_HOURS,
            "completeness_floor_pct": COMPLETENESS_FLOOR_PCT,
            "plausible_min": PLAUSIBLE_MIN,
            "plausible_max": PLAUSIBLE_MAX,
        },
        "weights": weights,
        "national": {
            "sensors_scored": scored,
            "sensors_failed": failed,
            "failure_rate_pct": failure_rate,
        },
        "sensors": sensors,
        "attribution": ATTRIBUTION,
    }


def collect_and_build(client: Any, now: datetime, sample_size: int) -> dict[str, Any]:
    """Enumerate a small PM2.5 sample, read each Sensor's /days window, and score.

    `client` supplies `iter_location_pages(sample_size)` and
    `get_sensor_days(id, date_from, date_to)`. Any object with that shape works —
    the live OpenAQClient or a fixture-backed fake.
    """
    date_from, date_to = _window_bounds(now)
    records: list[dict[str, Any]] = []
    for page in client.iter_location_pages(sample_size):
        for record in extract_pm25_sensors(page):
            window = summarize_days_window(
                client.get_sensor_days(record["sensor_id"], date_from, date_to)
            )
            record.update(window)
            records.append(record)
            if len(records) >= sample_size:
                return build_derived(records, now)
    return build_derived(records, now)


def run(sample_size: int = 8) -> dict[str, Any]:
    """Live entry point: read OpenAQ, score, write the derived JSON. Commits no raw data."""
    from src.openaq import OpenAQClient  # local import: tests never hit the network

    now = datetime.now(timezone.utc)
    derived = collect_and_build(OpenAQClient(), now, sample_size)
    DERIVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    DERIVED_PATH.write_text(json.dumps(derived, indent=2), encoding="utf-8")
    return derived


if __name__ == "__main__":
    result = run()
    n = result["national"]
    print(f"Wrote {DERIVED_PATH} — {n['sensors_failed']}/{n['sensors_scored']} failed "
          f">=1 SLA ({n['failure_rate_pct']}%)")
