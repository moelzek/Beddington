# CLAUDE.md — Lullaby / Labie (read me first)

This folder is the **Lullaby** project. It pivoted from Lab Witness on 19 Jun 2026. This file is a router, not a fact store.

**Working folder:** `~/Code/Labie`.

## Read These First

1. **[memory.md](memory.md)** — single source of truth for active facts, decisions, status, and changelog.
2. **[context.md](context.md)** — what Lullaby is, why it exists, and its product boundaries.
3. **[agents.md](agents.md)** — how to operate: voice, safety, hardware escalation, and drift rules.
4. **[ROADMAP.md](ROADMAP.md)** — current build sequence.
5. **[BUILD.md](BUILD.md)** — practical build/runbook notes.
6. **[skills.md](skills.md)** — tool routing for this project.
7. **[DEVLOG.md](DEVLOG.md)** — reverse-chronological work log.

## Current Product Boundary

- Lullaby is a privacy-first baby-monitor companion.
- Raw audio/video stays on-device.
- Core detection must work deterministically with the LLM off.
- No medical claims: do not say the product diagnoses, treats, predicts, prevents SIDS, verifies breathing health, or proves a baby is safe.
- Hot compute stays in a vented base beside the cot, not in the cot.
- Cloud LLM use, if any, is optional and only for summarising already-redacted text events.

## Legacy Material

- Lab Witness is retired and archived.
- `lab-witness-*`, `reviewer-skills/`, and `Archive/` are legacy unless Mo explicitly asks to reuse them.
- Do not resurrect Lab Witness scope, deadlines, hardware plans, Notion lab notebook work, or hackathon judging criteria for Lullaby.

## Git Rules

- Do not commit, amend, push, or create PRs unless Mo explicitly asks.
- Never discard or overwrite uncommitted user work. If local changes block a pull/merge, stash them with a clear name first.
- Never force-push `main`.

## Memory Rules

- Mutable facts live in `memory.md`.
- When a decision/status/date changes, update `memory.md` and persistent memory in the same turn.
- If repo docs and memory disagree, `memory.md` wins, but flag the drift.
