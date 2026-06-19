# skills.md — Lullaby (tools and routing)

Use this for active Lullaby work. Legacy Lab Witness reviewer skills are archived unless rewritten for Lullaby.

| Situation | Tool / skill | Use when |
|---|---|---|
| Hardware, enclosure, wiring, power, thermal, camera placement | Flomotion prompt, then human mentor review if risky | Any physical build decision near a cot or power source. |
| Bug or unexpected behaviour | `investigate` / systematic debugging | Reproduce, isolate root cause, then fix. |
| UI or caregiver flow | design review / browser QA tools | When testing the local dashboard, mock app, or alert flow. |
| Docs or product boundary drift | Direct doc edit + `memory.md` update | Medical/privacy/hardware constraints changed or were violated. |
| Security/privacy review | `cso` | Before any network, cloud, auth, storage, or media export feature. |
| PDF/deck/demo material | `pptx`, `make-pdf` | Only after the v0 behaviour is stable. |

## Current Tooling Notes

- The active Python package is `lullaby`.
- `reviewer-skills/` contains Lab Witness-era skills. Do not rely on them for Lullaby safety without rewriting their prompts/checklists.
- Do not add cloud media upload, face identity, or health-risk scoring tools without an explicit new decision from Mo.
