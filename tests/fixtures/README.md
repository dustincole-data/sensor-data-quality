# Test fixtures — OpenAQ v3 (`openaq/`)

Small, sanitized samples of real OpenAQ v3 responses, captured by the T1 spike (2026-07-18) so later loader/scoring tests run **offline with no live calls**. Public data, trimmed; no API key. These are the only OpenAQ payloads committed to the repo — raw pulls stay in gitignored `data/raw/`.

| File | Source request | Trim |
|---|---|---|
| `openaq/locations_us_pm25_page.sample.json` | `GET /v3/locations?countries_id=155&parameters_id=2&limit=3&page=1` | 3 Locations |
| `openaq/sensor_detail.sample.json` | `GET /v3/sensors/{id}` (id 268) | as-is (small) |
| `openaq/sensor_days_window.sample.json` | `GET /v3/sensors/{id}/days?date_from=<30d>&date_to=<today>` (id 268) | trailing ~31 daily records |

## Regenerating

Header `X-API-Key: <free key>` (register at https://explore.openaq.org/register; keep it in gitignored `.env`). Constants: US `countries_id=155`, PM2.5 `parameters_id=2`.

**Gotcha:** the daily-aggregate window uses `date_from`/`date_to` (`YYYY-MM-DD`). `datetime_from`/`datetime_to` are silently ignored and return oldest-first history. See `.scratch/air-sensor-data-quality/T1-spike-findings.md`.

Field notes for whoever writes the loader:
- The `/v3/locations` list embeds sensors as `{id, name, parameter}` only — **no** `datetimeLast`/`coverage`/`summary`.
- `/v3/sensors/{id}` `summary` and `coverage` are **lifetime**, not windowed — do not score off them; use the `/days` window (see the findings note / ADR-0002).
