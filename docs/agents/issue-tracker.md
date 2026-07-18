# Issue tracker: Local Markdown

Issues and PRDs for this repo live as markdown files in `.scratch/` (no external tracker). External PRs are not a request surface.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The PRD/spec is `.scratch/<feature-slug>/PRD.md`
- Implementation issues are `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed). `/to-tickets` may instead write a single ordered `tickets.md` at the repo root.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path (the user normally passes the path or issue number).

## Wayfinding operations (used by `/wayfinder` — not used by this project yet)

- **Map**: `.scratch/<effort>/map.md`
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md` with `Type:` (`research`/`prototype`/`grilling`/`task`) and `Status:` (`claimed`/`resolved`) lines
- **Blocking**: a `Blocked by: NN, NN` line; unblocked when every listed file is `resolved`
- **Frontier**: first open, unblocked, unclaimed file by number
