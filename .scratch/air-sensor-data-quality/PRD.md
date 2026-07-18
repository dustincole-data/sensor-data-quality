# Spec: Can you trust the US air-sensor network's data?

Status: ready-for-agent

A public data-quality monitor that scores the reporting health of US PM2.5 air-quality Sensors in OpenAQ, published as the "Can you trust the US air-sensor network's data?" page on dustincoledata.com. Source of truth for feasibility: the research dossier (`C:\Users\dusti\brain\raw\sources\2026-07-17 Public Data Project Selection for dustincoledata Research.md`). Glossary: `CONTEXT.md`. Decisions: `docs/adr/0001`–`0005`.

## Problem Statement

People treat public air-quality numbers as fact, but a sensor feed can be stale, incomplete, or reporting garbage — and nobody publishes whether a given sensor's *data* can be trusted. A reader (or a technical peer evaluating the owner's data-quality skill) has no way to see, at a glance, how trustworthy the reporting behavior of the US air-sensor network actually is, or which networks run clean feeds versus flaky ones.

## Solution

A single public page that answers "can you trust the US air-sensor network's data?" with:

- one headline number — the share of US PM2.5 Sensors that failed at least one basic data-quality check in the last 30 days — over a 90-day trend, shown on a US map shaded by Sensor Trust Score;
- a provider leaderboard ranking networks from healthiest to flakiest feeds;
- a searchable per-Sensor table exposing each Sensor's Trust Score and which checks it failed;
- a methodology + disclaimer section making explicit that this scores **data health, not air quality and not sensor accuracy**.

Behind it, a daily loader pulls OpenAQ's summary fields, computes deterministic Trust Scores, and publishes small derived JSON. Raw data is never committed; the whole thing runs on free rails at $0.

## User Stories

1. As a reader, I want one plain headline number, so that I immediately grasp how much of the US air-sensor network reports untrustworthy data.
2. As a reader, I want a US map shaded by Sensor Trust Score, so that I can see where reporting is healthy versus flaky at a glance.
3. As a reader, I want the headline paired with a 90-day trend, so that I can see whether feed health is improving or degrading.
4. As a reader, I want a provider leaderboard, so that I can see which networks run clean feeds and which don't.
5. As a reader, I want to search a specific Sensor and see its Trust Score, so that I can check a monitor I care about.
6. As a reader, I want each Sensor to show *which* checks it failed (staleness, completeness, plausibility), so that "untrustworthy" is concrete, not a black box.
7. As a skeptical technical peer, I want the exact check definitions and thresholds published, so that I can judge whether the methodology is sound.
8. As a skeptical technical peer, I want an explicit statement that scoring is robust to OpenAQ's out-of-order ingestion, so that I trust the score measures the Sensor, not the pipeline.
9. As a hiring manager, I want the page to read as data-observability engineering (SLAs, completeness, drift, freshness at fleet scale), so that it demonstrates the owner's data-quality competency.
10. As a reader who might misread it, I want a prominent disclaimer that this is not an air-quality index and not a sensor-accuracy judgment, so that I don't draw health or calibration conclusions.
11. As a data provider, I want my network and OpenAQ both attributed wherever my Sensors appear, so that licensing terms are honored.
12. As the owner, I want the panel to exclude Kentucky/Louisville Sensors, so that I never publicly grade Sensors near my employer's facilities (COI).
13. As the owner, I want the page to update itself daily with no manual step, so that it stays live without maintenance.
14. As the owner, I want the pipeline to degrade gracefully if OpenAQ changes or a provider drops out, so that the page shows last-good data instead of breaking.
15. As the owner, I want the whole thing to cost $0 in infra and runtime LLM, so that it's sustainable indefinitely.
16. As the owner, I want raw measurements never committed to the repo, so that the repo stays small and I'm only publishing derived metrics.
17. As a reader on mobile, I want the map and tables to be legible on a small screen, so that the page works everywhere.
18. As a reader, I want to know how many Sensors were excluded (unmappable coordinates, restricted-license providers), so that the denominator is honest.

## Implementation Decisions

- **Panel** (ADR-0001): US PM2.5 Sensors only, excluding Kentucky/Louisville; reference-grade and low-cost both included. Global and other pollutants are v2.
- **Data source**: OpenAQ API v3, free key in `X-API-Key` header. Enumerate the Panel via `/v3/locations` (US, PM2.5), read per-Sensor `datetimeLast` + `coverage.percentComplete` + summary min/max. No dense per-measurement pulls (ADR-0002).
- **Three checks (SLAs)** per Sensor:
  - *Staleness*: FAIL if no data in the last 24h (conservative, robust to ingestion lag).
  - *Completeness*: FAIL if trailing-30-day `percentComplete` < 90% (window-based, ADR-0002).
  - *Plausibility*: FAIL if window min < 0 or max > 1000 µg/m³.
- **Trust Score** (0–100, graded, tunable weights): `100 × (0.40·completeness_component + 0.40·staleness_component + 0.20·plausibility_component)`, where completeness_component = `percentComplete/100`, staleness_component = `clamp(1 − hours_since_last/24, 0, 1)`, plausibility_component = 1 if within `[0,1000]` else 0. **Hero** = share of Panel Sensors that FAIL ≥1 SLA. Weights are an explicit tunable knob.
- **Licensing** (ADR-0004): read `/v3/licenses`; fully exclude Sensors whose provider sets `redistributionAllowed:false`; dual-attribute provider + OpenAQ everywhere; disclose the excluded count.
- **Output**: small derived JSON in-repo under `data/derived/` — (a) national aggregate + 90-day history of the failure-rate and per-provider medians, (b) per-provider leaderboard rollup, (c) per-Sensor current scores + failed checks + coordinates. Raw pulls stay in gitignored `data/raw/` (ADR-0003).
- **Automation** (ADR-0003): daily GitHub Actions cron (~06:00 ET) in this public repo; health-check + last-good fallback so a bad run never publishes a broken/empty file.
- **Page** (ADR-0005): static Astro route on the dustincole_data site (Vercel Hobby), fetching the derived JSON by raw URL. Hero = US map from a **bundled** basemap (no external tiles); Sensors with `coordinates:null` excluded from the map but counted in aggregates. Then leaderboard, per-Sensor table, methodology + disclaimer.
- **Framing**: name = the question; slug `/air-sensor-data-quality`; every statement a data-quality statement — never pollution/health/accuracy.

## Testing Decisions

- **Good test = external behavior, not implementation.** Assert on inputs→outputs, not internal calls.
- **Primary seam (the one that matters): the pure scoring function** — given a Sensor's summary fields (`datetimeLast`, `percentComplete`, min, max, `now`), it returns the three pass/fail results and the graded Trust Score. Fully deterministic, no I/O — the whole domain is testable here. Cover: each check's pass/fail boundary (23h vs 25h; 89% vs 91%; −1, 1000, 1001), the graded score math, and "failed ≥1 SLA".
- **Thin integration seam: the loader** — run it against a **recorded OpenAQ fixture** (captured sample response, committed as a test fixture), asserting it produces the expected derived-JSON shape and excludes restricted/KY Sensors. No live network calls in tests.
- **Aggregation**: test national failure-rate and per-provider rollup from a small hand-built set of scored Sensors.
- **Page**: minimal — renders headline, map, leaderboard, table from a fixture derived-JSON without error; not a full visual regression.
- **Prior art**: the Fanbase pipeline's deterministic scoring (VADER/AFINN) is tested the same pure-function way — mirror that shape.

## Out of Scope

- Any air-quality, health, or pollution-level claim; any sensor-accuracy / calibration judgment.
- Flatline detection and cross-sensor consistency (v2 — need dense series / neighbor graph).
- Pollutants other than PM2.5; countries other than the US; Kentucky/Louisville Sensors.
- Real-time or sub-daily updates; a database or server; external map tile services.
- Historical per-Sensor score history (only aggregates get a 90-day trend; per-Sensor is current-only).

## Further Notes

- **Spike dependency**: the cheapest source for the plausibility window min/max needs confirming against the live API — if OpenAQ's `summary` isn't a trailing-window figure, plausibility needs one bounded per-Sensor daily-aggregate call, else it slips to v1.1 and we ship staleness + completeness first (ADR-0002).
- **Slug** `/air-sensor-data-quality` to be confirmed against the dustincole_data site's actual IA when the page is built.
- Trust-Score weights (0.40/0.40/0.20) are a starting point; expose them as a single config so they're tunable once the score distribution is visible.
