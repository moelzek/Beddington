# Flomotion hand-off — file structure and paste-ready format

Flomotion is the **external executor**: it generated the candidate and it applies
the fixes. Your hand-off has two destinations — a dated file on disk (the record)
and a paste-ready block in chat (the thing Mo actually pastes into Flomotion).
Keep "what to do" separate from "who does it" so the executor target can be
swapped later without rewriting the fixes.

## The dated file

Write to `/Users/elzekmo/Code/Labie/` with a dated name:

```
flomotion-cto-review-YYYY-MM-DD.md
```

If more than one review runs the same day, append a short slug:
`flomotion-cto-review-2026-06-13-gripper-wiring.md`.

### File structure

```markdown
# Flomotion CTO review — <one-line outcome>
Date: YYYY-MM-DD
Setpoint: <the one-sentence outcome>
Done-when: <the concrete, testable success line>
Reviewers dispatched: hardware-reviewer | software-reviewer | both

## Reconciled verdict
<Approve | Revise | Reject  —or—  Safe-to-build | Do-not-build>
Conditions to clear:
- <condition>  (or "none outstanding")

## Risk + blocker flags
- <terse line per risk/blocker; safety items marked ESCALATE-TO-MENTOR>

## Fix-prompts for Flomotion (ranked)
1. <specific, self-contained fix the executor can apply without guessing>
2. ...

## Ranked mentor questions
1. <question> — <one-line reason it matters>
2. ...

## Evidence
<what each reviewer checked and found; cite the reviewer>
```

## The paste-ready chat block

After writing the file, surface a block in chat that Mo can paste straight into
Flomotion with **no editing**. It is the deep technical register only — Flomotion
doesn't need the beginner explanation. Make each fix-prompt self-contained: state
the target, the current problem, and the desired end state, so the executor never
has to infer context it wasn't given.

Format it so it reads as an instruction set to an agent, not a report to a human:

```
For Flomotion — apply the following fixes to <component/module>:

Verdict: <…>  | Done-when: <…>

FIX 1 — <title>
  Problem: <what's wrong, precisely>
  Change:  <exact end state to reach>
  Check:   <how to confirm it's fixed>

FIX 2 — …

Do not change anything outside these fixes. If a fix depends on a value you
don't have, stop and flag it rather than assuming one.
```

That last line carries Rule #1 (never fabricate specs) downstream to the
executor — so the no-fabrication contract holds even after the hand-off leaves
your hands.

## Swappable target

Keep the fix-prompts written against the work, not against Flomotion
specifically. The only Flomotion-specific thing is the addressing line ("For
Flomotion —"). If Mo later swaps executors, only that line changes; the fixes
themselves carry over unchanged.
