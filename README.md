# sensor-data-quality

A public **data-quality monitor for air-quality sensors** — the "Sensor Trust Index" on dustincoledata.com.

**Live:** https://dustincoledata.com/projects/sensor-trust · re-scored daily by a GitHub Actions cron.

## What this is (and is NOT)

It scores the **data-reporting health of each sensor** in the OpenAQ network on three v1 checks — **staleness** (silent > 24 h), **completeness** (< 90% of expected readings over a trailing 30 days), and **plausibility** (a physically impossible PM2.5 value) — rolled into a 0–100 Trust Score. The question it answers is **"is this sensor *feed* trustworthy?"** (Two richer checks — flatline detection and cross-sensor consistency — are deferred to v2.)

v1 scope is **US PM2.5** sensors: the fine-particle pollution most tied to health, the pollutant behind most AQI readings, and by far the most widely reported parameter in the network, so there is enough coverage to grade a whole fleet. Other pollutants and global coverage are v2 widens.

It is **NOT**:
- an air-quality index (it says nothing about whether the air is clean), or
- a sensor-accuracy / calibration judgment (whether a reading is right vs. ground truth).

Those are environmental science. This is **data-quality / observability engineering** — a fleet-of-sensors data-health audit, the same discipline applied to utility smart-meter (AMI) telemetry.

## How it works (see the dossier + plan)

Loader (Python) pulls OpenAQ v3 summary endpoints → computes deterministic QA metrics → publishes small **derived** JSON. Raw measurements are never committed. A static Astro page on dustincole_data fetches the derived JSON. Runs on free rails (GitHub Actions cron + Vercel Hobby); $0 infra, $0 runtime LLM.

## Pointers
- **Build workflow plan:** `.claude/plans/build-workflow.md`
- **Research dossier (source of truth for feasibility):** `C:\Users\dusti\brain\raw\sources\2026-07-17 Public Data Project Selection for dustincoledata Research.md`
- **Data source:** OpenAQ API v3 — https://docs.openaq.org (free key, CC BY 4.0 per-provider)

Attribution: air-quality data via **OpenAQ** and its upstream providers (CC BY 4.0 unless a provider specifies otherwise).
