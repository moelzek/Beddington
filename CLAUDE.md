# CLAUDE.md — Lullaby (read me first)

This repository is **Lullaby**, a privacy-first baby-monitor companion. This file is a router, not a fact store: changing project facts belong in [memory.md](memory.md).

**Working repository:** `~/Code/Labie`.

## Read these in order

1. [memory.md](memory.md) — **single source of truth** for status, locked decisions, hardware, safety boundaries, tier state, and changelog.
2. [agents.md](agents.md) — how to work with Mo and how to preserve the living-document system.
3. [context.md](context.md) — the durable what and why.
4. [baby-monitor-build-plan.md](baby-monitor-build-plan.md) — the Tier 0–5 build sequence and bill of materials.
5. [baby-monitor-evaluation.md](baby-monitor-evaluation.md) — opportunity analysis and reviewer gate.
6. [ROADMAP.md](ROADMAP.md) — forward plan and acceptance gates.
7. [README.md](README.md) — human-facing project overview and quickstart.
8. [DEVLOG.md](DEVLOG.md) — short narrative journal of what actually happened.
9. [skills.md](skills.md) — project-specific tool routing.

## Supporting material

- `hardware-photos/` — local photos of the available hardware; intentionally git-ignored.
- `Archive/` — superseded Lab Witness documents, reviewer skills, prompts, and build logs. Historical only.

## Cardinal project rules

- `memory.md` wins if another document disagrees.
- Every decision, status change, or dated milestone gets written to `memory.md` with a dated changelog line.
- Raw audio and video never leave the device. Cloud services may receive only derived events, features, or short text.
- No medical or safety claims. No SIDS, apnoea, fever, or “breathing as a vital sign” language.
- Inferences such as “likely hungry” are visibly labelled **best guess**.
- Detection and timing are deterministic. An LLM is optional, behind a flag, and never required for the app to work.
- Hot compute lives in a vented base. The companion sits beside the cot, never in it.
- Develop hardware-free first using files and mock sensors behind adapter interfaces.
- Build only the active roadmap tier. Do not start a later tier without Mo’s explicit approval.
- Secrets never enter git. Use a gitignored `.env` and committed `.env.example`.

## Version control

### Auto-commit after every task

After finishing a logical unit of work:

1. Stage the intended files with `git add`.
2. Commit with a clear Conventional Commit prefix such as `docs:`, `feat:`, `fix:`, `test:`, or `chore:`.
3. Get the commit onto `main` and GitHub:
   - On `main`, use `git push`.
   - In a linked worktree or task branch, use `git push origin HEAD:main`.
   - If rejected because `main` moved, run `git fetch origin`, rebase onto `origin/main`, and retry once.
   - If conflicts remain, stop. Keep the local commit, never force-push, and report the conflict.

Rules:

- Never commit secrets, model weights, private recordings, or generated night logs.
- Never force-push `main`.
- Do not bundle unrelated pre-existing changes into a commit.
- Prefer one logical change per commit.
- If nothing changed, do not create an empty commit.

## Sign-off format

End completed work with:

`✅ Done & committed — <short-hash> "<message>"`

Then state whether it was pushed to origin or committed locally only.
