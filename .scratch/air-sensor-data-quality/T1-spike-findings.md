# T1 spike findings — OpenAQ v3 cheap path (2026-07-18)

Status: done. Throwaway spike (script not committed — regenerate from the params below; fixtures under `tests/fixtures/openaq/`). Resolves the ADR-0002 plausibility question.

## Acceptance criteria — results

| Criterion | Result |
|---|---|
| Free key works via `X-API-Key` | ✅ `GET /v3/parameters` 200 with the key in `.env` (gitignored). |
| Enumerate US PM2.5 Locations via `/v3/locations` (paginated) | ✅ `GET /v3/locations?countries_id=155&parameters_id=2&limit=1000&page=N`. **5,423 Locations / 5,529 PM2.5 Sensors**, 6 pages. |
| Per-Sensor `datetimeLast` / `percentComplete` / min-max retrieved | ✅ but only from `/v3/sensors/{id}` (the `/v3/locations` list embeds sensors as `{id,name,parameter}` only — no scoring fields). |
| **Plausibility source decided** | ✅ see below — needs a per-Sensor daily-aggregate call. |
| Test fixture captured | ✅ `tests/fixtures/openaq/` (3 files, sanitized, ~52 KB). |
| Rate-limit headers + Panel budget recorded | ✅ below. |

## Decision — plausibility (and completeness) source

`summary.min/max` and `coverage.percentComplete` on the **Sensor object are LIFETIME, not a trailing window** — confirmed across 5 Sensors:

| sensor | coverage window | percentComplete | summary min/max |
|---|---|---|---|
| 268 | 2016-01-30 → 2026-07-18 | 2,963,300% | −4.0 / 123.6 |
| 2071327 | 2022-10-20 → 2026-07-17 | 2,715,000% | −4.9 / 316.8 |
| 2031 | 2016-03-06 → 2026-07-17 | 4,661,700% | −4.9 / 330.1 |

A lifetime min is routinely negative, so plausibility read off the object would fire on nearly every Sensor. **Both plausibility and completeness must be windowed.**

→ **Use one bounded daily-aggregate call per Sensor:** `GET /v3/sensors/{id}/days?date_from=<30d ago>&date_to=<today>`. Its daily `summary.min/max` → window min/max (plausibility); daily `coverage.expectedCount/observedCount` → window completeness. One call covers both. Still an aggregate (not a dense per-measurement pull) → cheap-path thesis (ADR-0002) holds; mechanism corrected there.

**Param gotcha:** `date_from`/`date_to` (`YYYY-MM-DD`) work; `datetime_from`/`datetime_to` are **silently ignored** (return oldest-first history — the trap that made the first probe read 2016 data). Verified: `date_from`/`date_to` returned the trailing 31 days (min 2.8, max 37.0, completeness 99.9%).

Staleness stays the raw 24h check off `datetimeLast` (`/v3/sensors/{id}`, or the newest `/days` record — day-resolution is fine under the deliberately-conservative 24h bar).

## Rate limits (observed headers)

`GET` responses carry the **per-minute** bucket:
```
x-ratelimit-limit: 60      x-ratelimit-used: 5
x-ratelimit-remaining: 55  x-ratelimit-reset: 59   (seconds to reset)
```
Documented ceilings: **60 / minute** and **2,000 / hour** (free tier). 429 on exceed (`retry-after`); repeated abuse can suspend the key. The 2,000/hr ceiling is not surfaced in these headers — track it client-side.

## Full-Panel request budget (~5,529 Sensors)

| Run shape | Calls | Wall-clock @ 2,000/hr |
|---|---|---|
| Enumeration only | ~6 | trivial |
| **Daily scoring, minimal** (enumeration + 1 `/days` per Sensor; staleness from newest `/days` day) | **~5,535** | **~2.8 h** |
| Scoring + precise per-Sensor `datetimeLast` (+1 `/v3/sensors/{id}` per Sensor) | ~11,064 | ~5.5 h |

Implications for T4/T5:
- **Neither run fits one clock-hour** → the cron must **stagger** across ≥3 hours (pace ≈ 30 req/min ⇒ ≤ ~33/min keeps under 2,000/hr and well under 60/min). A daily cadence absorbs this fine.
- Prefer the **minimal** shape: derive staleness from the newest `/days` record → no second per-Sensor call, ~halves the budget.
- Provider **`licenses` ride along free** on each `/v3/locations` list entry (no extra calls for the T4 redistribution filter/attribution).

## Fixtures (`tests/fixtures/openaq/`)
- `locations_us_pm25_page.sample.json` — `/v3/locations` page, 3 Locations (enumeration + licenses/attribution/coords shape).
- `sensor_detail.sample.json` — one `/v3/sensors/{id}` (datetimeLast; lifetime summary/coverage).
- `sensor_days_window.sample.json` — one `/v3/sensors/{id}/days` trailing-30d (windowed min/max + completeness). Regen params in `tests/fixtures/README.md`.
