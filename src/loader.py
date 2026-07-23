"""Loader: OpenAQ live -> Trust Score -> derived JSON. T4 scales to full Panel.

Split into a pure core and a thin live shell so the whole scoring path is tested
offline (docs/adr/0002, docs/adr/0003):
  - build_derived(records, now, ...)   pure: records -> derived dict (national + per-Sensor)
  - collect_and_build(client, now, ...)   orchestration over an injectable client
  - run()                               wires the live OpenAQClient and writes the JSON file

Each Sensor is scored on four checks (staleness/completeness/plausibility/drift) from
one /v3/sensors/{id}/days call — windowed completeness + plausibility min/max + a
day-resolution last-seen + the per-day mean series (docs/adr/0002, docs/adr/0006). Only
*derived* QA metrics are emitted —
never a raw measurement value (CLAUDE.md hard constraint). Full Panel ~5,529 Sensors,
excluding restricted-license providers (ADR-0004; the Kentucky/Louisville exclusion was
removed 2026-07-20, ADR-0001 superseded)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.openaq import extract_pm25_sensors, should_exclude_location, summarize_days_window
from src.persist import DERIVED_PATH, persist_run
from src.scoring import (
    CHECKS,
    COMPLETENESS_FLOOR_PCT,
    DRIFT_MIN_BASELINE_DAYS,
    DRIFT_RECENT_DAYS,
    DRIFT_Z,
    PLAUSIBLE_MAX,
    PLAUSIBLE_MIN,
    STALE_HOURS,
    TRUST_WEIGHTS,
    WEIGHTS_NOTE,
    plausibility_reason,
    score_sensor,
)

WINDOW_DAYS = 30
# Honest scope (ADR-0007): the panel is the set of US PM2.5 feeds OpenAQ redistributes —
# low-cost/hobbyist-heavy, NOT "the US air-sensor network." The old "(live full panel)"
# label sat a pulsing live-dot over a graveyard (23% last reported >1yr ago), so it's
# dropped: liveness is now stated as a count, not asserted by the label.
PANEL_LABEL = "US PM2.5 sensors redistributed by OpenAQ"
OPENAQ_ATTRIBUTION = "OpenAQ (CC BY 4.0)"

# A Sensor silent longer than this — or one that never reported — is DARK: pulled OUT of
# the *scored* population and counted, not scored (ADR-0007). 7 days is a weekly-heartbeat
# bar, far more conservative than the 24h Staleness check, so a merely-stale-but-alive
# Sensor still scores (as flawed, on Staleness). The split is deliberately robust to the
# exact window: the panel is bimodal (most Sensors report within a day, then a long tail of
# multi-year-dead hardware), so 7d vs 30d moves the dark share only ~1pp.
DARK_AFTER_HOURS = 168

# Abort-resilience (A1 F3): a single persistently-bad Sensor (non-retryable 4xx, or a 5xx
# past the client's retries) must never abort a ~3h full-Panel run — it is skipped and
# counted. But a *flood* of failures is a systemic upstream outage, not one bad Sensor:
# past this ceiling the run aborts so persist_run retains last-good rather than publishing a
# garbage panel. ~50 is well under 1% of the ~5.5k Panel yet far above any plausible handful.
MAX_SKIPPED_SENSORS = 50


def _panel_label(sample_size: Optional[int]) -> str:
    """Honest label: the full Panel, or a bounded live sample of N Sensors."""
    if sample_size is None:
        return PANEL_LABEL
    return f"US PM2.5 (live sample of {sample_size})"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _window_bounds(now: datetime, window_days: int = WINDOW_DAYS) -> tuple[str, str]:
    """The trailing `window_days` window as OpenAQ `date_from`/`date_to` (YYYY-MM-DD)."""
    date_to = now.date()
    date_from = date_to - timedelta(days=window_days)
    return date_from.isoformat(), date_to.isoformat()


def _age_hours(datetime_last_iso: Optional[str], now: datetime) -> Optional[float]:
    """Hours since a Sensor's last report, from its published ISO `datetime_last`
    (None if it never reported)."""
    if not datetime_last_iso:
        return None
    return (now - datetime.fromisoformat(datetime_last_iso)).total_seconds() / 3600.0


def _is_dark(row: dict[str, Any], now: datetime, dark_after_hours: float) -> bool:
    """Dark = never reported, or silent past the dark window (ADR-0007). Dark Sensors are
    counted, not scored: we have no recent data to judge their reporting health."""
    age = _age_hours(row.get("datetime_last"), now)
    return age is None or age > dark_after_hours


def _site_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """The physical-site key for dedup: coordinates rounded to 4dp + provider. A Sensor
    with no coordinates can't be a coordinate duplicate, so it keys on its own id (kept as
    its own site)."""
    c = row.get("coordinates")
    if not c or c.get("latitude") is None or c.get("longitude") is None:
        return ("id", row["sensor_id"])
    return (round(c["latitude"], 4), round(c["longitude"], 4), row.get("provider"))


def dedup_to_sites(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Collapse Sensor rows to physical sites (coord@4dp + provider), keeping the
    most-recently-reporting row of each (ADR-0007). One site's hardware-swap history
    (e.g. 'Millvale' x86 rows at one coordinate) is ONE site, not 86 instruments — deduped
    before any count so a single dead site can't set a rollup or inflate the denominator.
    Insertion order is preserved (dict grouping) so a deduped panel keeps a stable order."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_site_key(row), []).append(row)

    _oldest = datetime.min.replace(tzinfo=timezone.utc)

    def _reported_at(row: dict[str, Any]) -> datetime:
        dt = row.get("datetime_last")
        return datetime.fromisoformat(dt) if dt else _oldest

    return [max(group, key=_reported_at) for group in groups.values()]


def _finalize_panel(scored: list[dict[str, Any]], now: datetime,
                    dark_after_hours: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Correct the population before any count (ADR-0007): dedup scored Sensor rows to
    physical sites, tag each dark + status (clean | flawed | dark), and roll up the national
    decomposition. Only Sensors that actually report are "scored"; the headline splits into
    clean / reporting-but-flawed / dark instead of one blob. Shared by build_derived (fresh
    scoring) and the one-time reprocessor (existing JSON) so both emit identical structure."""
    raw_rows = len(scored)
    sites = dedup_to_sites(scored, now)
    for s in sites:
        s["dark"] = _is_dark(s, now, dark_after_hours)
        s["status"] = "dark" if s["dark"] else ("flawed" if s["failed_any"] else "clean")

    live = [s for s in sites if not s["dark"]]
    dark_rows = [s for s in sites if s["dark"]]
    clean = [s for s in live if not s["failed_any"]]
    flawed = [s for s in live if s["failed_any"]]
    n_sites, n_live = len(sites), len(live)
    _pct = lambda part: round(len(part) / n_sites * 100, 1) if n_sites else 0.0

    national = {
        # "Scored" = Sensors that actually report; dark Sensors are counted separately.
        "sensors_scored": n_live,
        "sensors_failed": len(flawed),
        # The live-only failure rate — the number that survives the "zombie census" attack.
        "failure_rate_pct": round(len(flawed) / n_live * 100, 1) if n_live else 0.0,
        # The three honest buckets (share of all physical sites) + the counts they read.
        "sites_total": n_sites,
        "live": n_live,
        "dark": len(dark_rows),
        "clean": len(clean),
        "flawed": len(flawed),
        "clean_pct": _pct(clean),
        "flawed_pct": _pct(flawed),
        "dark_pct": _pct(dark_rows),
        # Pre-dedup Sensor rows, disclosed so the dedup is auditable.
        "raw_rows": raw_rows,
        "dark_after_hours": dark_after_hours,
    }
    return sites, national


def build_derived(records: list[dict[str, Any]], now: datetime,
                  weights: dict[str, float] = TRUST_WEIGHTS,
                  excluded_by_redistribution: int = 0,
                  panel_label: str = PANEL_LABEL,
                  skipped: int = 0,
                  dark_after_hours: float = DARK_AFTER_HOURS) -> dict[str, Any]:
    """Score each record's Trust Score and roll up the national failure-rate.

    A record is `{sensor_id, location, provider, datetime_last, percent_complete,
    window_min, window_max, daily_means}` (datetime_last/min/max may be None and
    daily_means empty for a silent Sensor). Output is JSON-serializable. The hero is the
    share failing >=1 check.
    The redistribution-policy exclusion count is tracked for transparency (ADR-0004).
    """
    sensors: list[dict[str, Any]] = []
    for r in records:
        result = score_sensor(
            datetime_last=r.get("datetime_last"),
            percent_complete=r.get("percent_complete"),
            window_min=r.get("window_min"),
            window_max=r.get("window_max"),
            now=now,
            daily_means=r.get("daily_means"),
            weights=weights,
        )
        sensors.append(
            {
                "sensor_id": r["sensor_id"],
                "location": r.get("location"),
                "provider": r.get("provider"),
                "provider_attribution": r.get("provider_attribution"),
                # Location coordinates drive the hero map (ADR-0005). null => the
                # Sensor is unmappable: excluded from the map, still scored + counted.
                "coordinates": r.get("coordinates"),
                "datetime_last": _iso(r.get("datetime_last")),
                "percent_complete": r.get("percent_complete"),
                "trust_score": result["trust_score"],
                "failed_checks": result["failed_checks"],
                "failed_any": result["failed_any"],
                # A derived label for WHICH plausibility bound broke (A1 F9) — auditable
                # without ever emitting the raw window min/max measurement values.
                "plausibility_reason": plausibility_reason(
                    r.get("window_min"), r.get("window_max")),
            }
        )

    sites, national = _finalize_panel(sensors, now, dark_after_hours)

    result = {
        "generated_at": now.isoformat(),
        "panel": panel_label,
        "checks": list(CHECKS),
        "thresholds": {
            "stale_hours": STALE_HOURS,
            "completeness_floor_pct": COMPLETENESS_FLOOR_PCT,
            "plausible_min": PLAUSIBLE_MIN,
            "plausible_max": PLAUSIBLE_MAX,
            "drift_z": DRIFT_Z,
            "drift_recent_days": DRIFT_RECENT_DAYS,
            "drift_min_baseline_days": DRIFT_MIN_BASELINE_DAYS,
        },
        "weights": weights,
        "weights_note": WEIGHTS_NOTE,
        "exclusions": {
            "by_redistribution_policy": excluded_by_redistribution,
        },
        "national": national,
        # Sensors dropped this run after a per-Sensor fetch failure (A1 F3). Surfaced so a
        # partial run is visible/auditable rather than silently thinning the Panel.
        "skipped": skipped,
        # Deduped to physical sites, each tagged status = clean | flawed | dark.
        "sensors": sites,
        "attribution": OPENAQ_ATTRIBUTION,
    }
    return result


def _get_provider_attribution(location: dict[str, Any]) -> Optional[str]:
    """Extract the upstream provider's name from licenses (for dual attribution).

    Licenses may carry `attribution.name` (the upstream provider's name). The
    OpenAQ attribution (`attribution`) is fixed. Returns the upstream provider name or None.
    """
    licenses = location.get("licenses") or []
    for lic in licenses:
        attr = lic.get("attribution")
        if attr and attr.get("name"):
            return attr["name"]
    return None


def collect_and_build(client: Any, now: datetime,
                      sample_size: Optional[int] = None) -> dict[str, Any]:
    """Enumerate US PM2.5 Sensors (full Panel or a sample), apply exclusions, score.

    `sample_size` limits the count (for testing); None means exhaustive iteration.
    `client` supplies `iter_location_pages()` and `get_sensor_days(id, date_from, date_to)`.
    Any object with that shape works — the live OpenAQClient or a fixture-backed fake.

    Exclusions (ADR-0004):
    - Locations where any license forbids redistribution (redistributionAllowed: false)

    Each Sensor carries dual attribution: upstream provider + OpenAQ.
    """
    date_from, date_to = _window_bounds(now)
    records: list[dict[str, Any]] = []
    excluded_by_redistribution = 0
    skipped = 0

    for page in client.iter_location_pages():
        for location in page.get("results", []):
            # Apply the T4 exclusion criterion. Counts are Sensor-level (the Panel is a
            # set of Sensors), so count the PM2.5 Sensors in an excluded Location, not
            # the Location itself.
            if should_exclude_location(location):
                excluded_by_redistribution += len(
                    extract_pm25_sensors({"results": [location]}))
                continue

            # Extract PM2.5 Sensors from this Location.
            for record in extract_pm25_sensors({"results": [location]}):
                # Get the 30-day window for this Sensor. A single Sensor's fetch failure
                # (non-retryable 4xx, or a 5xx past the client's retries) must never abort
                # the whole ~3h run — skip it, count it, continue (A1 F3, 2026-07-20).
                # Broad by design: any per-Sensor error (HTTP, JSON, parse) costs one
                # Sensor, not the run. A flood past the ceiling is a systemic outage —
                # abort so persist_run keeps last-good instead of publishing a thin Panel.
                try:
                    window = summarize_days_window(
                        client.get_sensor_days(record["sensor_id"], date_from, date_to)
                    )
                except Exception as exc:
                    skipped += 1
                    if skipped > MAX_SKIPPED_SENSORS:
                        raise RuntimeError(
                            f"aborting run: {skipped} Sensors skipped after fetch failures "
                            f"(> {MAX_SKIPPED_SENSORS} ceiling) — likely a systemic upstream "
                            f"outage, not one bad Sensor") from exc
                    continue
                # extract_pm25_sensors set datetime_last from the Location's minute-
                # resolution datetimeLast (A1 F5). Prefer it over the /days day-resolution
                # coverage end, which update(window) carries as the fallback when a
                # Location omits its last-seen.
                station_last_seen = record.get("datetime_last")
                record.update(window)
                if station_last_seen is not None:
                    record["datetime_last"] = station_last_seen
                # Add provider attribution (dual: upstream provider + OpenAQ).
                record["provider_attribution"] = _get_provider_attribution(location)
                records.append(record)

                # Stop if sample_size reached (for testing).
                if sample_size is not None and len(records) >= sample_size:
                    return build_derived(
                        records, now,
                        excluded_by_redistribution=excluded_by_redistribution,
                        panel_label=_panel_label(sample_size),
                        skipped=skipped,
                    )

    return build_derived(
        records, now,
        excluded_by_redistribution=excluded_by_redistribution,
        panel_label=_panel_label(sample_size),
        skipped=skipped,
    )


def run(sample_size: Optional[int] = None) -> dict[str, Any]:
    """Live entry point: read OpenAQ full Panel, score, safely publish derived JSON.

    sample_size: for testing/smoke runs, cap at this many Sensors (None = exhaustive).
    Commits no raw data. Records the actual wall-clock run duration for rate-limit
    hygiene monitoring (the full ~5.5k-call run must stay staggered under 2000/hr).

    Publishing is guarded by persist_run: an empty or malformed result retains the
    last-good JSON instead of overwriting it, and a rolling 90-day history is
    appended on every good run (T5). Returns the derived dict either way.
    """
    import time
    from src.openaq import OpenAQClient  # local import: tests never hit the network

    now = datetime.now(timezone.utc)
    start = time.time()
    client = OpenAQClient()
    derived = collect_and_build(client, now, sample_size=sample_size)
    # Duration + call count must be measured AFTER the run completes, not at call
    # time (they together show the run stayed staggered under 2000/hr).
    derived["run_duration_seconds"] = round(time.time() - start, 1)
    derived["http_calls"] = client.get_request_count()

    written = persist_run(derived, now)
    # Publish decision for the CLI summary. Set AFTER the atomic write so it never lands
    # in the committed JSON (in-memory only) — lets __main__ report Wrote vs RETAINED
    # honestly now that a structurally-valid run can still be held by the F4 guard.
    derived["published"] = written
    return derived


if __name__ == "__main__":
    import os

    # SAMPLE_SIZE lets the manual workflow_dispatch run a quick smoke test (N Sensors);
    # the daily cron leaves it unset for the full Panel.
    _raw = os.environ.get("SAMPLE_SIZE", "").strip()
    if _raw and not _raw.isdigit():
        raise SystemExit(f"SAMPLE_SIZE must be a positive integer or blank, got {_raw!r}")
    result = run(sample_size=int(_raw) if _raw else None)
    n = result["national"]
    e = result.get("exclusions", {})
    d = result.get("run_duration_seconds", "?")
    if result.get("published"):
        print(f"Wrote {DERIVED_PATH}")
    else:
        print(f"RETAINED last-good {DERIVED_PATH} — empty/invalid or implausible result, "
              f"not overwritten (F4 guard)")
    print(f"  Sites: {n['sites_total']} physical ({n['raw_rows']} raw rows deduped)")
    print(f"  Live {n['live']}: clean {n['clean']} ({n['clean_pct']}%) / "
          f"flawed {n['flawed']} ({n['flawed_pct']}%)  |  dark {n['dark']} ({n['dark_pct']}%)")
    print(f"  Live failure rate: {n['sensors_failed']}/{n['sensors_scored']} = {n['failure_rate_pct']}%")
    print(f"  Excluded: {e.get('by_redistribution_policy', 0)} by policy")
    print(f"  {result.get('http_calls', '?')} HTTP calls in {d}s")
