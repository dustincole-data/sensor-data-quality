# Tickets: Can you trust the US air-sensor network's data?

Vertical tracer-bullet tickets for the OpenAQ Sensor Data-Quality Monitor. Source spec: `.scratch/air-sensor-data-quality/PRD.md`. Glossary: `CONTEXT.md`. Decisions: `docs/adr/0001`–`0005`. All tickets are agent-grabbable (`ready-for-agent`) by construction.

Work the **frontier**: any ticket whose blockers are all done. This is a linear chain (T1 → T7), so top to bottom. Run `/implement` one ticket at a time, **clearing context between tickets**.

## T1 — Spike: confirm the cheap data path

**What to build:** A throwaway spike that proves the loader can get everything the Trust Score needs from OpenAQ's cheap summary endpoints, and pins the one open data-source question. Not user-facing.

**Blocked by:** None — can start immediately. **DONE 2026-07-18** — findings: `.scratch/air-sensor-data-quality/T1-spike-findings.md`; decision in `docs/adr/0002`.

- [x] A registered OpenAQ v3 free key works via the `X-API-Key` header (key kept out of the repo, in a gitignored `.env`).
- [x] The spike enumerates US PM2.5 Locations via `/v3/locations` (paginated) and, for a sample, retrieves `datetimeLast`, `coverage.percentComplete`, and summary min/max. — 5,423 Locations / 5,529 Sensors; scoring fields come from `/v3/sensors/{id}`, not the list.
- [x] **Decision recorded** (ADR-0002 update): `summary`/`coverage` on the Sensor object are **lifetime, not windowed** → plausibility *and* completeness need one bounded per-Sensor daily-aggregate call (`/v3/sensors/{id}/days?date_from&date_to`); ~1 call/Sensor, cheap-path budget holds.
- [x] A representative OpenAQ response is captured as a committed **test fixture** (small, sanitized) for later offline tests. — `tests/fixtures/openaq/` (3 files).
- [x] Observed rate-limit headers + a rough full-Panel request-budget estimate are written down. — 60/min + 2,000/hr; ~5.5k calls ≈ 2.8 h staggered for the daily run.

## T2 — One metric, end-to-end

**What to build:** The thinnest complete path: score a small US PM2.5 sample on **staleness only**, publish derived JSON, and show the result on a local `preview.html`. Proves loader → score → JSON → page.

**Blocked by:** T1. **DONE 2026-07-18** — commit `8a604f6`; `src/` + `preview.html` + `data/derived/staleness.json` (sample: 2/8 stale). 19 tests pass offline.

- [x] A **pure** staleness function returns pass/fail from `datetimeLast` + `now`; unit tests cover the 24h boundary (e.g. 23h passes, 25h fails). — `src/staleness.py::is_stale` (strictly-greater 24h).
- [x] The loader writes derived JSON (national stale-rate + per-Sensor stale flag) for the sample, reading OpenAQ live but **committing no raw data**. — `src/loader.py`; emits `datetime_last` metadata + flags only, no measurement values.
- [x] `preview.html` fetches the derived JSON and shows *"X% of these sensors are stale"* plus the sensor list.
- [x] Tests run offline against the T1 fixture (no live calls). — fixture/paged fake clients in `tests/`.

## T3 — Full Trust Score

**What to build:** Complete the scoring: add completeness + plausibility, produce the graded 0–100 Trust Score and the "failed ≥1 SLA" flag; surface the real hero number and a per-Sensor score table.

**Blocked by:** T2. **DONE 2026-07-18** — `src/scoring.py` (pure Trust Score) + loader/openaq wired to one `/v3/sensors/{id}/days` call per Sensor; `data/derived/trust_index.json` + `preview.html` (hero 71.4% on an illustrative sample). 47 tests pass offline.

- [x] The pure scoring function returns all three checks + graded Trust Score; unit tests cover each boundary (23h/25h; 89%/91%; −1, 1000, 1001), the score math, and "failed ≥1 SLA". — `src/scoring.py`; `tests/test_scoring.py`.
- [x] Derived JSON carries per-Sensor `trust_score` + `failed_checks[]` and the national failure-rate. — `src/loader.py::build_derived`; raw window min/max stay internal (never published).
- [x] `preview.html` shows the hero failure-rate % and a per-Sensor Trust Score table. — worst-first, color-banded scores + failed-check badges.
- [x] Trust-Score weights live in one config value (tunable). — `src/scoring.py::TRUST_WEIGHTS` (0.40/0.40/0.20), emitted in the JSON.

## T4 — Full Panel + licensing/exclusions

**What to build:** Scale from sample to the whole US PM2.5 Panel, with honest exclusions and rate-limit hygiene.

**Blocked by:** T3.

- [ ] The loader enumerates and scores the full US PM2.5 Panel via pagination.
- [ ] `/v3/licenses` is read; Sensors from `redistributionAllowed:false` providers are excluded; Kentucky/Louisville Sensors are excluded; both excluded counts appear in the JSON.
- [ ] Every displayed Sensor carries provider + OpenAQ attribution.
- [ ] Requests back off on 429 and stagger to stay within 2,000/hr; the full run completes within limits (duration recorded).

## T5 — Daily automation + history + fallback

**What to build:** Make it self-updating and durable, on the public repo.

**Blocked by:** T4.

- [ ] The **public GitHub repo** is created and pushed.
- [ ] A daily GitHub Actions cron runs the loader and commits the updated derived JSON.
- [ ] A 90-day aggregate history (failure-rate + per-provider medians) is appended each run.
- [ ] On loader failure or empty result, the last-good JSON is retained (a simulated failure does not overwrite with a broken/empty file).

## T6 — Real page: map hero + leaderboard + table + trend

**What to build:** The production page on the dustincole_data site.

**Blocked by:** T5.

- [ ] An Astro route on dustincole_data renders, from the derived JSON raw URL: the US **map** (bundled basemap, Sensors colored by Trust Score), the provider **leaderboard**, a searchable per-Sensor **table**, and the 90-day **trend**.
- [ ] Sensors with `coordinates:null` are excluded from the map but counted in aggregates, and the unmappable count is disclosed.
- [ ] The page is legible on mobile, makes **no external tile/network requests** (CSP-safe), and Lighthouse mobile is ≥ the site's ~91 baseline.

## T7 — Methodology + disclaimer + framing + ship

**What to build:** The framing that keeps it in-lane, plus the ship artifacts.

**Blocked by:** T6.

- [ ] A methodology section states the check definitions, thresholds, the out-of-order-ingestion caveat, and the honest denominator (excluded counts).
- [ ] A prominent disclaimer states this is **data health, not air quality and not sensor accuracy**.
- [ ] The H1 is the question; the slug is confirmed against the site's IA.
- [ ] A README-skim and a 1-page exec memo (the competency this proves) are written; dual attribution is present; the COI self-screen passes (no Kentucky/facility commentary).
- [ ] The page is live.
