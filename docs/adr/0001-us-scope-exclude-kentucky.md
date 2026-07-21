# US-only scope (v1), excluding Kentucky/Louisville

**Status: Superseded** (2026-07-20) — the Kentucky/Louisville exclusion below was removed:
no conflict of interest, Dustin's call. See A5c.

v1's Panel is US Sensors only (OpenAQ is global) — a legible US-audience story that keeps the daily poll inside OpenAQ's 2,000 req/hr limit; going global is a reversible v2 (lift the country filter). ~~Kentucky/Louisville Sensors are excluded because the owner works at LG&E/KU (a Louisville utility): scoring local Sensors near employer facilities as "low-trust" could read as compliance commentary from a utility insider (conflict of interest).~~ Both reference-grade and low-cost Sensors are in scope, since low-cost Sensors carry the messy fleet-health story the project is about.

## Update — Kentucky/Louisville exclusion removed (2026-07-20)

Dustin confirmed no conflict of interest; the geographic exclusion (`should_exclude_location`'s
KY bounding-box check, `src/openaq.py`) is removed and the `by_location_ky_louisville` count
is dropped from the derived JSON. The US-only scope (this ADR's other decision) stands
unchanged. ADR-0004 (restricted providers, dual attribution) is unaffected.
