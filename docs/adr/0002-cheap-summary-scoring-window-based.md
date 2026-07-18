# Score from cheap summary endpoints; window-based; defer dense-series checks

The Trust Score is computed only from OpenAQ's per-Sensor summary/coverage fields (`datetimeLast`, `coverage.percentComplete`, summary min/max) — no dense per-measurement pulls — so a daily scan of the US Panel stays within OpenAQ's 2,000 req/hr limit at $0 infra.

Completeness is scored over a **fixed trailing window (30 days)** rather than raw last-seen, because OpenAQ can ingest measurements out of chronological order; window-based scoring measures the Sensor's reporting health, not OpenAQ's ingestion lag. (Staleness stays a raw last-seen check but with a deliberately conservative 24h bar to shrug off that lag.)

Two richer checks that would need dense per-measurement series or a neighbor graph — **flatline detection** and **cross-sensor consistency** — are deferred to v2 to preserve the cheap-summary budget.

## Update — T1 spike outcome (2026-07-18)

The live spike settled the open plausibility question and corrected the *mechanism* (the cheap-path thesis still holds):

- The per-Sensor **object** fields (`/v3/sensors/{id}` `summary.min/max` and `coverage.percentComplete`) are **lifetime, not windowed** — confirmed across 5 sensors: coverage windows span the Sensor's whole history (2016/2022 → now) and `percentComplete` reads in the millions of percent (e.g. 2,963,300%). A lifetime `summary.min` is routinely negative (−4 to −5 µg/m³), so a plausibility check read off it would fire on almost every Sensor. **Neither plausibility nor completeness can come from the object's summary/coverage.**
- **Decision:** score the window from **one bounded daily-aggregate call per Sensor** — `GET /v3/sensors/{id}/days?date_from=<30d ago>&date_to=<today>` — whose daily `summary.min/max` and `coverage.expected/observedCount` yield **both** windowed plausibility min/max **and** windowed completeness in a single response. This is still a summary/aggregate call (not a dense per-measurement pull), so the cheap-summary budget survives.
- **Param gotcha:** the aggregate endpoints honor `date_from`/`date_to` (`YYYY-MM-DD`); `datetime_from`/`datetime_to` are **silently ignored** (return oldest-first history). Use `date_from`/`date_to`.
- **Staleness** stays the raw-last-seen 24h check off `datetimeLast` (from `/v3/sensors/{id}` or the newest `/days` record).
- **Cost:** enumeration ≈ 6 calls + ~1 call/Sensor ≈ **~5.5k calls** for the ~5,529-Sensor Panel ≈ **~2.8 h** staggered under the 2,000/hr cap (does not fit one clock-hour). Provider `licenses` ride along free on the `/v3/locations` list. Full budget: `.scratch/air-sensor-data-quality/T1-spike-findings.md`.
