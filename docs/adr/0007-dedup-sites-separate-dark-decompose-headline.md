# Dedup to physical sites, separate dark Sensors from the scored population, and decompose the national headline

An adversarial statistical-rigor pass (three hostile reviewers, 2026-07-22) found the shipped
Trust Score **not defensible as one 0–100 number**, because it conflated two different questions —
*"is the sensor even reporting?"* and *"how good is the data it reports?"* — onto one axis. Three
concrete defects, each a one-line kill for a statistician or an HN commenter:

- **A dead sensor scored exactly 50 ("fair").** 1,885 of 5,551 rows (34%) scored *exactly* 50.0,
  all sharing the pattern `[completeness, staleness]` — pure-dark sensors with no data. Mechanism:
  a dark sensor has `completeness_c=0` and `staleness_c=0`, but `plausibility_c` and `drift_c`
  **default to 1.0 when there is nothing to judge** → `100·(0+0+0.25+0.25)=50`. *Absence of
  evidence was scored as evidence of health,* on exactly the sensors with the least evidence. And
  the site bands 50–74 as "fair," so **every dead sensor rendered "fair."**
- **A "live full panel" badge over a graveyard.** 23.5% of rows last reported > 1 year ago
  (oldest 2016); the pulsing live-dot + "5,551 sensors" implied a live network. "Padding a scary
  failure rate with a decade of dead hardware under a live badge" is a graveyard census, not a
  data-health audit.
- **Duplicate rows.** 844 redundant rows by location; "Millvale" was **86 rows at one coordinate**
  (one CMU site's hardware-swap history, not 86 instruments); "Mammoth Lakes" ×36 was GPS jitter
  in the 5th–6th decimal. One dead site could single-handedly set a small rollup and inflate the
  denominator.

This ADR records the **ship-gate correction**: fix the population before any count, then report it
honestly. It changes *panel membership and the national summary* only — **per-Sensor scoring math
is untouched**, so the live fleet's scores, provider medians, and trend continuity are preserved.

## Decision

Applied in `loader._finalize_panel` (shared by the live pipeline and the one-time reprocessor),
in order:

1. **Dedup to physical sites.** Key = `round(lat,4) + round(lon,4) + provider`; keep the
   most-recently-reporting row of each. Millvale 86 → 1. A Sensor with no coordinates keys on its
   own id (it can't be a coordinate duplicate). Deduped **before any count or rollup**.
   *Result: 5,551 rows → 5,147 physical sites (404 dup rows removed).*

2. **Separate dark Sensors from the *scored* population.** A Sensor is **dark** when it never
   reported or has been silent longer than `DARK_AFTER_HOURS` (168 h = 7 days). Dark Sensors are
   **counted, not scored** — they carry `status:"dark"`, not a Trust Score anyone reads as
   quality. Only Sensors that actually report are scored. This kills the 50-spike and the
   "dead = fair" harm at the source, and (because it changes only *membership*) leaves the live
   fleet's scoring untouched.

3. **Decompose the national headline** into three honest buckets instead of one blob, leading with
   the live count:
   - **clean** (live, passes all four checks) — **1,456 (28.3% of sites)**
   - **reporting-but-flawed** (live, fails ≥1 check) — **2,093 (40.7%)**
   - **dark/silent** (counted, not scored) — **1,598 (31.0%)**
   - **live-only failure rate = 2,093 / 3,549 = 59.0%** — the number that survives the zombie
     critique (vs the old 73.5% over a graveyard-padded denominator).

4. **Fix the panel label / scope.** `PANEL_LABEL` drops "(live full panel)" → **"US PM2.5 sensors
   redistributed by OpenAQ."** Liveness is now stated as a *count*, never asserted by a badge. The
   fuller scope caption (low-cost/hobbyist-heavy: AirGradient + Clarity dwarf regulatory AirNow;
   attributions include individuals — **not** "the US air-sensor network") lives in the site copy.

## Why 7 days for "dark" — and why the exact window doesn't matter

7 days is a weekly-heartbeat bar: a feed that has produced nothing in a week is not "currently
reporting," yet the bar is far more forgiving than the 24 h Staleness check (a merely-stale-but-
alive sensor still scores, as *flawed* on Staleness). More important, **the split is robust to the
window** because the panel is bimodal: ~44% of sites report within a day, then a near-empty gap
(1–30 days ≈ 2%), then a large tail of multi-year-dead hardware (>1 yr ≈ 20%). So the dark share
barely moves with the cutoff — **7 d → 30 d shifts dark only 31.0% → 30.0% and the live failure
rate 59.0% → 59.6%.** The classification isn't riding on a gerrymandered threshold; it's riding on
a real gap in the data. `clean` is window-*invariant* (passing Staleness ⇒ reported < 24 h ⇒ always
live). The window is exposed as `DARK_AFTER_HOURS` and published as `national.dark_after_hours`.

## Scope — ship-gate minimum only

This is steps 1–4 of the reviewers' recommendation (the unambiguously-correct fixes). **Deferred**
to a later, data-informed tuning pass (documented, not done here):

- **Renormalize weights over the *evaluable* checks** for partially-dark live sensors (no free 1.0
  for a check that can't be judged).
- **Demote Plausibility from a 25% component to a pass/fail gate** (it fires on 0.6% of sensors —
  a near-constant +25, carrying no discriminating information as a graded term).

Both re-score the live fleet (resetting the trend epoch and forcing test/distribution rework), so
they are deliberately done *after* the dark separation makes the live distribution visible. Clean
first; tune weights with the real numbers in hand.

## Consequences

- The published `sensors` list is **deduped** and each row carries `dark` + `status`
  (`clean|flawed|dark`); `national` gains `sites_total, live, dark, clean, flawed, *_pct,
  raw_rows, dark_after_hours`. `sensors_scored` / `failure_rate_pct` are **redefined** to the live
  population (the persist F4 guards still read them; 59% sits well under the 90% ceiling, and the
  changed panel label exempts the one-time transition from the same-panel jump guard).
- History provider-medians **exclude dark rows**, so a provider's graveyard can't drag its median.
- The site drops the by-state table (a state median over a 34% point-mass at 50 was largely
  "% dead in disguise"); the **provider** leaderboard is the only ranking, led by **% reporting
  cleanly** with median as a secondary column over live sensors (n ≥ 10 floor retained).
- Every headline number must be **recomputed on the corrected population before any copy is
  written** — done: see the numbers above, validated against the 2026-07-22 08:43 UTC run.

Supersedes the "one 0–100 Trust Score, banded 50–74 = fair over all sensors" presentation from the
A6 full-panel ship. Does **not** change the four checks or their weights (ADR-0006 stands).
