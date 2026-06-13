# skills.md — Lab Witness (WHICH tools, and WHEN)

> Routing guide for skills, connectors and tools on this project. Pairs with [agents.md](agents.md) (how) and [context.md](context.md) (what). Only the tools actually relevant to a 12-day Pi build sprint are listed; everything else is out of scope.

## Routing table — situation → reach for this

| Situation | Skill / connector / tool | Use when |
|---|---|---|
| A hardware question (wiring, specs, NPU, camera, mount) | `prompt-engineer` → draft a Flomotion prompt | Always route hardware through the Flomotion loop — you craft the prompt, Mo pastes it, you review the answer. Never answer as the authority. |
| Review a Flomotion/mentor answer spanning **both** hardware + software, or "is this safe to build?" | `flomotion-cto` skill | The orchestrator: decomposes the input, dispatches to the reviewer skills, reconciles to one Approve/Revise/Reject (or Safe-to-build/Do-not-build) gate, hands fix-prompts back to Flomotion. |
| Review a **hardware** design only (board, wiring, power, 3D part, mount) | `hardware-reviewer` skill | PASS/FAIL with evidence + beginner Mermaid diagram + Safe-to-build gate + ranked mentor questions. Owns hardware-safety escalation. |
| Review **software / control logic / LLM-agent** design only | `software-reviewer` skill | PASS/FAIL + beginner diagram + Approve/Revise/Reject gate + mentor questions. |
| Rig or code won't work | `systematic-debugging` | Camera not detected, detection flaky, state machine misfiring, Notion write failing — isolate before fixing. |
| Build/spec on Pi-specific APIs | `mcp-builder` only if wiring a custom MCP; otherwise just reference `picamera2/examples/hailo` | Rare. Most rig code is plain Python on the Pi, outside this chat. |
| Write the timestamped lab-notebook entry | **Notion** connector (`notion-*` tools) | The "Act" step. Model the write on Mo's existing **Granola → Notion** pipeline. Probe the actual tool response shape before building automation. |
| Demo Night deck | `pptx` | Building the slide deck (after v0 freeze, week-two narrative work). |
| Demo visuals / poster / diagram styling | `canvas-design`, `theme-factory` | One-off visuals or theming the deck. |
| Sprint reminders / recurring check-in | `schedule` | "remind me each morning", daily reconcile task. |
| Book a call (e.g. with the CV dev or a mentor) | `calendar-invite` | Any attendee + time combo. |
| Mo signals stress / overwhelm | `lori-therapist` | ADHD + newborn + Frontier Biotech attention collapse. Wellbeing first. |
| Need to verify a stat for a slide | `WebSearch` | Before quoting Baker 2016 figures or any kit spec on a slide. |
| Quick hackathon-logistics help | `hackathon-organiser` | Submission checklist, judging-axis framing, pitch structure. |

## Connector gotchas observed (Phase 1)

- **Notion** is the lab-notebook target and the most important connector here. Before building any automated write, call the tool once and inspect the real response shape — MCP wrappers rename params and reshape output. Reuse the structure of Mo's working Granola→Notion flow rather than inventing a new schema.
- **Granola** (meeting notes) is referenced only as the *model* for the Notion write pipeline, not a live dependency of the rig.
- **Flomotion is not an MCP connector** — it's an external app Mo drives manually. The interface is copy-paste prompts, not tool calls.

## Out of scope / do NOT reach for

- **PubMed, ChEMBL, Open Targets, biorxiv, clinical-trials, and other bio-research connectors** — these map to the v2 "context pulls" roadmap, **not** v0. Don't wire them in during the sprint.
- **protocols.io integration** — v2 only.
- **Finance, sales, CRM, marketing, SEO, legal, design-system, and the large enterprise-plugin suites** (Carta, Salesforce, ZoomInfo, Daloopa, etc.) — irrelevant to this project. Ignore.
- **Heavy CV/ML training skills or single-cell/RNA bio pipelines** — the technical bet is deliberately *small* (detector + state machine + clock). Don't pull in model-training machinery; it's scope creep against 20 Jun.
- **Anything that recognises faces or fine motor / gestures** — excluded by design and by the privacy boundary (local-first, no faces leave the device).

## Reminder

When a tool result is linkable (Notion pages, etc.), cite it. When you've rendered live state as a table Mo will want again, offer to turn it into a live artifact. Keep every recommendation pointed at the single next action.
