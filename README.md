# sensor-data-quality

A public **data-quality monitor for air-quality sensors** — the "Sensor Trust Index" on dustincoledata.com.

## What this is (and is NOT)

It scores the **data-reporting health of each sensor** in the OpenAQ network: staleness, dropout, window-completeness, drift, and cross-sensor consistency. The question it answers is **"is this sensor *feed* trustworthy?"**

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
