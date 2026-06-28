"""A small, deterministic question-answerer over a live sensor snapshot.

This is the "brain" of the Lullaby voice assistant. It maps a plain question
("what's the humidity?") to an answer built directly from the current sensor
readings — no LLM, so it cannot invent a value. Vital signs (breathing/heart)
are deliberately not answered here: they stay raw bench data, never spoken as a
health reading.
"""

from __future__ import annotations

from .context import describe_presence_scene
from .ears import _edit_distance, normalize_transcript

_FALLBACK = "Sorry, I didn't catch that. Please say it again."


def _num(snapshot: dict[str, object], key: str) -> float | None:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mentions(question: str, *keywords: str, fuzzy: tuple[str, ...] = ()) -> bool:
    """True if the question contains a keyword (whole word for single words, so
    'shot' does not match 'hot'; substring for phrases), or a word that is a
    near-miss of a fuzzy target ('temprature' still matches 'temperature')."""
    words = question.split()
    for keyword in keywords:
        if " " in keyword:
            if keyword in question:
                return True
        elif keyword in words:
            return True
    for target in fuzzy:
        for word in words:
            if abs(len(word) - len(target)) <= 2 and _edit_distance(word, target) <= 2:
                return True
    return False


def answer_question(question: str, snapshot: dict[str, object]) -> str:
    """Answer a plain-language question from the current sensor snapshot."""
    q = normalize_transcript(question)

    if _mentions(q, "humid", fuzzy=("humidity",)):
        value = _num(snapshot, "room_humidity_pct")
        if value is not None:
            return f"The humidity is about {value:g} percent."

    if _mentions(
        q, "temperature", "warm", "hot", "cold", "degree", fuzzy=("temperature",)
    ):
        value = _num(snapshot, "room_temperature_c")
        if value is not None:
            return f"The room is about {value:g} degrees Celsius."

    if _mentions(q, "pressure", fuzzy=("pressure",)):
        value = _num(snapshot, "room_pressure_hpa")
        if value is not None:
            return f"The air pressure is about {value:g} hectopascals."

    if _mentions(
        q, "air quality", "gas", "smell", "voc", "stuffy", "nappy", fuzzy=("quality",)
    ):
        value = _num(snapshot, "room_gas_resistance_ohms")
        if value is not None:
            return (
                f"The air-quality gas reading is about {value / 1000:.0f} kilo-ohms. "
                "Higher means cleaner air."
            )

    if _mentions(q, "light", "bright", "dark", "lux", fuzzy=("brightness",)):
        value = _num(snapshot, "room_illuminance_lx")
        if value is not None:
            return f"The room brightness is about {value:g} lux."

    if _mentions(q, "how far", "distance", "close", fuzzy=("distance",)):
        value = _num(snapshot, "target_distance_cm")
        if value is not None:
            return f"The nearest person is about {value:g} centimetres away."

    if _mentions(q, "present", "anyone", "someone", "is there", "nearby"):
        scene = describe_presence_scene(
            snapshot.get("person_present"), snapshot.get("motion_detected")
        )
        if scene is not None:
            return f"Best guess: {scene}."

    if any(word in q for word in ("moving", "movement", "motion", "still")):
        motion = snapshot.get("motion_detected")
        if isinstance(motion, bool):
            return "There's movement in the room." if motion else "The room is still."

    return _FALLBACK
