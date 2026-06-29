"""A small, deterministic question-answerer over a live sensor snapshot.

The "brain" of the Beddington voice assistant. It maps a plain-language question
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
from .intent import INTENT_KEYWORDS, AskLlm, translate_intent

_FALLBACK = "Sorry, I didn't catch that. Please say it again."

# Vital-sign words. A question containing one is answered from the radar's bench
# data (Mo, the owner/physician, authorised this), routed first so a vitals
# question is never captured by the people-count, presence, motion, or overview
# branches. The answer is always a clearly-labelled rough radar estimate, never
# paired with reassurance, and says "no reading" honestly when the radar has no
# lock — see _vitals_phrase. It asserts nothing about the baby's wellbeing.
# Supported vitals: breathing and heart rate are the only signals the radar
# estimates, so only these route to the radar readout.
_VITALS_WORDS = (
    "breathing", "breath", "breaths", "breathe", "chest", "heart", "heartbeat",
    "heartrate", "pulse", "respiratory", "respiration", "bpm", "vital", "vitals",
)

# Vital signs the device does NOT measure. Routed first (before the room-pressure
# branch, so "blood pressure" never returns air pressure) to an honest "I don't
# have that reading", never a fabricated or mismatched value.
_UNSUPPORTED_VITALS = (
    "oxygen", "saturation", "spo2", "sats", "blood", "apnea", "apnoea", "fever",
)

# Wellbeing-check phrasings about the baby (not the room) — surface the radar
# vitals. Deliberately narrow phrases, not a bare "baby", so "is the baby
# asleep / crying / hungry" do NOT get answered with vitals numbers.
_BABY_VITALS_PHRASES = (
    "how is the baby", "how s the baby", "the baby okay", "the baby alright",
    "the baby doing", "check the baby", "check on the baby",
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


def _radar_breathing_lock(snapshot: dict[str, object]) -> bool:
    """A plausible breathing lock. The radar's vitals keys are only present when it
    has a genuine still-and-close lock (sensors.py drops implausible values to
    None), so a breathing value here means a real, still person — not clutter."""
    return _num(snapshot, "radar_respiratory_rate") is not None


def _radar_target_detected(snapshot: dict[str, object]) -> bool:
    """The radar reports a physical target — a measured distance or a target count
    of at least one — i.e. a real reflector in the beam, not just the bare flag."""
    count = _num(snapshot, "target_count")
    if count is not None and count >= 1:
        return True
    return _num(snapshot, "target_distance_cm") is not None


def radar_person_present(snapshot: dict[str, object]) -> bool:
    """Radar-driven presence (the PIR motion sensor has been removed).

    Trust the 60GHz radar's "person present" flag, but only when it is corroborated
    by a real target (a measured distance / target count) or a plausible breathing
    lock — so micro-vibration clutter can't read as a phantom person from the bare
    flag alone. The radar is the room's only presence sensor now.
    """
    if snapshot.get("person_present") is not True:
        return False
    return _radar_target_detected(snapshot) or _radar_breathing_lock(snapshot)


def _presence_phrase(snapshot: dict[str, object]) -> str:
    if radar_person_present(snapshot):
        return "Yes, I can detect someone in the room."
    # No radar reading at all (e.g. it is briefly offline / reconnecting) — hedge
    # rather than claim the room is empty from a missing reading.
    if snapshot.get("person_present") is None:
        return "I don't have a clear presence reading right now."
    # The radar is reporting but without a trustworthy person (flag false, or true
    # but uncorroborated clutter): no one.
    return "No, I don't detect anyone in the room right now."


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


def _vitals_phrase(snapshot: dict[str, object]) -> str:
    """A deterministic readout of the radar's breathing/heart values — or an
    honest "no reading" when the radar has no lock.

    Per Mo's preference the spoken answer carries no medical/safety disclaimer
    (this is a personal bench device, not a medical product). It still never
    interprets the numbers, never reassures, and never asserts the baby is well;
    and it never fabricates — the vitals keys are only present when bench_vitals
    is enabled AND the radar has a valid lock (still + close), so a missing
    reading yields the honest no-lock message.
    """
    resp = _num(snapshot, "radar_respiratory_rate")
    heart = _num(snapshot, "radar_heart_rate_bpm")
    if resp is None and heart is None:
        return (
            "I don't have a clear reading right now. The radar only picks up "
            "breathing and heart rate when the baby is very still and close."
        )
    bits: list[str] = []
    if resp is not None:
        bits.append(f"breathing about {resp:.0f} breaths a minute")
    if heart is not None:
        bits.append(f"heart rate about {heart:.0f} beats per minute")
    return "From the radar, " + ", and ".join(bits) + "."


def _unsupported_vitals_phrase() -> str:
    """For vital signs the device cannot measure (oxygen, blood pressure, fever):
    say so honestly rather than answering with the breathing/heart estimate."""
    return (
        "I can only read breathing and heart rate from the radar. I don't have "
        "that particular reading."
    )


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


# Questions that ask for the night recap rather than a current reading. The
# listen loop answers these from the persisted sensor history (night_digest.py),
# not the live snapshot.
_NIGHT_WORDS = (
    "the night", "overnight", "last night", "night summary", "summary",
    "recap", "digest", "how was the night", "how did the night",
)


def is_night_question(question: str) -> bool:
    """True if the question asks for the night recap (answered from history)."""
    return _mentions(normalize_transcript(question), *_NIGHT_WORDS)


# Soothe voice control: "play white noise", "soothe the baby", "stop the sound".
_SOOTHE_STOP_WORDS = ("stop", "silence", "turn off", "switch off", "enough", "no more", "shush")
_SOOTHE_PLAY_WORDS = ("play", "put on", "soothe", "comfort", "calm")


def _soothe_preset_from(q: str) -> str | None:
    if _mentions(q, "heartbeat", "heart beat"):
        return "heartbeat"
    if _mentions(q, "music", "song", "melody", "lullaby"):
        return "soothing_music"
    if _mentions(q, "whoosh", "womb", "uterine", "ocean"):
        return "uterine_whoosh"
    if _mentions(q, "white", "noise", "static", "hush"):
        return "white_noise"
    return None


def match_soothe_command(question: str) -> dict[str, str] | None:
    """Detect a soothe play/stop command, or None. Returns e.g.
    {"action": "play", "preset": "white_noise"} or {"action": "stop"}."""
    q = normalize_transcript(question)
    preset = _soothe_preset_from(q)
    context = preset is not None or _mentions(
        q, "soothe", "sound", "noise", "music", "playing", "it", "that", "crying", "cry"
    )
    if _mentions(q, *_SOOTHE_STOP_WORDS) and context:
        return {"action": "stop"}
    if _mentions(q, *_SOOTHE_PLAY_WORDS):
        return {"action": "play", "preset": preset or "white_noise"}
    return None


def answer_question(
    question: str,
    snapshot: dict[str, object],
    llm_translator: object | None = None,
    ask_llm: AskLlm | None = None,
) -> str:
    """Answer a plain-language question from the current sensor snapshot."""
    answer = _deterministic_answer_question(question, snapshot)
    if answer != _FALLBACK:
        return answer
    if llm_translator is None or not getattr(llm_translator, "enabled", False):
        return answer

    intent = translate_intent(question, llm_translator, ask_llm=ask_llm)
    if intent not in INTENT_KEYWORDS:
        return answer

    translated = _deterministic_answer_question(intent, snapshot)
    return translated if translated != _FALLBACK else answer


def _deterministic_answer_question(question: str, snapshot: dict[str, object]) -> str:
    q = normalize_transcript(question)

    # Unsupported vitals first (oxygen, blood pressure, fever...): say we don't
    # measure them — routed before the room-pressure branch so "blood pressure"
    # never returns air pressure.
    if _mentions(q, *_UNSUPPORTED_VITALS):
        return _unsupported_vitals_phrase()

    # Supported vitals next: an explicit breathing/heart/pulse question is answered
    # from the radar's bench data, routed before any other branch can capture a
    # vitals-flavoured question (even one with an incidental "still"/"moving"/
    # "warm" in it). The answer never reassures and never claims wellbeing.
    if _mentions(q, *_VITALS_WORDS):
        return _vitals_phrase(snapshot)

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

    # A wellbeing check about the baby (not the room) surfaces the labelled radar
    # vitals, checked after the specific room/presence/motion branches so "is the
    # baby too warm" still answers temperature and "is the baby moving" still
    # answers motion. Narrow phrases only, so "is the baby asleep/crying/hungry"
    # fall through to the fallback rather than being answered with vitals numbers.
    if _mentions(q, *_BABY_VITALS_PHRASES):
        return _vitals_phrase(snapshot)

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
