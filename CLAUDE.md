# sensor-data-quality — repo instructions

A public data-quality monitor for OpenAQ air-quality **sensors** (the "Sensor Trust Index" for dustincoledata.com).

## North-star framing (anti-overclaim guardrail — do not cross)

This project scores the **data-reporting health of sensors** (staleness, dropout, completeness, drift, consistency) — "is this sensor *feed* trustworthy." It is **NOT** an air-quality index and **NOT** a sensor-accuracy/calibration judgment. Never make pollution-level, health, or accuracy-vs-ground-truth claims. Keep every statement a **data-quality** statement.

## Hard constraints

- **Raw data is NEVER committed.** The loader pulls OpenAQ live and publishes only small *derived* QA metrics as JSON. `data/raw/` is git-ignored.
- **$0 infra, $0 runtime LLM.** Deterministic metrics only (no LLM in the loader). Free rails: GitHub Actions cron (public repo) + Vercel Hobby + static JSON.
- **COI:** stay vendor-neutral; no facility/emissions commentary. (Owner works at LG&E/KU; the Kentucky/Louisville geo exclusion was removed 2026-07-20 — no COI, Dustin's call — ADR-0001 superseded.)
- **Attribution:** dual — the upstream provider AND OpenAQ (CC BY 4.0 unless a provider specifies otherwise); suppress providers with `redistributionAllowed:false` from sensor-level display.

## Agent skills

### Issue tracker
Issues/PRDs/tickets live as **local markdown** under `.scratch/<feature-slug>/` — no external tracker. See `docs/agents/issue-tracker.md`.

### Triage labels
The five canonical roles use default strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs
Single-context: `CONTEXT.md` (glossary) + `docs/adr/` (decisions) at the repo root, created lazily by `/domain-modeling`. See `docs/agents/domain.md`.
