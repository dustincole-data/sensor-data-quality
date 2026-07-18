# Sensor Data-Quality Monitor

Scores the data-reporting health of public air-quality sensors (OpenAQ) — "is this sensor feed trustworthy." A data-quality / observability audit, not an air-quality or accuracy judgment.

## Language

**Location**:
A physical monitoring site in OpenAQ; contains one or more Sensors.
_Avoid_: station, site

**Sensor**:
One measuring element at a Location reporting a single parameter (e.g. PM2.5) to OpenAQ. The unit we score.
_Avoid_: monitor, device

**Panel**:
The set of Sensors currently in scope for scoring. v1 = United States **PM2.5** Sensors, excluding Kentucky/Louisville. (Other pollutants + global are v2 widens.)
_Avoid_: fleet (evocative in prose, but "Panel" is the precise scored set), cohort

**Reference-grade sensor**:
A regulatory/agency monitor (e.g. EPA / AirNow) with strict siting and QA.
_Avoid_: reference monitor

**Low-cost sensor**:
A community/consumer sensor (lower cost, looser QA); noisier data-health, and the richer part of the story.
_Avoid_: cheap sensor

**Trust Score**:
A Sensor's 0–100 data-reporting-health score — the atomic unit everything rolls up from (national failure-rate, provider leaderboard). 100 minus graded penalties for degraded/failed checks.
_Avoid_: health score, quality score, rating

**Data-quality check (SLA)**:
One pass/fail test of a Sensor's reporting health against a threshold. v1 checks: **Staleness** (silent > 24h), **Completeness** (trailing-30-day `percentComplete` < 90%), **Plausibility** (window min < 0 or max > 1000 µg/m³). "Failed ≥1 SLA" drives the hero national failure-rate.
_Avoid_: rule, metric (reserve "metric" for the underlying number)
