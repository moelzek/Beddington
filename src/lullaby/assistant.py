"""A small, deterministic question-answerer over a live sensor snapshot.

This is the "brain" of the Lullaby voice assistant. It maps a plain question
("what's the humidity?") to an answer built directly from the current sensor
readings — no LLM, so it cannot invent a value. Vital signs (breathing/heart)
are deliberately not answered here: they stay raw bench data, never spoken as a
health reading.
"""

from __future__ import annotations

from .context import describe_presence_scene

_FALLBACK = (
    "I can tell you about the room: temperature, humidity, air pressure, "
    "air quality, brightness, or whether someone is nearby."
)


def _num(snapshot: dict[str, object], key: str) -> float | None:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def answer_question(question: str, snapshot: dict[str, object]) -> str:
    """Answer a plain-language question from the current sensor snapshot."""
    q = question.lower()

    if "humid" in q:
        value = _num(snapshot, "room_humidity_pct")
        if value is not None:
            return f"The humidity is about {value:g} percent."

    if any(word in q for word in ("temperature", "warm", "hot", "cold", "degree")):
        value = _num(snapshot, "room_temperature_c")
        if value is not None:
            return f"The room is about {value:g} degrees Celsius."

    if "pressure" in q:
        value = _num(snapshot, "room_pressure_hpa")
        if value is not None:
            return f"The air pressure is about {value:g} hectopascals."

    if any(word in q for word in ("air quality", "gas", "smell", "voc", "stuffy", "nappy")):
        value = _num(snapshot, "room_gas_resistance_ohms")
        if value is not None:
            return (
                f"The air-quality gas reading is about {value / 1000:.0f} kilo-ohms. "
                "Higher means cleaner air."
            )

    if any(word in q for word in ("light", "bright", "dark", "lux")):
        value = _num(snapshot, "room_illuminance_lx")
        if value is not None:
            return f"The room brightness is about {value:g} lux."

    if any(word in q for word in ("how far", "distance", "close")):
        value = _num(snapshot, "target_distance_cm")
        if value is not None:
            return f"The nearest person is about {value:g} centimetres away."

    if any(
        word in q
        for word in ("present", "anyone", "someone", "is there", "nearby", "in the room")
    ):
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
