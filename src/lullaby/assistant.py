"""A small, deterministic question-answerer over a live sensor snapshot.

The "brain" of the Paddington voice assistant. It maps a plain-language question
to an answer built directly from the current sensor readings — no LLM, so it can
never invent a value. Answers interpret the reading (comfortable / a bit warm /
dry / dimly lit / clean) using ordinary nursery comfort ranges, framed as gentle
guidance, never a medical or safety claim. Vital signs (breathing/heart) are
deliberately never answered.

Routing is intent-based: vital-sign questions are refused first; specific
readings are matched next; a general "how is the room?" gives a whole-room
overview; "how many people?" counts; and "is anyone there?" answers presence
plainly. Numbers a parent can't act on (hectopascals, kilo-ohms, lux) are spoken
as plain interpretations, not raw figures.
"""

from __future__ import annotations

import math

from .ears import _edit_distance, normalize_transcript

_FALLBACK = "Sorry, I didn't catch that. Please say it again."

# Vital-sign words. Any question containing one is refused outright (returns the
# fallback) before any branch can answer it — the medical-claim boundary. Checked
# first so "how many breaths" / "is she still breathing" / "heart rate" never
# reach the people-count, presence, or motion branches.
_VITALS_WORDS = (
    "breathing", "breath", "breaths", "breathe", "heart", "heartbeat",
    "heartrate", "pulse", "respiratory", "respiration", "bpm", "vital",
    "vitals", "oxygen", "apnea", "apnoea", "saturation",
)


def _num(snapshot: dict[str, object], key: str) -> float | None:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mentions(question: str, *keywords: str, fuzzy: tuple[str, ...] = ()) -> bool:
    """True if the question contains a keyword (whole word for single words so
    'shot' != 'hot'; substring for phrases), or a word within edit-distance 1 of
    a fuzzy target (so a misheard 'temprature' still matches 'temperature' while
    avoiding distance-2 collisions like 'pleasure'~'pressure')."""
    words = question.split()
    for keyword in keywords:
        if " " in keyword:
            if keyword in question:
                return True
        elif keyword in words:
            return True
    for target in fuzzy:
        for word in words:
            if abs(len(word) - len(target)) <= 1 and _edit_distance(word, target) <= 1:
                return True
    return False


# --- short interpretation labels (shared by single answers and the overview) ---


def _temp_label(c: float) -> str:
    return "comfortable" if 16 <= c <= 20 else ("a bit cool" if c < 16 else "a bit warm")


def _humid_label(h: float) -> str:
    return "comfortable" if 40 <= h <= 60 else ("a bit dry" if h < 40 else "a bit humid")


def _air_label(ohms: float) -> str:
    kohm = ohms / 1000
    if kohm >= 50:
        return "seems clean"
    return "seems okay" if kohm >= 20 else "seems a bit stuffy"


def _bright_label(lux: float) -> str:
    """A bare descriptor so it reads cleanly both alone and inside the overview."""
    if lux < 10:
        return "dark"
    if lux < 50:
        return "dimly lit"
    return "softly lit" if lux < 200 else "bright"


def _pressure_label(p: float) -> str:
    if p < 1000:
        return "on the low side"
    return "normal" if p <= 1025 else "on the high side"


# --- full single-reading phrases ---
# Temperature and humidity keep their number plus the interpretation; pressure,
# air quality and brightness are spoken as pure interpretations (the raw
# hectopascals / kilo-ohms / lux mean nothing to a parent). Commas, not em-dashes,
# so a TTS voice pauses naturally.


def _temperature_phrase(c: float) -> str:
    if 16 <= c <= 20:
        return f"The room is about {c:.0f} degrees Celsius, comfortable for a baby."
    side = "cool" if c < 16 else "warm"
    return (
        f"The room is about {c:.0f} degrees Celsius, a bit {side} for a baby; "
        "around 16 to 20 degrees is the usual comfortable range."
    )


def _humidity_phrase(h: float) -> str:
    if 40 <= h <= 60:
        return f"The humidity is about {h:.0f} percent, comfortable."
    side = "dry" if h < 40 else "humid"
    return (
        f"The humidity is about {h:.0f} percent, a bit {side}; "
        "40 to 60 percent is the usual comfortable range."
    )


def _pressure_phrase(p: float) -> str:
    return f"The air pressure is {_pressure_label(p)}."


def _air_quality_phrase(ohms: float) -> str:
    return f"The air quality {_air_label(ohms)}."


def _brightness_phrase(lux: float) -> str:
    if lux < 10:
        return "It's dark in here, nice and dim for sleep."
    return f"The room is {_bright_label(lux)}."


# --- presence and people ---


def _presence_phrase(snapshot: dict[str, object]) -> str:
    present = snapshot.get("person_present")
    motion = snapshot.get("motion_detected")
    if present is True:
        return "Yes, I can detect someone in the room."
    if present is False:
        if motion is True:
            return "There's some movement, but I don't detect a person in the room."
        return "No, I don't detect anyone in the room right now."
    # No radar presence reading — only motion (PIR) to go on, so hedge rather
    # than claim the room is empty from a missing reading.
    if motion is True:
        return "There's some movement, but I don't have a clear presence reading."
    return "I don't have a clear presence reading right now."


def _people_phrase(snapshot: dict[str, object]) -> str:
    count = _num(snapshot, "target_count")
    if count is None:
        return _presence_phrase(snapshot)
    n = round(count)
    if n <= 0:
        return "I don't detect anyone in the room right now."
    if n == 1:
        return "I detect about one person in the room."
    return f"I detect about {n} people in the room."


def _room_overview(snapshot: dict[str, object]) -> str:
    parts: list[str] = []
    t = _num(snapshot, "room_temperature_c")
    if t is not None:
        parts.append(f"it's about {t:.0f} degrees, {_temp_label(t)}")
    h = _num(snapshot, "room_humidity_pct")
    if h is not None:
        parts.append(f"humidity is {h:.0f} percent, {_humid_label(h)}")
    p = _num(snapshot, "room_pressure_hpa")
    if p is not None:
        parts.append(f"air pressure is {_pressure_label(p)}")
    g = _num(snapshot, "room_gas_resistance_ohms")
    if g is not None:
        parts.append(f"the air {_air_label(g)}")
    lx = _num(snapshot, "room_illuminance_lx")
    if lx is not None:
        parts.append(f"the lighting is {_bright_label(lx)}")
    if not parts:
        return "I don't have any room readings right now."
    return "Here's the room: " + "; ".join(parts) + "."


def answer_question(question: str, snapshot: dict[str, object]) -> str:
    """Answer a plain-language question from the current sensor snapshot."""
    q = normalize_transcript(question)

    # Safety first: refuse anything that sounds like a vital sign, before any
    # branch (people-count, presence, motion...) can capture a vitals-flavoured
    # question — even one with an incidental "still"/"moving"/"warm" in it.
    if _mentions(q, *_VITALS_WORDS):
        return _FALLBACK

    # Specific readings first, so "how warm is the room" routes to temperature
    # rather than the general overview.
    if _mentions(
        q, "temperature", "warm", "hot", "cold", "chilly", "degree", "degrees",
        fuzzy=("temperature",),
    ):
        value = _num(snapshot, "room_temperature_c")
        if value is not None:
            return _temperature_phrase(value)

    if _mentions(q, "humid", "humidity", "muggy", "dry", "damp", fuzzy=("humidity",)):
        value = _num(snapshot, "room_humidity_pct")
        if value is not None:
            return _humidity_phrase(value)

    if _mentions(q, "pressure", "barometer", fuzzy=("pressure",)):
        value = _num(snapshot, "room_pressure_hpa")
        if value is not None:
            return _pressure_phrase(value)

    if _mentions(
        q, "air quality", "gas", "smell", "smelly", "voc", "stuffy", "fresh", "nappy",
        fuzzy=("quality",),
    ):
        value = _num(snapshot, "room_gas_resistance_ohms")
        if value is not None:
            return _air_quality_phrase(value)

    if _mentions(
        q, "light", "lighting", "lit", "bright", "dark", "dim", "lux",
        fuzzy=("brightness",),
    ):
        value = _num(snapshot, "room_illuminance_lx")
        if value is not None:
            return _brightness_phrase(value)

    if _mentions(q, "how many", "number of people", "headcount", "count"):
        return _people_phrase(snapshot)

    # Motion before presence, so "is there any movement" reaches motion rather
    # than being captured by a generic presence phrase.
    if _mentions(q, "moving", "movement", "motion", "still", "activity"):
        motion = snapshot.get("motion_detected")
        if isinstance(motion, bool):
            return "There's movement in the room." if motion else "The room is still."

    if _mentions(
        q, "anyone", "anybody", "someone", "somebody", "everyone", "everybody",
        "nearby", "occupied", "empty", "who", "people", "person",
    ):
        return _presence_phrase(snapshot)

    if _mentions(q, "how far", "distance", "close"):
        value = _num(snapshot, "target_distance_cm")
        if value is not None:
            return f"The nearest person is about {value:.0f} centimetres away."

    # General "how is the room?" — a whole-room overview, checked last so specific
    # questions win.
    if _mentions(
        q, "how is the room", "room condition", "condition", "everything", "overview",
        "how are things", "status", "report", "summary", "rundown", "how is it",
        "in here", "in there", "the room", "room like", "what s it like",
        "comfortable", "cozy", "cosy", "nice",
    ):
        return _room_overview(snapshot)

    return _FALLBACK
