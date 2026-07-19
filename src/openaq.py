"""OpenAQ v3 access + response parsing.

The parse helpers (`extract_pm25_sensors`, `parse_datetime_last`) are pure functions
over the response shapes the T1 spike pinned (tests/fixtures/openaq/), so scoring is
tested offline. The live HTTP client lives in this module too but is only touched by
`loader.run()` — never by tests.

Shape notes (T1): the `/v3/locations` list embeds sensors as {id,name,parameter} only,
so per-Sensor `datetimeLast` needs a `/v3/sensors/{id}` call. Constants: US
countries_id=155, PM2.5 parameters_id=2."""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

PM25_PARAMETER_ID = 2
US_COUNTRY_ID = 155
BASE_URL = "https://api.openaq.org/v3"

# Kentucky bounding box (ADR-0001: exclude Kentucky/Louisville — COI with LG&E/KU).
# Whole-state extent: lat 36.49–39.15, lon -89.57 (west, the Kentucky Bend) to -81.96
# (east). This rectangle covers all of KY — including Louisville at -85.76 — plus a
# safe-direction sliver of neighboring states; over-exclusion is the correct bias for
# a conflict-of-interest guard.
KY_LAT_MIN, KY_LAT_MAX = 36.49, 39.15
KY_LON_MIN, KY_LON_MAX = -89.57, -81.96


def _is_in_kentucky(latitude: float, longitude: float) -> bool:
    """True if the location is in Kentucky's bounding box (covers Louisville too)."""
    return KY_LAT_MIN <= latitude <= KY_LAT_MAX and KY_LON_MIN <= longitude <= KY_LON_MAX


def should_exclude_location(location: dict[str, Any]) -> bool:
    """True if a Location should be excluded from the Panel (T4 exclusion criteria).

    Exclusions (ADR-0001, ADR-0004):
    1. Any license forbids redistribution (redistributionAllowed: false).
    2. Location is in Kentucky (Louisville included) — conflict of interest, owner at LG&E/KU.
    """
    # Check licenses for redistribution restrictions.
    licenses = location.get("licenses") or []
    for license_obj in licenses:
        if license_obj.get("redistributionAllowed") is False:
            return True

    # Check geographic exclusion: Kentucky (the bounding box includes Louisville).
    coords = location.get("coordinates") or {}
    lat = coords.get("latitude")
    lon = coords.get("longitude")
    if lat is not None and lon is not None:
        if _is_in_kentucky(lat, lon):
            return True

    return False


def extract_pm25_sensors(locations_page: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a `/v3/locations` page into one record per PM2.5 Sensor.

    Each record carries the display context the derived JSON needs (location name,
    provider, coordinates) but NOT any measurement value — raw data is never emitted.
    """
    records: list[dict[str, Any]] = []
    for location in locations_page.get("results", []):
        provider = (location.get("provider") or {}).get("name")
        for sensor in location.get("sensors", []):
            if (sensor.get("parameter") or {}).get("id") != PM25_PARAMETER_ID:
                continue
            if sensor.get("id") is None:  # skip malformed entries rather than abort the run
                continue
            records.append(
                {
                    "sensor_id": sensor["id"],
                    "location": location.get("name"),
                    "provider": provider,
                    "coordinates": location.get("coordinates"),
                }
            )
    return records


def parse_datetime_last(sensor_detail: dict[str, Any]) -> Optional[datetime]:
    """Timezone-aware `datetimeLast` from a `/v3/sensors/{id}` response, or None.

    None means the Sensor has never reported; the loader treats that as stale.
    """
    results = sensor_detail.get("results") or []
    if not results:
        return None
    last = (results[0].get("datetimeLast") or {}).get("utc")
    if not last:
        return None
    # OpenAQ emits "...Z"; fromisoformat handles the offset once Z is normalized.
    return datetime.fromisoformat(last.replace("Z", "+00:00"))


def _parse_utc(node: Optional[dict[str, Any]]) -> Optional[datetime]:
    """Timezone-aware datetime from an OpenAQ `{utc, local}` node, or None."""
    if not node:
        return None
    utc = node.get("utc")
    if not utc:
        return None
    return datetime.fromisoformat(utc.replace("Z", "+00:00"))


def summarize_days_window(days_response: dict[str, Any]) -> dict[str, Any]:
    """Reduce a `/v3/sensors/{id}/days` window to the four scoring inputs.

    One bounded daily-aggregate call yields BOTH windowed completeness AND
    plausibility min/max in a single response (docs/adr/0002). Returns:
      - `datetime_last`   day-resolution last-seen (newest record's coverage end)
      - `percent_complete` sum(observed)/sum(expected) over the window, as a %
      - `window_min` / `window_max`  extremes across the window's daily summaries

    An empty window (Sensor silent all 30 days) => datetime_last None, 0% complete,
    None min/max. Record order is not assumed; last-seen is the max, not the last.
    """
    results = days_response.get("results") or []
    if not results:
        return {"datetime_last": None, "percent_complete": 0.0,
                "window_min": None, "window_max": None}

    expected = observed = 0
    mins: list[float] = []
    maxes: list[float] = []
    last_seen: Optional[datetime] = None
    for record in results:
        coverage = record.get("coverage") or {}
        expected += coverage.get("expectedCount") or 0
        observed += coverage.get("observedCount") or 0

        summary = record.get("summary") or {}
        if summary.get("min") is not None:
            mins.append(summary["min"])
        if summary.get("max") is not None:
            maxes.append(summary["max"])

        # Prefer the coverage end (actual observed span); fall back to the period end.
        day_end = _parse_utc(coverage.get("datetimeTo")) or _parse_utc(
            (record.get("period") or {}).get("datetimeTo"))
        if day_end is not None and (last_seen is None or day_end > last_seen):
            last_seen = day_end

    percent_complete = round(observed / expected * 100, 1) if expected else 0.0
    return {
        "datetime_last": last_seen,
        "percent_complete": percent_complete,
        "window_min": min(mins) if mins else None,
        "window_max": max(maxes) if maxes else None,
    }


def _load_api_key() -> str:
    """Key from the OS env (CI) or the gitignored .env (local). Never from the repo."""
    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("OPENAQ_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if not key:
        raise RuntimeError(
            "OPENAQ_API_KEY not set — put your free key in .env (see .env.example).")
    return key


class OpenAQClient:
    """Live OpenAQ v3 reader (X-API-Key header). Deterministic GETs, no LLM.

    Only used by loader.run(); the test suite injects a fixture-backed fake instead,
    so nothing here runs offline. Rate limits (60/min, 2000/hr) matter at full-Panel
    scale (T4/T5); T2's handful of calls is well under them.

    Stagger strategy (T4): pace at ~30 req/min to stay under 2000/hr and well under
    60/min. Full Panel (~5,535 calls) completes in ~2.8h.
    """

    MAX_429_RETRIES = 3

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30,
                 stagger_interval: float = 2.0):
        import requests  # lazy: keeps the parse helpers importable without requests

        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"X-API-Key": api_key or _load_api_key()})
        self._stagger_interval = stagger_interval  # seconds between requests (~30/min)
        self._last_request_time = 0.0
        self._request_count = 0

    def get_request_count(self) -> int:
        """Total HTTP requests made by this client (rate-limit hygiene telemetry)."""
        return self._request_count

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        # Back off on 429 up to MAX_429_RETRIES times before giving up, so a brief
        # burst of rate-limiting doesn't abort a multi-hour full-Panel run.
        for attempt in range(self.MAX_429_RETRIES + 1):
            # Stagger: apply a minimum interval between requests.
            elapsed_since_last = time.time() - self._last_request_time
            if elapsed_since_last < self._stagger_interval:
                time.sleep(self._stagger_interval - elapsed_since_last)

            self._last_request_time = time.time()
            self._request_count += 1

            resp = self._session.get(f"{BASE_URL}{path}", params=params, timeout=self._timeout)
            if resp.status_code != 429 or attempt == self.MAX_429_RETRIES:
                break
            time.sleep(self._retry_after_seconds(resp))

        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _retry_after_seconds(resp: Any, default: int = 60) -> int:
        """Seconds to wait from a 429 `Retry-After` header. Robust to a non-numeric
        (HTTP-date) header value, which `int()` alone would choke on."""
        raw = resp.headers.get("retry-after")
        if raw is None:
            return default
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return default

    def iter_location_pages(self) -> Iterator[dict[str, Any]]:
        """Yield `/v3/locations` pages of US PM2.5 Locations (all pages, full Panel).

        Paginated iteration over all ~5,423 Locations / 5,529 PM2.5 Sensors.
        Each page carries ~500 Locations (limit tuned per OpenAQ responsiveness).
        """
        page = 1
        limit = 500  # per-page limit for balanced throughput
        while True:
            payload = self._get(
                "/locations",
                {
                    "countries_id": US_COUNTRY_ID,
                    "parameters_id": PM25_PARAMETER_ID,
                    "limit": limit,
                    "page": page,
                },
            )
            if not payload.get("results"):
                return
            yield payload
            page += 1

    def get_sensor_detail(self, sensor_id: int) -> dict[str, Any]:
        """`/v3/sensors/{id}` — lifetime detail (retained; not on the T3 scoring path)."""
        return self._get(f"/sensors/{sensor_id}", {})

    def get_sensor_days(self, sensor_id: int, date_from: str, date_to: str) -> dict[str, Any]:
        """`/v3/sensors/{id}/days` — the one per-Sensor call the Trust Score reads.

        Its daily summaries yield windowed completeness + plausibility min/max +
        day-resolution last-seen. Dates are `YYYY-MM-DD`: the aggregate endpoints
        honor `date_from`/`date_to`; `datetime_from`/`datetime_to` are silently
        ignored (docs/adr/0002). `limit` covers the whole ~30-day window.
        """
        return self._get(
            f"/sensors/{sensor_id}/days",
            {"date_from": date_from, "date_to": date_to, "limit": 400},
        )
