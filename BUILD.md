# BUILD.md — Lullaby Build Runbook

Practical steps for rebuilding the active project. Legacy Raspberry Pi lab-bench instructions are not active Lullaby scope.

## 1. Run The Software Mock

```bash
python3 examples/sleep_monitor.py
```

Expected: local journal lines plus caregiver check alerts. No hardware, camera, network, or LLM required.

## 2. Run Tests

```bash
python3 tests/test_monitor.py
```

Expected: all tests pass.

## 3. Local Development Install

```bash
python3 -m pip install -e .
```

Optional Pi/webcam dependencies are not required for the mock path.

## 4. Hardware Boundary Before Any Build

- Keep hot compute in a vented base beside the cot.
- Do not place batteries, chargers, power supplies, or heat-generating boards in the cot.
- Keep cables strain-relieved and out of reach.
- Route uncertain physical decisions through Flomotion and a human hardware mentor.

## 5. Future Hardware Path

1. Prove the demo with replay/mock observations.
2. Add a laptop webcam perceiver or Pi camera perceiver.
3. Measure heat and reliability away from the cot.
4. Only then design an enclosure/base.

## Archive Note

The old Lab Witness Raspberry Pi/Hailo/lab-bench runbook is intentionally not active. Retrieve it from git history only if Mo explicitly asks to revive Lab Witness.
