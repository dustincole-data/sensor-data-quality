# Domain Docs

How the engineering skills consume this repo's domain documentation.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root (the glossary), and
- **`docs/adr/`** — read ADRs touching the area you're about to work in.

This is a **single-context** repo (no `CONTEXT-MAP.md`). If `CONTEXT.md` or `docs/adr/` don't exist yet, **proceed silently** — `/domain-modeling` (reached via `/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## Use the glossary's vocabulary

When output names a domain concept (issue title, hypothesis, test name), use the term as defined in `CONTEXT.md`; don't drift to synonyms it lists under `_Avoid_`.

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly rather than silently overriding.
