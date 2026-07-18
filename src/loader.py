"""Loader: OpenAQ live -> score -> derived JSON. T2 ships the staleness slice only.

Split into a pure core and a thin live shell so the whole scoring path is tested
offline (docs/adr/0002, docs/adr/0003):
  - build_derived(records, now)      pure: records -> derived dict (national + per-Sensor)
  - collect_and_build(client, now)   orchestration over an injectable client (fixture or live)
  - run()                            wires the live OpenAQClient and writes the JSON file

Only *derived* QA metrics are emitted — never a raw measurement value (CLAUDE.md hard
constraint). `datetime_last` is reporting metadata, not a reading."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.openaq import extract_pm25_sensors, parse_datetime_last
from src.staleness import is_stale

THRESHOLD_HOURS = 24
PANEL_LABEL = "US PM2.5 (T2 sample)"
ATTRIBUTION = "Air-quality data via OpenAQ and its upstream providers (CC BY 4.0 unless a provider specifies otherwise)."

# Repo-root/data/derived/staleness.json — committed; raw pulls never are.
DERIVED_PATH = Path(__file__).resolve().parent.parent / "data" / "derived" / "staleness.json"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def build_derived(records: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Score each record on staleness and roll up the national stale-rate.

    A record is `{sensor_id, location, provider, datetime_last}` where `datetime_last`
    is a tz-aware datetime or None (never reported => stale). Output is JSON-serializable.
    """
    sensors: list[dict[str, Any]] = []
    for r in records:
        last = r.get("datetime_last")
        stale = last is None or is_stale(last, now, THRESHOLD_HOURS)
        sensors.append(
            {
                "sensor_id": r["sensor_id"],
                "location": r.get("location"),
                "provider": r.get("provider"),
                "datetime_last": _iso(last),
                "stale": stale,
            }
        )

    scored = len(sensors)
    stale_count = sum(1 for s in sensors if s["stale"])
    stale_rate = round(stale_count / scored * 100, 1) if scored else 0.0

    return {
        "generated_at": now.isoformat(),
        "panel": PANEL_LABEL,
        "check": "staleness",
        "threshold_hours": THRESHOLD_HOURS,
        "national": {
            "sensors_scored": scored,
            "stale": stale_count,
            "stale_rate_pct": stale_rate,
        },
        "sensors": sensors,
        "attribution": ATTRIBUTION,
    }


def collect_and_build(client: Any, now: datetime, sample_size: int) -> dict[str, Any]:
    """Enumerate a small PM2.5 sample, fetch each Sensor's `datetimeLast`, and score.

    `client` supplies `iter_location_pages(sample_size)` and `get_sensor_detail(id)`.
    Any object with that shape works — the live OpenAQClient or a fixture-backed fake.
    """
    records: list[dict[str, Any]] = []
    for page in client.iter_location_pages(sample_size):
        for record in extract_pm25_sensors(page):
            record["datetime_last"] = parse_datetime_last(
                client.get_sensor_detail(record["sensor_id"])
            )
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
    print(f"Wrote {DERIVED_PATH} — {n['stale']}/{n['sensors_scored']} stale "
          f"({n['stale_rate_pct']}%)")
