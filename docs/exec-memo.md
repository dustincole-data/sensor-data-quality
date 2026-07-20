# Exec memo — Sensor Trust Index

**One page. What it is, and the competency it proves.**

## What it is

A public, self-updating **data-quality monitor** for the US public air-sensor
network. Every PM2.5 sensor OpenAQ exposes is scored 0–100 each day on one
question: **is this sensor's feed still trustworthy?** The result is mapped,
ranked by provider, searchable per-sensor, and trended over 90 days at
[dustincoledata.com/projects/sensor-trust](https://dustincoledata.com/projects/sensor-trust).

It is deliberately **not** an air-quality index and **not** a sensor-accuracy
judgment. It is a fleet **data-health / observability audit** — the same
discipline utilities apply to AMI (smart-meter) telemetry: is the endpoint
reporting, on time, completely, and within physical bounds?

## The competency it proves

- **Deterministic data-quality scoring at fleet scale.** ~5.5k sensors graded
  daily on three pure, testable checks (staleness, completeness, plausibility)
  into a single tunable Trust Score. Scoring is a pure function with unit tests
  on every threshold boundary — built test-first.
- **Honest measurement over flattering numbers.** The hero is a *failure* rate.
  Every denominator is disclosed: scored vs. mapped vs. unmappable vs. excluded,
  with counts. Metrics are designed to resist ingestion-lag artifacts (windowed
  completeness, a conservative staleness bar), not to look good.
- **Ships and stays up on free rails.** $0 infra, $0 runtime LLM. A GitHub
  Actions cron re-scores nightly inside OpenAQ's rate limits; a last-good
  fallback means a bad or empty run never blanks the live page. The page itself
  makes zero external network requests (CSP-safe, bundled basemap).
- **Data-licensing and provenance hygiene.** Dual attribution on every sensor
  (upstream provider + OpenAQ, CC BY 4.0); providers whose licenses disallow
  redistribution are excluded and counted.

## Why it transfers

Swap "air sensor" for "smart meter," "grid endpoint," or any IoT/telemetry
fleet and nothing about the method changes: enumerate the fleet, score reporting
health deterministically, surface the failures honestly, automate it, keep it
cheap and durable. That is observability / data-reliability engineering.

## Integrity note

Panel is US PM2.5. Kentucky/Louisville sensors are held out of scope as a
conflict-of-interest precaution, keeping the author at arm's length from any
local network. Rationale in [`docs/adr/0001`](adr/0001-us-scope-exclude-kentucky.md).

**Code + open pipeline:** https://github.com/dustincole-data/sensor-data-quality
