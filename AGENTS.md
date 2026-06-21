# AGENTS.md — how to work on Lullaby

> Codex reads `AGENTS.md` by default. Claude Code reads `CLAUDE.md`. This file
> is the canonical agent operating manual for Codex and replaces the old
> lowercase `agents.md` name. Project facts live in [memory.md](memory.md).

## Before work

1. Run persistent-memory recall:

   ```bash
   engram recall "<task in 4-6 words>" --top-k 5 --json
   ```

2. Read `memory.md` and check the active tier. `memory.md` wins if any document
   disagrees.
3. Read `CLAUDE.md` for document order, project rules, version control, and
   sign-off format.
4. After learning a stable preference, decision, correction, or project fact,
   save it with `engram remember`.

## Working style

- Explain software and hardware in plain English. Define jargon briefly.
- Keep steps small and ADHD-friendly.
- After each completed step, state exactly what Mo should run and what he should see.
- Prefer simple, reliable code over clever abstractions.
- Use British English in project prose.
- Flag uncertainty. Do not invent hardware specifications, model performance, or safety claims.

## Build discipline

1. Read `memory.md` and check the active tier.
2. Work only inside that tier.
3. Develop and test with files/mocks before relying on Pi hardware.
4. Put hardware-specific behaviour behind an adapter interface.
5. Keep detection/timing deterministic and testable.
6. Keep cloud/LLM behaviour optional and disabled by default.
7. Run focused tests and one end-to-end sample before committing.
8. Update `memory.md` and its changelog when status or decisions change.
9. Commit each logical unit. Never include secrets or private recordings.

## Non-negotiable review checks

- No medical or safety claims.
- No raw audio/video off-device.
- No unlabelled inference presented as fact.
- No hot compute in a plush toy or cot.
- No later-tier work without Mo's explicit approval.
- No required API key for core operation.

## Definition of done for a user-facing step

Mo has:

1. one command to run;
2. a short description of the expected output;
3. a clear next action if it works;
4. a useful error message or troubleshooting note if it fails.
