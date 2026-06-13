# memory.md — Lab Witness (durable FACTS & STATE)

> Single source-of-truth snapshot of the project's live state. Update this as things change. Pairs with [context.md](context.md), [agents.md](agents.md), [skills.md](skills.md). Cross-links to persistent memory: `lab-witness-working-agreement` and `lab-witness-project` (see MEMORY.md index).

## Key entities & conventions

- **Project name:** Lab Witness. **Working folder: `~/Code/Labie`** (folder named `Labie`). The redundant nested `Labie/Labie` was flattened on 13 Jun 2026 — there is no longer an inner `Labie/` subfolder.
- **Build doc (source of truth):** `lab-witness-v0-build-doc.md` in this folder.
- **Owner:** Mo — physician-scientist; owns science + story; new to hardware; ADHD; newborn.
- **Hardware oracle:** Flomotion (flomotion.app) — external app, copy-paste interface.
- **On-site mentors:** robotics-company founders — escalation path for risky hardware calls.
- **Lab-notebook target:** Notion (write modelled on Mo's Granola→Notion pipeline).
- **Deployment spine:** mock bench at **Blue Garage** (controlled lighting + fixed angle). A friend's real bench is **upside B-roll only**, never a dependency.
- **Demo Night venue:** LocalGlobe. Prize pool £2k+.

## Locked decisions (do not reopen)

| Decision | Call |
|---|---|
| Deployment | Mock bench at Blue Garage = spine; real bench = B-roll only |
| Protocol | Serial dilution / pipetting series (one mix/incubation step) |
| Deviation scope (v0) | **Timing only** (over/under-run). Reagent-order & skipped-step → v2 |
| Compute | Pi 5 (4GB, on hand) + Camera Module 3, **CPU-first vision (OpenCV / MediaPipe)**. **No AI HAT+ for v0** — deferred; add 13 TOPS / Hailo-8L post-v0 only if CPU proves too slow. Cloud LLM optional, for prose only |

## Kit list (all ordered / in hand as of 13 Jun 2026)

**All kit ordered and physically in hand** — the Pi 5 rig is present at Workshop #1. Pi 5 4GB (**have**) · Active cooler + 27W USB-C PSU (**have**) · Camera Module 3 ×2 (**have**) · 64GB A2 microSD (32GB **acquired**) · **Pi-5-compatible** camera cable (~£3) · top-down mount/clamp (~£15–30, single biggest reliability lever) · LED/ring light (~£15) · optional GPIO LED/buzzer (~£5). **Deferred (post-v0, only if CPU vision too slow): AI HAT+ 13 TOPS (~£70) or fallback Pi AI Camera IMX500 (~£70)** — don't buy upfront.

## Scoring model — the three judging axes

**Novelty · Deployment · Impact** (confirmed 13 Jun 2026). Supersedes the earlier four-axis framing (Innovation/Impact/Progress/Deployment) — "Progress" is no longer a scored axis and "Innovation" is now "Novelty". Every scoping call should defend at least one axis without breaking the v0 freeze (PROPOSED ~24 Jun — see Key dates). Deployment is the highest-risk axis given the open hardware gaps.

## Sprint roster — dated state (as of 13 Jun 2026, Day 0)

| Item | Status |
|---|---|
| Both gates locked | ✅ Done |
| Kit ordered | ✅ Done — all kit in hand; Pi 5 rig present at Workshop #1 (13 Jun) |
| CV/embedded dev recruited | ⬜ Open — Mo has the rig but has not confirmed a developer |
| Ordered step-list for dilution series written | ⬜ Open — Mo to write (his bench intuition = ground truth) |
| Rig booted / camera live | ⬜ Open |
| Physical rig + footage | ⬜ Open |
| Perception working | ⬜ Open |
| State machine firing | ⬜ Open |
| Notion write + timing flag | ⬜ Open |
| Live integration | ⬜ Workshop #2 (21 Jun) |
| **v0 FROZEN** | ⬜ PROPOSED ~24 Jun (pending Mo's confirmation) |
| Demo deck + rehearsal | ⬜ towards demo ~28 Jun |

## Open items Mo owns (manual, off-Claude)

1. ~~**Order the kit.**~~ ✅ Done — all kit ordered and in hand; Pi 5 rig present at Workshop #1.
2. **Write the ordered step-list** for the dilution series — still to do; nobody else can write it.
3. **Recruit/confirm the CV/embedded dev** who owns the rig — still open (Mo has the rig but no confirmed dev).

## Key dates

Revised timeline confirmed 13 Jun 2026 (supersedes the old 20 Jun freeze / 7 Jul Demo Night):

- **Sat 13 Jun** — Workshop #1 (in-person build/assembly). Today.
- **14–20 Jun** — Home / remote tinkering.
- **Sun 21 Jun** — Workshop #2 (in-person integration).
- **Wed 24 Jun** — **v0 FREEZE — PROPOSED, pending Mo's confirmation** (replaces the old 20 Jun freeze).
- **≈ Sun 28 Jun** — **DEMO (approximate** — ~a week after the 21st; exact date/time to be confirmed**)**. Was 7 Jul.
- **25 Jun Frontier Biotech** (attention collapses) *(review — may be superseded under the revised timeline; confirm with Mo)*.
- **28 Jun submission** *(review — may be superseded under the revised timeline; confirm with Mo)*.

## Cross-links to persistent memory

- `lab-witness-working-agreement` (type: feedback) — the Flomotion loop, beginner explanations, ADHD low-friction style, flag risk to mentors. **Authoritative on how Claude works here.**
- `lab-witness-project` (type: project) — canonical project facts + pointer to these files. **Working folder: `~/Code/Labie` — always operate here.**
- `lab-witness-hardware-on-hand` (type: reference) — kit Mo physically has + blockers (microSD, Pi-5 camera cable, micro-HDMI). Mirrored in folder file `lab-witness-hardware-inventory.md`.

## Project-specific skills (built, live)

- `flomotion-cto` — orchestrates a full multi-domain review; reconciles to one gate.
- `hardware-reviewer` — hardware-only PASS/FAIL + Safe-to-build gate (owns hardware-safety escalation).
- `software-reviewer` — code / control-logic / LLM-design PASS/FAIL + Approve/Revise/Reject gate.

  See [skills.md](skills.md) for when to reach for each.

## Changelog

- **2026-06-13** — Operating-system files created (context / agents / skills / memory). Day-0 snapshot recorded. Baker 2016 figures and AI HAT+ specs web-verified.
- **2026-06-13** — Judging rubric corrected to three axes: **Novelty · Deployment · Impact** (was four: Innovation/Impact/Progress/Deployment). "Progress" dropped, "Innovation"→"Novelty".
- **2026-06-13** — Aligned context.md to the three-axis rubric (it had drifted, still showed four). Added a Living-document protocol to agents.md: memory.md is the single source of truth, write-through on every canonical change, drift check at session start.
- **2026-06-13** — Added CLAUDE.md as an auto-loading router/index pointing to the four operating files (thin, no duplicated facts).
- **2026-06-13** — Added DEVLOG.md (daily build journal, distinct from this changelog) and routed CLAUDE.md to it. Decided against a static project-tree file (drift-bait; generate on demand instead).
- **2026-06-13** — Navigation pass: skills.md now routes the three built reviewer skills (flomotion-cto / hardware-reviewer / software-reviewer); CLAUDE.md anchors the working folder (`~/Code/Labie/Labie`) and indexes supporting files (hardware inventory, reviewer-build prompts, codex-review-request). Flagged `flomotion-cto-reviewer-PROMPT.md` as likely superseded by PROMPT-1.
- **2026-06-13** — Renamed all 21 hardware photos in `~/Code/Labie/Stuff/` from camera defaults (IMG_7802–7822) to descriptive snake_case names (e.g. `raspberry_pi_5_4gb_box`, `oled_display_1–3`, `pwm_servo_driver_front/back`, `jumper_wires_1/2`). Updated every photo reference in `lab-witness-hardware-inventory.md` and appended a full old→new mapping table; mirrored the note into persistent `lab-witness-hardware-on-hand`. **NB:** photos live in the sibling `Stuff/` folder, not the working `Labie/` folder. Pre-existing tension noted (not resolved): photos confirm a Pi 5 **4GB** + **no AI HAT+**, whereas Locked decisions / Kit list still cite 8GB + AI HAT+ — Mo to reconcile.
- **2026-06-13** — **Compute decision reconciled (Mo's call): no AI HAT+ for v0.** Standardised to Pi 5 (4GB, on hand) + Camera Module 3, CPU-first vision (OpenCV / MediaPipe); AI HAT+ (13 TOPS / Hailo-8L) and Pi AI Camera (IMX500) deferred to post-v0, add only if CPU too slow. Propagated to Locked decisions + Kit list above and to context.md, DEVLOG.md, agents.md, lab-witness-v0-build-doc.md, and persistent `lab-witness-project`. Reviewer-skill checklists already assumed 4GB/CPU-first.
- **2026-06-13** — **Flattened the folder structure:** moved all project files + skill folders up from `~/Code/Labie/Labie` into `~/Code/Labie` (alongside `Stuff/`); the inner `Labie/` is now **empty** but couldn't be removed from the sandbox (it's the session's mount point) — **Mo to delete `~/Code/Labie/Labie` in Finder.** Updated every path reference across CLAUDE.md, memory.md, the reviewer prompts, the hardware inventory, and persistent memory. New working folder is `~/Code/Labie`. `Stuff/` (hardware photos) is now a subfolder of the working folder; photo paths were absolute so they stay valid.
- **2026-06-13** — Repackaged `flomotion-cto.skill`: its bundled `SKILL.md` still had the old `~/Code/Labie/Labie/` handoff path (the earlier `.md` sweep couldn't reach inside the zip). Extracted, fixed the path, re-zipped to the identical 2-file structure, verified clean + zip integrity OK. The other two `.skill` archives (hardware-reviewer, software-reviewer) were already clean.
- **2026-06-13** — **Tidied the directory.** Created `Archive/` (the 4 spent build-prompts now the skills exist, plus `skills-flomotion-cto-OLD/` — a divergent older flomotion-cto copy parked pending Mo's call on which is canonical) and `reviewer-skills/` (the 3 skill source dirs + 3 `.skill` packages, out of root). Renamed `Stuff/` → `hardware-photos/` and updated every reference (inventory + persistent `lab-witness-hardware-on-hand`). Moved a stray `ROADMAP.md` out of the deprecated inner `Labie/` up to root and added it to the CLAUDE.md router. Sandbox couldn't delete the now-empty `Labie/`, the empty `skills/`, or a stray `.DS_Store` — **Mo to remove those three in Finder.**
- **2026-06-13** — Wired `ROADMAP.md` into `DEVLOG.md`'s header (the CLAUDE.md router already listed it at read-order #7), so every session auto-picks-up the forward plan and each day's logged outcome is checked against the current roadmap tier (A → B → C).
- **2026-06-13** — **Git repo established at the project root `~/Code/Labie`** (Mo's call — an earlier repo had been initialised one level too deep in the deprecated inner `Labie/`). Restored the `.gitignore`, `git init` at root, initial commit `2617eb4` — 31 files tracked. The 21 `.JPG` hardware photos are correctly **git-ignored** (so they live on disk but aren't versioned); the 3 `.skill` packages **are** tracked. Empty `Labie/` + `skills/` dirs and a `.DS_Store` remain (sandbox can't delete) — **Mo to remove in Finder.** If a future git command reports a stale `.git/index.lock`, delete `~/Code/Labie/.git/index.lock`.
- **2026-06-13** — **Timeline revised (Mo's confirmation).** Now a two-workshop structure: Workshop #1 (in-person build) Sat 13 Jun, home/remote tinkering 14–20 Jun, Workshop #2 (in-person integration) Sun 21 Jun, demo ≈ Sun 28 Jun (approx; was 7 Jul), v0 freeze PROPOSED Wed 24 Jun pending Mo's confirmation (was 20 Jun). Old milestones "Frontier Biotech 25 Jun" + "submission 28 Jun" annotated as review-may-be-superseded (not deleted). **All hardware now ordered and in hand** — the "Order the kit" item is closed and the Pi 5 rig is present at Workshop #1; Day-0 mode shifted from ordering to hands-on assembly at an in-person workshop with 3D printers, full tool bench, and mentors on site. **CV/embedded dev still unconfirmed** (Mo has the rig, no confirmed developer). Updated context.md + ROADMAP.md date/milestone refs to match; appended a Workshop #1 entry to DEVLOG.md.
- **2026-06-14** — **Code skeleton scaffolded (reusing Hatch).** Stood up the `lab_witness/` package mirroring build-doc §3 (Perception → State machine → Decision → Notion/Flag): `protocol.py` (timing state machine), `runtime.py` (perceivers + act sinks + loop). `BrainPerceiver` reuses `hatch-brain`'s `Brain.decide()` (one whitelist action per protocol step); `pyproject.toml` depends on `hatch-brain` from the Hatch repo (ADR-0009 — reusable kernel). Demoable with no hardware (`examples/serial_dilution.py` — the live over-run flag fires mid-incubation) + 5 passing timing tests (`tests/test_protocol.py`). The hard CV is decoupled behind a one-method `Perceiver` interface for the CV dev; Notion write + on-screen banner are still stubs. Followed labie's auto-commit-to-main convention (not a PR). **NB:** merge Hatch PR #1 first — it carries the per-action persistence fix `BrainPerceiver` relies on.
