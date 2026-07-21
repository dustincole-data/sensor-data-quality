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
The set of Sensors currently in scope for scoring. v1 = United States **PM2.5** Sensors. (Other pollutants + global are v2 widens.)
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

**Data-quality check**:
One pass/fail test of a Sensor's reporting health against a threshold. Checks: **Staleness** (silent > 24h), **Completeness** (trailing-30-day `percentComplete` < 90%), **Plausibility** (a reading below the sensor noise floor or beyond any real ambient value), **Drift** (see below). "Failed ≥1 check" drives the hero national failure-rate.
_Avoid_: rule, SLA (implies an agreed service level that doesn't exist), metric (reserve "metric" for the underlying number)

**Drift**:
A data-quality check: the Sensor's recently reported level has shifted sharply away from its own trailing baseline — a marker of possible sensor drift or a developing fault. Judged against the Sensor's *own* history, never against other Sensors or an air-quality truth. A single anomalous day (a real pollution event) is not Drift; a sustained shift is.
_Avoid_: anomaly, outlier (reserve for a single point), calibration error (that's an accuracy claim — out of scope)

**Baseline**:
A Sensor's own trailing distribution of daily means, against which its recent reporting is compared for Drift. Self-referential — one Sensor's baseline says nothing about another's.
_Avoid_: normal, expected value
