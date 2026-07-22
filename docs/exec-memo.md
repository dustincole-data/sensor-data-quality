# Sensor Trust: Project Report

**A public, self-updating data-quality monitor for the US public air-sensor network. What it is, how it works, what it found, and the engineering competency it proves.**

Live: [dustincoledata.com/projects/sensor-trust](https://dustincoledata.com/projects/sensor-trust) · Code: [github.com/dustincole-data/sensor-data-quality](https://github.com/dustincole-data/sensor-data-quality)

## What it is

Every PM2.5 sensor OpenAQ tracks in the United States is scored 0 to 100 each day on one question: is this sensor's feed still trustworthy to report from? The score rolls up into a national failure rate, a provider leaderboard, a per-sensor map, and a 90-day trend, on the live page above.

It is deliberately **not** an air-quality index and **not** a sensor-accuracy or calibration judgment. It never says the air is clean or dirty, and it never says a reading is right or wrong against a reference instrument. It measures one thing: data-reporting health. Is the sensor reporting, on time, completely, and within sane bounds? That is a data-quality / observability audit, the same discipline a utility applies to AMI (smart-meter) telemetry: is the endpoint checking in, on schedule, with complete readings that make sense.

That guardrail is load-bearing. Everything in this report stays on the data-health side of it.

## Why I built it

I wanted a public, end-to-end artifact that proves one competency cleanly: deterministic data-quality scoring and observability engineering at fleet scale, shipped and kept running, on real data anyone can check.

The public air-sensor network is a good proving ground because it is exactly the shape of problem that competency exists for: a real, messy fleet of thousands of independent endpoints, all reporting into one open API, all free to pull. The domain is incidental. The method is the point, and it is the same method a utility runs against smart-meter telemetry or a platform runs against any IoT fleet.

## How it works

**The scored unit.** Each US PM2.5 sensor OpenAQ exposes. The v1 scored set (the "Panel") is US PM2.5 only; other pollutants and global coverage are planned, not built. As of the run that locked the numbers below, the Panel was **5,546 sensors across 9 providers**, spanning regulatory networks (AirNow) and low-cost community sensors (Clarity, AirGradient).

**The four checks.** Each sensor is graded on four pure pass/fail checks. Every one is a data-reporting test; none is an air-quality claim.

| Check | Fails when | What it catches |
|---|---|---|
| Completeness | Under 90% of expected readings present over a trailing 30-day window | Sensors quietly dropping readings |
| Staleness | No reading in over 24 hours | Sensors that have gone silent |
| Drift | The recent reported level has shifted 3 or more standard deviations from the sensor's own trailing baseline | A sensor reporting inconsistently with its own recent history (a possible developing fault) |
| Plausibility | A reading falls below the sensor noise floor or beyond any real ambient value | Stuck-high or garbage values |

Two guardrail notes on the record, because they are the line between honest and overclaiming:

- Drift is judged only against the sensor's **own** past, never against other sensors or an air-quality truth. A single high day (real wildfire smoke) is valid data, not drift; the check fires only on a *sustained* shift, by design.
- Plausibility is a wide data-sanity bound, not a physics claim. The bounds sit below the documented optical-PM noise floor and far above any real ambient reading, so it flags stuck or garbage values without ever judging extreme-but-real air.

**The Trust Score.** 100 minus graded penalties across the four checks, currently weighted equally at 0.25 each. The weights are explicitly provisional and tunable, surfaced as a note in the data, because the honest justification for any particular weighting only exists once the full score distribution is visible. "Failed at least one check" is what drives the headline national failure rate.

**The engineering.**

- Scoring is a pure function with unit tests on every threshold boundary, built test-first.
- It runs on free rails: $0 infrastructure, $0 runtime LLM. A GitHub Actions cron re-scores the full Panel nightly, staggered inside OpenAQ's rate limit, off one cheap daily-aggregate call per sensor (no dense per-measurement pulls).
- A last-good fallback means a bad or empty run never blanks the live page, and a validity gate holds a structurally-valid but suspiciously-wrong result from publishing.
- The page itself makes zero external network requests: bundled basemap, no map tiles, CSP-safe.
- Provenance is handled: dual attribution on every sensor (upstream provider plus OpenAQ, CC BY 4.0), and providers whose license forbids redistribution are excluded from the Panel and counted, not silently displayed (ADR-0004).

## What it found

These are the locked numbers from the full-panel run of **2026-07-21**. The monitor recomputes daily, so the live figure moves; treat these as a dated snapshot, every figure backable to source.

- **73.0% of scored sensors failed at least one data-quality check** (4,051 of 5,546).
- **Median Trust Score: 74.3** (min 33.1, max 100).
- **27% passed every check** (1,495 of 5,546).
- 0 sensors excluded, 0 skipped, all 5,546 mapped.

Failure rate by check:

| Check | Share of Panel failing |
|---|---|
| Completeness | 61.0% |
| Staleness | 36.2% |
| Drift | 19.0% |
| Plausibility | 0.6% |

Read honestly, the story is dropout. The dominant failure is completeness: sensors going quiet or missing readings, not sensors reporting impossible values (plausibility fires on well under 1%). A "failed" sensor is one whose reporting is degraded. It is not a broken sensor, not a bad-air reading, and not a wrong measurement. The headline is a *failure* rate on purpose: the point of the project is to measure reporting health honestly, and a number designed to look flattering would defeat it.

What it means, plainly: on any given day a large share of the public air-sensor network is reporting patchy or stale data, and anything built on top of it (research, forecasts, consumer apps, health alerts) inherits that patchiness silently unless someone measures it. The contribution here is not a verdict on the air. It is a reusable, honest method for scoring reporting health across a whole fleet.

## Honest limits

Named plainly, because the gaps matter as much as the wins:

- **Scope is narrow by design.** v1 is US PM2.5 only. Global coverage and other pollutants (ozone, NO2) are a planned widening, not something already shipped.
- **Two of the four checks overlap.** Completeness and staleness are two views of the same dropout signal (staleness rarely fires on its own), so the score effectively rests on roughly three independent axes: dropout, drift, and plausibility. The equal 0.25 weights reflect that honestly and are marked provisional rather than presented as tuned.
- **Plausibility is intentionally weak.** It is a wide sanity bound (0.6% fire rate), not a calibrated physics check. That is the correct call for a data-health monitor, but it should not be read as a strong signal.
- **Two richer checks are deferred.** Flatline detection and cross-sensor consistency would need dense per-measurement series or a neighbor graph, which would break the cheap-summary API budget that keeps this free and fast. They are roadmapped, not built.
- **The time series is young.** Clean, like-for-like history starts at the 2026-07-21 model lock; earlier points mixed a model change with a real change and are not comparable.

Full methodology, thresholds, and the reasoning behind each decision live in the repo's ADRs and `CONTEXT.md`.

## Why it transfers

Swap "air sensor" for "smart meter," "grid endpoint," or any IoT/telemetry fleet and nothing about the method changes: enumerate the fleet, score reporting health deterministically, surface the failures honestly, automate it, keep it cheap and durable. That is observability and data-reliability engineering, demonstrated end-to-end on a public dataset anyone can check.

**Code and open pipeline:** https://github.com/dustincole-data/sensor-data-quality
