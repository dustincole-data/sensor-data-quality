# Add a Drift check, soften Plausibility, and reweight the Trust Score

The v1 Trust Score shipped three checks — Staleness, Completeness, Plausibility — but the
dossier's whole competency thesis promised **drift/rolling-z-score anomaly detection** as the
marquee AMI-transfer signal. It was silently swapped for a fixed min<0/max>1000 plausibility
bound (undisclosed), and that bound mass-false-positives on benign optical-PM noise
(~43% of the headline was plausibility-only failures; A1 F1/F2, A2 G1). This ADR records the
correctness lock: **add Drift as a real fourth, independent check; soften Plausibility to a
data-sanity bound; and rebalance the weights.** Partially supersedes ADR-0002 (which deferred
drift to v2 to protect the cheap-summary budget — drift is now built, but still off the same
one-call `/days` payload, so the budget holds).

## Drift — sustained level shift vs the Sensor's own baseline

Drift is a **rolling z-score of the recent reported level against the Sensor's own trailing
Baseline of daily means** (the per-day `summary.avg` already in the fetched `/days` window):

- recent = mean of the last `DRIFT_RECENT_DAYS` (7) daily means
- baseline = the daily means before that; require `≥ DRIFT_MIN_BASELINE_DAYS` (10) with σ>0,
  else the check is **insufficient → PASS** (benefit of the doubt; dropout is already caught by
  Staleness/Completeness)
- `z = (recent − μ_baseline) / σ_baseline`; **fail if `|z| ≥ DRIFT_Z` (3.0)**; graded
  component `drift_c = clamp(1 − |z| / DRIFT_Z)`

**Why the recent *window* and not the latest day:** a single real high day (wildfire smoke) is
valid data, not a sensor fault — flagging it would repeat exactly the guardrail-crossing F2
mistake. Averaging over a 7-day recent window makes Drift fire on a *sustained* shift while a
lone spike dilutes out (verified on the T1 fixture: one 21 µg/m³ day is z≈2.7 alone but z≈0.4
inside the recent window → correctly passes).

**Guardrail (load-bearing):** Drift measures the Sensor's *self-consistency* — is it reporting
consistently with its own recent history — never air quality, accuracy, or agreement with other
Sensors. Presentation (site copy, ticket A5d) MUST frame it as "shifted from this sensor's own
recent baseline," never "the air changed," and must never assert a reading is wrong. If Drift
proves false-positive-prone on the full-panel run (A6), raise `DRIFT_Z` or demote it to a
recorded-only soft flag.

## Plausibility — a data-sanity bound, not a physics claim

`PLAUSIBLE_MIN` −5.0 (below the documented −4 to −5 µg/m³ optical-PM noise floor, ADR-0002
Update — so benign near-zero noise no longer fails) and `PLAUSIBLE_MAX` 10000.0 (a value no real
*ambient* reading reaches, even record wildfire — a stuck-high/sentinel guard, not a judgment on
extreme air). Re-verify the failure rate after the change (A6). Considered and rejected: keeping
max at 1000 (false-positives on real wildfire >1000 µg/m³, and guardrail-adjacent); dropping the
high bound entirely (leaves a stuck-high sensor scoring ~100).

## Weights — equal 0.25, provisional

`{staleness: 0.25, completeness: 0.25, plausibility: 0.25, drift: 0.25}`. Staleness and
Completeness are correlated views of dropout (A1 F13: staleness never fires alone), so their
combined weight drops 0.80 → 0.50; Drift and Plausibility are the independent axes. Exact weights
can't be justified until the score distribution is visible (the full-panel A6 run), so they are
**equal and explicitly provisional/tunable** — surfaced as a `weights_note` in the derived JSON.
Full de-correlation of the two dropout checks is deferred pending that distribution.
