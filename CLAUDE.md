# CLAUDE.md — Lab Witness (read me first)

This folder is the **Lab Witness** hackathon build sprint. This file is a **router, not a fact store** — it tells you where to look. Do not put project facts here; they live in the files below.

**Working folder (always operate here):** `~/Code/Labie`. All project files, edits and new outputs go here — not a temp/scratch location, not a different folder.

## Read these, in this order

1. **[memory.md](memory.md)** — the **single source of truth** for live state: status, locked decisions, judging rubric, kit list, roster, open items, changelog. Check this first, every session. If any other file disagrees with it, memory.md wins.
2. **[agents.md](agents.md)** — how to operate: mission, voice rules (beginner-level, ADHD low-friction, British English), the Flomotion loop, the build SOP, hard guardrails, and the **Living-document protocol** (anti-drift). Treat this as your standing instructions.
3. **[context.md](context.md)** — the durable what & why: purpose, people, definitions, the three judging axes, sprint clock, sources.
4. **[skills.md](skills.md)** — which skill/connector/tool to reach for, and what's out of scope.
5. **[lab-witness-v0-build-doc.md](lab-witness-v0-build-doc.md)** — the detailed build bible (historical source doc; where it disagrees with memory.md on mutable facts, memory.md is current).
6. **[DEVLOG.md](DEVLOG.md)** — daily build journal (what happened at the bench each day; also Demo Night narrative material). Append one block per day; don't restate canonical facts here.
7. **[ROADMAP.md](ROADMAP.md)** — forward plan: Tier A (v0 core) / B (polish) / C (narrative) and who/what builds each piece through Demo Night. Sequences the work; `memory.md` holds live status.

## Supporting files & folders (in this folder, not part of the operating system)

- **[lab-witness-hardware-inventory.md](lab-witness-hardware-inventory.md)** — what kit Mo physically has (Use now / Check or buy / Park for later). Live reference; mirrors the `lab-witness-hardware-on-hand` persistent memory.
- **[codex-review-request.md](codex-review-request.md)** — request for an independent adversarial review of the three reviewer skills.
- **`hardware-photos/`** — the 21 renamed photos of Mo's kit (was `Stuff/`).
- **`reviewer-skills/`** — source dirs + packaged `.skill` files for the three built skills (`flomotion-cto`, `hardware-reviewer`, `software-reviewer`). The live skills load from the plugin system, not here; these are the editable source of record.
- **`Archive/`** — spent/historical: the build prompts (`PROMPT-1/2/3`, `flomotion-cto-reviewer-PROMPT`) now that the skills exist, plus `skills-flomotion-cto-OLD/` — a **divergent older copy** of the flomotion-cto skill (has an extra `flomotion-handoff.md`), parked pending Mo's call on which version is canonical.

> Empty leftovers the sandbox couldn't delete — remove in Finder: `Labie/` and `skills/` (both empty) and a stray `.DS_Store`.

## Cardinal rules

- **Single source of truth:** mutable facts live in `memory.md` only. Other files link, never restate.
- **Write-through:** when a decision/status/date changes in conversation, update `memory.md` *and* the `lab-witness-project` persistent memory in the same turn, with a dated changelog line.
- **You are orchestrator/translator/reviewer, not the hardware oracle** — route hardware through the Flomotion loop and flag risk to on-site mentors (see agents.md).
- **The 20 Jun v0 freeze is sacred.** If a day slips, cut scope, never extend.

> Persistent memory (`lab-witness-project`, `lab-witness-working-agreement`) also auto-loads each session and carries the gist even if these files are stale — but keep both in sync.
