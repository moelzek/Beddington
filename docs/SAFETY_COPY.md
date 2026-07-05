# Safety Copy

This guide is for anyone writing parent-facing Beddington strings. Human copy
and AI-generated copy must follow the same rules. Code is canonical when there
is a conflict.

## Non-Negotiables

From `ASSISTANT-EXPANSION-PLAN.md` lines 8-18:

1. **Never fabricate a sensor reading.** The deterministic brain stays the fact source.
2. **No reassurance / no medical claim about the baby.** Never say the baby is safe / asleep / sleeping / healthy / fine / well / okay / normal / calm / settled / content / at peace, and never give medical advice.
3. **The cry->alarm reflex (`pipeline.run_pipeline`) is untouched.**
4. **LLM persona only RE-VOICES** the deterministic answer. New verbatim answers must not be sent to the LLM.
5. Offline only - no network calls, no internet lookups.

## Voice Principles

- Observe, do not infer.
- Say what the sensors saw and how old the reading is.
- Hedge derived states with "best guess".
- Say missing data plainly: "No presence reading" is not the same as "No one detected".
- Never diagnose.
- Never reassure.
- Never turn absence of evidence into evidence of safety, health, sleep, or wellbeing.

## Banned Words

Code is canonical: `persona._BANNED_WORDS` in
`src/beddington/persona.py:91` is the source list. As of this doc, it is:

```text
asleep
breathing
calm
content
contentedly
cosy
cozy
dozing
fine
good
healthy
heart
normal
normally
ok
okay
peaceful
peacefully
pulse
respiratory
resting
safe
serene
settled
sleep
sleeping
slept
slumber
slumbering
snug
soundly
stable
tantrum
tranquil
well
```

The assistant vitals tests also enforce this reassurance set at
`tests/test_assistant.py:245`:

```text
fine
safe
healthy
normal
normally
okay
asleep
sleeping
well
good
stable
calm
settled
```

And these phrases at `tests/test_assistant.py:249`:

```text
breathing normally
he s okay
rayan is okay
all good
perfectly fine
doing well
```

Do not use these about the baby, baby state, or vitals. Room-only copy has a
narrow exception where existing deterministic modules describe room conditions,
such as pressure or temperature.

## Mandatory Exact Strings

| String | Where it ships | Rule |
|---|---|---|
| `LAN only · no cloud · no recording · no audio streaming` | `src/beddington/liveview.py:377` and `src/beddington/liveview.py:392` | Use exactly for the privacy badge. |
| `rough radar estimate` | `src/beddington/liveview.py:751` | Use exactly for radar vitals. Do not interpret it as health. |
| `It is not a medical device` framing | `README.md:154` | Preserve the "not a medical device" meaning in parent-facing safety text. |

## Alerts and Confidence

- Cry alerts state duration and score plainly: "Crying detected — {m} min" and "cry score {score}".
- Do not call cry score a probability, percent, chance, or certainty.
- Confidence is a band: low, medium, or high.
- Confidence needs a basis, such as "missing presence reading" or "fresh presence + motion reading".
- Recommended actions are suggestions: "worth a look", "check the camera", "adjust room".
- Never write instructions, diagnoses, or promises.

## Do and Don't Examples

| Situation | Do | Don't |
|---|---|---|
| Active cry alert | `Crying detected — {m} min` | `The baby is definitely distressed.` |
| Sensor issue | `Sensors need attention` | `The baby needs attention.` |
| Missing presence data | `No presence reading` | `No one detected` when there was no reading. |
| False presence reading | `No one detected` | `The room is empty.` |
| Multiple radar targets | `Someone's in the room — {n} radar targets` | `Mum is in the room.` |
| Motion | `Moving in the last {n} min` | `The baby is restless.` |
| Stillness | `Still for {n} min · best guess` | `The baby is asleep.` |
| Quiet movement pattern | `Quiet, occasional movement · best guess` | `The baby is calm.` |
| Unclear state | `Not sure right now — check the camera` | `Everything is fine.` |
| Vitals | `rough radar estimate` | `Breathing normally.` |
| Warm room | `Room temperature is outside the usual 16-20°C range.` | `The baby is too hot.` |
| First-night history | `I don't have enough history yet for a night summary.` | `No problems overnight.` |

The "Do" strings come from `live_snapshot.py:_label` and
`docs/LIVEVIEW-UI-SPEC.md` Section 8.

## New Copy Checklist

Before adding or changing parent-facing copy:

1. Scan for `persona._BANNED_WORDS`.
2. Scan for the assistant `_REASSURANCE` words and phrases.
3. Check the sentence is observational, not inferential.
4. Include source and age when a reading is involved.
5. Add "best guess" for derived stillness, quietness, or pattern labels.
6. Say missing data as missing data.
7. Add or update a test for the copy surface.
8. Update `docs/LIVEVIEW-UI-SPEC.md` Section 8 if the copy belongs in the catalogue.

## Cross-Links

- `docs/LIVEVIEW-UI-SPEC.md` Section 8 is the copy catalogue.
- `README.md` "Privacy and safety" is the public privacy and medical-device framing.
