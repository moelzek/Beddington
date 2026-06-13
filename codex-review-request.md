# Codex review request — Lab Witness reviewer skills

**Ask:** Give an independent, adversarial review of three coordinated Claude *skills* I built. I want a second opinion — find what's wrong, not reassurance. Claude has already reviewed them (findings at the bottom); **verify those independently and tell me what Claude missed.**

## Context (read the files in this repo)

These three skills implement a "Flomotion loop" review system for **Lab Witness** — a hackathon robot (Raspberry Pi over a lab bench that watches a scientist, writes the lab notebook to Notion, flags timing deviations). Flomotion is an external executor; these skills are the *reviewers* that gate its output. Owner is a beginner in HW/SW, so every review must carry a plain-English register + a deep technical register.

Files (each is `SKILL.md` + a `references/` folder):

- `./flomotion-cto/SKILL.md` — CTO orchestrator: decomposes input, dispatches to the two reviewers, reconciles their verdicts into one gate, manages a review loop + Flomotion hand-off.
- `./hardware-reviewer/SKILL.md` (+ `references/review-checklist.md`, `references/shared-guardrails.md`) — hardware verifier/critic; owns physical-safety escalation.
- `./software-reviewer/SKILL.md` (+ `references/` — **see defect**) — software/LLM verifier/critic.

The three share an identical `references/shared-guardrails.md` (4 rules: never fabricate specs, escalate hardware-safety to on-site mentors, stay inside the 20 Jun v0 freeze, don't rubber-stamp). Each reviewer ends with a structured return block:

```
{ verdict, conditions_to_clear, evidence, fix_prompts[], mentor_questions[], confidence }
```

…which `flomotion-cto` parses and reconciles (adds `round`, `reviewers_run`).

## What I want you to judge

1. **Is the verifier/critic + orchestrator design sound** for catching bad AI-generated hardware/software suggestions reliably? Where would it still bluff or rubber-stamp?
2. **Is the structured-return contract robust** for machine orchestration? Reviewers emit string verdicts (`Approve|Revise|Reject`, `Safe-to-build|Do-not-build`) while the orchestrator prose mentions "PASS/FAIL" — is the mapping unambiguous enough, or will it break?
3. **Trigger/description quality** — will the three skills fire on the right inputs and not steal each other's traffic? Any overlap or gap?
4. **Reference integrity & drift** — are any instructed `references/*.md` reads broken? Is the triplicated `shared-guardrails.md` a maintenance trap?
5. Anything else that would make a review **unreliable**, given the whole point is to be a source of truth.

## What Claude already found (verify, don't trust)

- **Critical:** the *installed* `software-reviewer` is missing its entire `references/` folder, but its `SKILL.md` (steps under "Before you start") instructs reading `references/shared-guardrails.md` and `references/review-checklist.md`. Both reads fail. The packaged `software-reviewer.skill` *does* contain them — so the package is correct but the live install is stale (reinstall fixes it).
- `shared-guardrails.md` is physically duplicated (byte-identical) in all three skills though it calls itself "the single canonical copy" — drift hazard.
- Project router files (`memory.md`, `agents.md`, `skills.md`) don't reference the three skills yet, and `memory.md` still locks "Pi 5 8GB + AI HAT+ 13 TOPS" while the skills' kit list says "Pi 5 4GB, no AI HAT on hand."

Be blunt. Rank issues by severity.
