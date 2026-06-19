# Lullaby

Privacy-first baby-monitor companion. Raw audio/video stays on-device, deterministic detection works with the LLM off, and the product avoids medical claims.

Lab Witness is retired. Legacy Lab Witness docs and reviewer skills remain only as archive/reference until explicitly rewritten.

## Try It Now

Run the no-hardware mock monitor:

```bash
python3 examples/sleep_monitor.py
```

Run the tests:

```bash
python3 tests/test_monitor.py
```

## What V0 Does

- Watches a cot-side camera or replay stream locally.
- Converts frames/audio levels into simple observations.
- Applies deterministic rules first: no LLM required for core behaviour.
- Logs local status events.
- Alerts a caregiver to check the baby when a configured condition persists.
- Never claims the baby is safe, diagnoses sleep or breathing, or prevents SIDS.

## Architecture

```text
[Local sensor stream] -> [Perceiver] -> [LullabyMonitor rules]
                                      -> [Local journal]
                                      -> [Caregiver check alert]
```

- `lullaby/monitor.py` contains the deterministic rule engine.
- `lullaby/runtime.py` contains perceiver and output seams.
- `examples/sleep_monitor.py` demonstrates a scripted run.
- `tests/test_monitor.py` covers the core rules.

## Hardware Boundary

Hot compute belongs in a vented base beside the cot, not in the cot. Any camera/audio hardware decision should be checked against this boundary before build work starts.

## Legacy Material

Files named `lab-witness-*`, `lab_witness/` references in git history, `reviewer-skills/`, and `Archive/` are Lab Witness-era material. Do not treat them as active Lullaby requirements.
