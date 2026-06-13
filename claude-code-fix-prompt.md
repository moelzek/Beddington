# Fix prompt — Lab Witness reviewer skills

**Paste this into Claude Code, run from `~/Code/Labie`.**

You are working in the **Lab Witness** repo. It contains three coordinated Claude *skills* that review an external executor's (Flomotion's) hardware/software suggestions for a hackathon robot:

- `flomotion-cto` — orchestrator: decomposes input, dispatches to the two reviewers, reconciles to one gate.
- `hardware-reviewer` — hardware verifier/critic (owns physical-safety escalation).
- `software-reviewer` — software/LLM verifier/critic.

Each skill = a `SKILL.md` + a `references/` folder, and is also shipped as a `.skill` zip. The repo was **recently reorganised**, so the skill sources now live under `reviewer-skills/` and old material under `Archive/`. **Do not trust any path in this prompt blindly — verify it against the live repo first**, because the prompt was written from a possibly-stale view.

A smoke test (run in the Cowork desktop app) surfaced the defects below. Work **top-down by priority**. For every item: **(a) verify it's actually true in the current repo, (b) fix it, (c) prove the fix.** Do not silently resolve the one item marked **[ASK MO]**.

## Ground rules
- These skills are meant to be a *source of truth*. Correctness beats cleverness — no fabricated specs, paths, or part numbers.
- Keep each skill **self-contained**: at runtime an installed skill only has its own folder, so **every file a `SKILL.md` instructs itself to read must physically exist inside that skill's own `references/`.** Do not "dedupe" shared files by deleting copies.
- After editing any skill, **rebuild that skill's `.skill` package** from its source dir so the zip matches the source (a `.skill` is just a zip of the skill folder).
- Leave `Archive/` contents alone except where explicitly told.
- Start by running `git status` and creating a branch (e.g. `fix/reviewer-skills`) so every change is reviewable.

---

## P0 — runtime-breaking

### 1. `software-reviewer` loses its `references/` when installed
Its `SKILL.md` → "Before you start" instructs reading `references/shared-guardrails.md` **and** `references/review-checklist.md`. In the **installed** copy both reads fail because the `references/` folder is absent. The repo source and the `.skill` package appear intact — so this is a stale install, not a missing source.

- Verify the source `reviewer-skills/software-reviewer/references/` contains **both** files. If either is missing, restore it (the canonical `shared-guardrails.md` is byte-identical across all three skills; the checklist is software-specific).
- Rebuild `reviewer-skills/software-reviewer.skill` from the source dir; confirm with `unzip -l` that the zip lists `SKILL.md` + both reference files.
- ⚠️ **The actual installed copy lives in the Cowork desktop app's skill cache, which you cannot write.** Once the package is correct, **Mo must reinstall `software-reviewer.skill` in the desktop app (Settings → Capabilities).** Put this in your final report as a required manual step.

### 2. Stale pre-reorg paths baked into the skills / packages
The orchestrator writes a hand-off file to a hard-coded path; an earlier version pointed at the now-defunct nested `~/Code/Labie/Labie/`.

- Run `grep -rn "Labie/Labie" .` across the repo, **and** `unzip -p <each>.skill | grep -n "Labie/Labie"` for each package. Fix every hit to `~/Code/Labie/`.
- Rebuild any `.skill` you touched.

---

## P1 — source-of-truth correctness

### 3. [ASK MO] Hardware contradiction — do NOT auto-resolve
`memory.md` "Locked decisions" still says **Pi 5 (8 GB) + AI HAT+ 13 TOPS / Hailo-8L**, but the skills' checklists, `lab-witness-hardware-inventory.md`, and the photos in `hardware-photos/` all say **Pi 5 4 GB, no AI HAT on hand**. These cannot both be true, and it sits on the project's highest-risk judging axis (Deployment).

- **Do not pick a side.** Add a prominent `> ⚠️ UNRESOLVED:` block at the top of `memory.md`'s Locked-decisions section stating the contradiction in one line, and **stop for Mo's decision** on this item. Fix everything else around it.

### 4. Reference / path drift after the reorg
Verify each of these resolves and names all three skills correctly; fix stale paths:
- `CLAUDE.md` — supporting-files list (the `PROMPT-1/2/3-*.md` and `flomotion-cto-reviewer-PROMPT.md` files moved to `Archive/`; confirm the paths match reality, and that the skills' home `reviewer-skills/` and `ROADMAP.md` are indexed).
- `codex-review-request.md` — its `./flomotion-cto/SKILL.md` style paths should now be `reviewer-skills/flomotion-cto/SKILL.md` etc. Also refresh its embedded "what Claude already found" so it isn't stale (the duplicate-fork is already archived; the routers may already reference the skills).
- `skills.md`, `agents.md`, `memory.md` — confirm all three skills are named and any path points into `reviewer-skills/`.
- Per the repo's living-document protocol, add a **dated changelog line** to the bottom of `memory.md` recording the reorg (skills→`reviewer-skills/`, prompts→`Archive/`, photos→`hardware-photos/`, `ROADMAP.md` added) and the fixes from this prompt.

---

## P2 — drift-prevention & hygiene

### 5. Triplicated `shared-guardrails.md` is a maintenance trap
All three skills bundle a byte-identical `references/shared-guardrails.md` that literally calls itself "the single canonical copy." Don't delete copies (installed skills need a physical file). Instead:
- Add `reviewer-skills/sync-guardrails.sh` that copies one canonical `shared-guardrails.md` into all three `references/` dirs and rebuilds all three `.skill`s.
- Run it; confirm with `md5sum` that the three copies are identical.

### 6. `evals/` parity
Only `software-reviewer` has an `evals/evals.json`. Either add equivalent eval stubs for `hardware-reviewer` and `flomotion-cto`, or add a one-line note in each skill's folder explaining why it has none. State which you chose.

### 7. Remove empty leftovers
If `~/Code/Labie/Labie` and `~/Code/Labie/skills` exist and are empty, remove them; remove any stray `.DS_Store`. Confirm they were empty first.

---

## Final verification — run all, report results as a table
1. `grep -rn "Labie/Labie" .` → expect **no hits**.
2. For each skill: every `references/*.md` named inside its `SKILL.md` physically exists in that skill's folder.
3. `unzip -l` each `.skill` → contains its `SKILL.md` **and** all its reference files.
4. `md5sum` the three `shared-guardrails.md` → **identical**.
5. Router files (`CLAUDE.md`, `memory.md`, `skills.md`, `agents.md`) name all three skills with correct `reviewer-skills/` paths.
6. `memory.md` has the new dated changelog line and the `UNRESOLVED` hardware note.

Report a short table: **issue → verified true? → action taken → proof**. Then list the two things only Mo can do: **(i) reinstall `software-reviewer.skill` (and any other rebuilt `.skill`) in the desktop app**, and **(ii) decide the 8 GB+AI-HAT vs 4 GB/no-HAT question.** After the reinstall, the last check is a live smoke test: run `flomotion-cto` on a cross-domain input and confirm it dispatches to both reviewers and returns one reconciled gate (this was blocked before, because the orchestrator chains into the broken `software-reviewer`).
