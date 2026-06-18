# Software & LLM review checklist

Work through the dimensions relevant to the suggestion under review. You don't have to touch every row every time — pick what applies and say which ones you checked (Rule #4). For each finding, decide PASS or FAIL and attach evidence (a traceable reason, a calculation, a doc reference, or a test you can describe). Never invent behaviour to fill a gap — unknowns become mentor questions (Rule #1).

## Table of contents
1. Correctness & logic
2. Edge cases & failure modes
3. Concurrency & timing
4. Resource limits on target hardware
5. Reality check — does the claimed thing exist?
6. LLM / agentic design
7. Hardware-driving software (safety bridge)

---

## 1. Correctness & logic
- Does the code/logic actually do what the setpoint says? Trace the happy path end to end.
- Off-by-one, inverted conditions, wrong operator, state never reset between cycles.
- For the Lab Witness pipeline (Perception → State machine → Decision → Act): does each stage hand the next the shape of data it expects? A state machine that can't reach a terminal state, or a transition with no trigger, is a FAIL.

## 2. Edge cases & failure modes
- What happens on empty input, no detection, partial detection, camera frame dropped, Notion API down, network gone?
- Does a single failed stage crash the loop, or degrade gracefully? For a bench-watching device that must run unattended, an uncaught exception that kills the process mid-protocol is a FAIL.
- Are errors observable (logged/flagged) or silent? Silent failure on a "witness" device defeats its purpose.

## 3. Concurrency & timing
- Frame capture, inference, and I/O (Notion write, OLED flag) — are they on the same thread fighting for time, or separated? A blocking Notion write inside the capture loop will drop frames.
- Race conditions on shared state (the current protocol step, the deviation flag).
- Timing-only deviations are the v0 detection signal — is the clock source monotonic and is the timing measured where it's actually meaningful, not where it's convenient?

## 4. Resource limits on target hardware
Target for v0: **Raspberry Pi 5, 4 GB RAM + AI HAT+ 26 TOPS (Hailo-8), on hand & fitted.** Vision runs Hailo-accelerated detection; the state machine + timing logic run on the CPU. Hardware acceleration **is** available for v0 (the Hailo-8 NPU).
- Will the model / pipeline fit in 4 GB alongside the OS? If you can't bound the memory, say so and make it a mentor question — don't assert a number you can't back.
- Is the per-frame latency budget realistic? The detector runs on the Hailo-8 (NPU); the CPU carries the state machine + timing. A detector that *only* hits frame rate on a bigger accelerator than the Hailo-8 is a FAIL for v0 unless downgraded.
- Disk (32 GB microSD), thermal throttling under sustained load (Active Cooler is present), USB bandwidth if multiple cameras.
- The AI HAT+ (Hailo-8) **is** on hand — code may rely on it for v0. Flag anything needing *more* than the Hailo-8 (a discrete GPU, a second accelerator, >4 GB RAM) as "needs hardware Mo doesn't have" → mentor question.

## 5. Reality check — does the claimed thing exist?
- Library/API: is the function, method, or argument real in the version being used? `picamera2`, `opencv-python`, `mediapipe`, the Notion SDK — signatures drift between versions. If unsure, flag it; do not reconstruct an API from memory (Rule #1).
- Model: does the named model exist, run locally, and have the claimed capability and size? Vision-model capability claims are a common hallucination source.
- Performance numbers: any "runs at X fps / uses Y MB" claim that isn't measured or calculated is suspect — mark it unverified.

## 6. LLM / agentic design (when the suggestion involves a prompt, model call, or agent)
- Is the task actually suited to an LLM, or is a deterministic rule cheaper and more reliable? For v0, prefer deterministic where it works — fewer failure modes, no latency tax.
- Prompt: is the instruction unambiguous, are output format and failure behaviour specified, is untrusted input (e.g. anything derived from the camera) kept out of the instruction channel?
- Agentic loop: is there a stop condition / budget, or can it loop forever? Are tool calls validated before acting? What happens when the model returns malformed output?
- Determinism & cost: does this call run on-device or off? If it sends data off-device, does that violate the local-first / "no faces leave the device" constraint? That's a FAIL on a privacy-critical build.
- Eval: how would Mo know this prompt/agent is working? If there's no way to tell right from wrong output, that's a gap worth flagging.

## 7. Hardware-driving software (safety bridge — see Rule #2)
- Does any code command a motor, servo (SG90/PCA9685 are parked for v0), actuator, or power path? If so, can it command an unsafe state (past travel limit, stall, over-current)?
- Is there a watchdog / safe default if the controller hangs?
- If yes to any risk: flag for on-site mentors and note it also belongs to `hardware-reviewer`.
