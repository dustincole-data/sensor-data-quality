# Build & Planning Workflow — Sensor Data-Quality Monitor (OpenAQ)

## Context
The deep research/selection dossier picked a winner: an OpenAQ **Sensor Data-Quality Monitor** for dustincoledata.com (survived all 6 hard gates + the contrarian pass; runner-up USGS 87% vs 94%). This plan is the *process* for going dossier → shipped, using Dustin's Matt Pocock "AI Hero" skills in the correct order, with a dedicated project home.

**What it is (north-star framing / anti-overclaim guardrail):** it scores the **data-reporting health of each air-quality sensor** (staleness, dropout, window-completeness, drift, cross-sensor consistency) — "is this sensor *feed* trustworthy." It is **NOT** an air-quality index and **NOT** a sensor-accuracy/calibration judgment (those are environmental science = out of Dustin's lane). This keeps it squarely in his AMI data-quality competency.

**Confirmed decisions:**
- Entry point: **Grill → Spec → Tickets** main flow; **skip `/wayfinder`** (one-session-size build; dossier already de-fogged it).
- Project locked: **OpenAQ** (grilling settles HOW, not WHICH).
- Project home: a **dedicated folder + public GitHub repo at `C:\Users\dusti\Projects\sensor-data-quality`** — the single home for all pipeline code, data, and Matt-Pocock docs/spec/tickets. (Repo name overridable → `sensor-trust`; public page branded "Sensor Trust Index".)
- Issue tracker: **LOCAL markdown** (not GitHub Issues) — tickets live *in the folder* (`.scratch/<feature>/` + `tickets.md`), self-contained, matching the Fanbase_Weather precedent and the "all docs in the project folder" rule. Blocking edges are text ("Blocked by").

## Two repos (keep straight)
1. **`Projects\sensor-data-quality`** (new, public GitHub) — loader + GitHub Actions cron + derived JSON + CONTEXT.md/ADRs/spec/tickets. The Matt-Pocock home. Public repo = free unlimited Actions + raw-JSON hosting.
2. **`Projects\dustincole_data`** (existing brand site) — receives the **Astro page** that fetches the derived JSON, as a branch/PR. A downstream deliverable (its own ticket), not the project's primary repo.

## The pipeline (canonical order, per `ask-matt` router — verified against the skill files)
Keep Stages 2–4 in **one unbroken context window** (~120k-token "smart zone"); if it fills before `/to-tickets`, `/handoff` to a fresh thread. Clear context between each `/implement`.

0. **Scaffold the project home** — `mkdir Projects\sensor-data-quality`, `git init`, create the public GitHub repo, seed `README.md` + `CLAUDE.md` + `.claude/plans/` (move THIS plan here per the `specs-plans-single-home` rule) + a pointer to the dossier. *This is the prerequisite that makes `/grill-with-docs` (the stateful, paper-trail variant) valid — without an existing repo you'd be forced into stateless `/grill-me` with no CONTEXT.md/ADRs.*
1. **`/setup-matt-pocock-skills`** (in the new repo, once) — configure tracker = **local markdown**, triage labels (defaults), domain docs = single-context (`CONTEXT.md` + `docs/adr/` at root). Writes `docs/agents/*.md` + an `## Agent skills` block into `CLAUDE.md`.
2. **`/grill-with-docs`** — feed it the dossier; relentless one-question interview (runs `/grilling` + `/domain-modeling`) that settles the open decisions below and writes `CONTEXT.md` glossary + `docs/adr/` ADRs. This is the step "go straight to /to-spec" would wrongly skip.
3. **`/to-spec`** — synthesize the grilled thread into a spec/PRD (Problem, Solution, User Stories, Implementation/Testing Decisions, Out of Scope); sketch + confirm test **seams** (fewest, highest); publish to the local tracker with `ready-for-agent`.
4. **`/to-tickets`** — slice into **vertical tracer-bullet** tickets (each a narrow but COMPLETE path through all layers, demoable — NOT the horizontal Phase-0-4 build order), each with "Blocked by" edges; quiz on granularity; write `tickets.md` in repo root (dependency order).
5. **`/implement`** per ticket — fresh context each; drives `/tdd` at agreed seams then `/code-review` (Standards + Spec); commit.

## What `/grill-with-docs` must settle (so `/to-spec` has decisions to synthesize)
- **Panel scope:** all-global (~15k sensors, ~5h polite daily poll) vs a US reference-grade subset — runtime vs coverage tradeoff.
- **Trust Score formula + SLA thresholds:** staleness cutoff, window-completeness floor (e.g. <90%), drift z-score threshold, cross-sensor consistency rule, 0–100 weighting.
- **Methodology guard:** score `coverage.percentComplete` over fixed windows; disclose the out-of-order-ingestion caveat (never equate "not ingested yet" with "sensor down").
- **COI exclusion:** exclude KY/Louisville sensors; vendor-neutral framing; no facility/emissions commentary.
- **Per-provider licensing:** `/v3/licenses` check; suppress `redistributionAllowed:false` providers from sensor-level display; dual attribution (provider + OpenAQ).
- **Headline metric wording** ("% of sensors failing ≥1 SLA in 30 days" + network leaderboard) and the **"data health, not air quality/accuracy" disclaimer** copy.

## Ticket preview — VERTICAL tracer bullets (exact granularity/edges decided in the `/to-tickets` quiz)
- **Prefactor/spike:** OpenAQ key + `/v3/locations` + `/v3/locations/{id}/sensors` reachable; `datetimeLast`+`percentComplete` populated (thin, not user-facing).
- **Bullet 1 (end-to-end):** ONE metric (staleness) for a small sensor panel → tiny derived JSON → rendered as a single number on a bare page. Cuts every layer; demoable. *(blocked by spike)*
- **Bullet 2:** add window-completeness + composite Trust Score (widen scoring). *(blocked by 1)*
- **Bullet 3:** daily GitHub Actions cron + 30-day rolling history + health-check/last-good fallback. *(blocked by 2)*
- **Bullet 4:** full leaderboard + per-sensor table/map + methodology/disclaimer UI on the dustincole_data page. *(blocked by 2)*
- **Bullet 5:** framing pass (lead with data-observability competency) + README-skim + 1-page exec memo + publish at `/sensor-trust`. *(blocked by 4)*

## Verification (definition of done per stage)
- **scaffold:** repo exists locally + on GitHub (public); README/CLAUDE.md/.claude/plans seeded.
- **setup:** `docs/agents/*.md` (tracker=local) + `CONTEXT.md`/`docs/adr/` layout + `## Agent skills` block present.
- **grill:** `CONTEXT.md` + ADRs written; every "must settle" decision above has a recorded answer.
- **to-spec:** one spec file on the local tracker tagged `ready-for-agent`, consistent with glossary + ADRs; seams confirmed.
- **to-tickets:** vertical tracer-bullet `tickets.md` with explicit "Blocked by" edges, approved by Dustin.
- **implement:** each ticket's acceptance test passes (e.g. Bullet 4 → page renders from live JSON on Vercel preview, Lighthouse mobile ≥ ~91, disclaimer/attribution visible); `/code-review` clean before commit.

## Pointers
- **Dossier** (research artifact + code-level architecture/cost/phases/risks): [raw/sources/2026-07-17 Public Data Project Selection for dustincoledata Research.md](<raw/sources/2026-07-17 Public Data Project Selection for dustincoledata Research.md>)
- **Canonical order / router:** `C:\Users\dusti\.claude\skills\ask-matt\SKILL.md`
- **Skill defs:** `C:\Users\dusti\.claude\skills\{setup-matt-pocock-skills,grill-with-docs,to-spec,to-tickets}\SKILL.md`
- **Precedent (local-tracker + wayfinder style):** `C:\Users\dusti\Projects\Fanbase_Weather\.claude\plans\fanbase-weather-collector\`

## Immediately after plan approval
1. Scaffold `Projects\sensor-data-quality` (folder + git + public GitHub repo + seed files; move this plan into its `.claude/plans/`).
2. `/setup-matt-pocock-skills` → tracker = local markdown.
3. Begin `/grill-with-docs` against the dossier — settle the decisions above.
