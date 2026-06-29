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
from collections.abc import Mapping
from dataclasses import dataclass

from .ears import _edit_distance, normalize_transcript
from .intent import INTENT_KEYWORDS, AskLlm, translate_intent

_FALLBACK = "Sorry, I didn't catch that. Please say it again."


@dataclass
class ConversationMemory:
    """Tiny carry-over for voice follow-ups; no free-form conversation state."""

    last_intent: str | None = None


@dataclass(frozen=True)
class _AnswerResult:
    answer: str
    intent: str | None = None

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


# Soothe voice control: "play rain", "soothe the baby", "stop the sound".
_DEFAULT_SOOTHE_PRESETS = {
    "white_noise": "white noise",
    "heartbeat": "heartbeat",
    "soothing_music": "soothing music",
    "uterine_whoosh": "uterine whoosh",
    "pink_noise": "pink noise",
    "rain": "rain",
    "ocean_waves": "ocean waves",
    "forest_breeze": "forest breeze",
    "night_sky": "night sky",
    "music_box_lullaby": "music box lullaby",
    "shushing": "shushing",
    "fan_hum": "fan hum",
}
_SOOTHE_STOP_WORDS = (
    "stop",
    "silence",
    "turn off",
    "switch off",
    "enough",
    "no more",
    "shush",
)
_SOOTHE_PLAY_WORDS = ("play", "put on", "soothe", "comfort", "calm")
_SOOTHE_GENERIC_PLAY_WORDS = ("soothe", "comfort", "calm")
_SOOTHE_GENERIC_PLAY_CONTEXT = ("baby", "cry", "crying")
_SOOTHE_AUTOSOOTHE_ON = (
    "start watching for crying",
    "start watching",
    "start cry guard",
    "start cryguard",
    "watch for crying",
    "auto soothe on",
)
_SOOTHE_AUTOSOOTHE_OFF = (
    "stop watching",
    "stop cry guard",
    "stop cryguard",
    "auto soothe off",
)
_SOOTHE_NEXT_WORDS = ("next", "switch", "try another")
_SOOTHE_VOLUME_UP = ("louder",)
_SOOTHE_VOLUME_DOWN = ("quieter",)


def _soothe_display_names(
    presets: Mapping[str, object] | None = None,
) -> dict[str, str]:
    if not presets:
        return dict(_DEFAULT_SOOTHE_PRESETS)
    names: dict[str, str] = {}
    for key, preset in presets.items():
        label = getattr(preset, "name", None)
        names[str(key)] = str(label or key).strip() or str(key)
    return names


def _soothe_aliases(presets: Mapping[str, object] | None = None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, display_name in _soothe_display_names(presets).items():
        aliases[normalize_transcript(key.replace("_", " "))] = key
        aliases[normalize_transcript(display_name)] = key
    for key, display_name in _DEFAULT_SOOTHE_PRESETS.items():
        aliases.setdefault(normalize_transcript(key.replace("_", " ")), key)
        aliases.setdefault(normalize_transcript(display_name), key)
    aliases.update(
        {
            "heart beat": "heartbeat",
            "music": "soothing_music",
            "song": "soothing_music",
            "melody": "soothing_music",
            "lullaby": "soothing_music",
            "whoosh": "uterine_whoosh",
            "womb": "uterine_whoosh",
            "uterine": "uterine_whoosh",
            "white": "white_noise",
            "noise": "white_noise",
            "static": "white_noise",
            "hush": "white_noise",
            "ocean": "ocean_waves",
            "waves": "ocean_waves",
        }
    )
    return aliases


def _soothe_preset_from(
    q: str,
    presets: Mapping[str, object] | None = None,
) -> str | None:
    aliases = _soothe_aliases(presets)
    words = q.split()
    without_articles = " ".join(word for word in words if word not in {"a", "an", "the"})
    for text in (q, without_articles):
        for alias in sorted(aliases, key=lambda value: (-len(value.split()), value)):
            if _mentions(text, alias):
                return aliases[alias]
    return None


def match_soothe_command(
    question: str,
    presets: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    """Detect a soothe play/stop command, or None. Returns e.g.
    {"action": "play", "preset": "white_noise"} or {"action": "stop"}."""
    q = normalize_transcript(question)
    if _mentions(q, *_SOOTHE_AUTOSOOTHE_ON):
        return {"action": "autosoothe", "enabled": True}
    if _mentions(q, *_SOOTHE_AUTOSOOTHE_OFF):
        return {"action": "autosoothe", "enabled": False}

    preset = _soothe_preset_from(q, presets)
    context = preset is not None or _mentions(
        q, "soothe", "sound", "noise", "music", "playing", "it", "that", "crying", "cry"
    )
    if q == "stop":
        return {"action": "stop"}
    if _mentions(q, *_SOOTHE_STOP_WORDS) and context:
        return {"action": "stop"}
    if _mentions(q, *_SOOTHE_NEXT_WORDS):
        return {"action": "next"}
    if _mentions(q, *_SOOTHE_VOLUME_UP):
        return {"action": "volume", "dir": "up"}
    if _mentions(q, *_SOOTHE_VOLUME_DOWN):
        return {"action": "volume", "dir": "down"}
    if _mentions(q, *_SOOTHE_PLAY_WORDS):
        if preset is not None:
            return {"action": "play", "preset": preset}
        if _mentions(q, *_SOOTHE_GENERIC_PLAY_WORDS) and _mentions(
            q, *_SOOTHE_GENERIC_PLAY_CONTEXT
        ):
            return {"action": "play", "preset": "white_noise"}
    return None


def _answer_intent_result(intent: str, snapshot: dict[str, object]) -> _AnswerResult:
    if intent == "temperature":
        value = _num(snapshot, "room_temperature_c")
        if value is not None:
            return _AnswerResult(_temperature_phrase(value), intent)
    if intent == "humidity":
        value = _num(snapshot, "room_humidity_pct")
        if value is not None:
            return _AnswerResult(_humidity_phrase(value), intent)
    if intent == "pressure":
        value = _num(snapshot, "room_pressure_hpa")
        if value is not None:
            return _AnswerResult(_pressure_phrase(value), intent)
    if intent == "air quality":
        value = _num(snapshot, "room_gas_resistance_ohms")
        if value is not None:
            return _AnswerResult(_air_quality_phrase(value), intent)
    if intent == "brightness":
        value = _num(snapshot, "room_illuminance_lx")
        if value is not None:
            return _AnswerResult(_brightness_phrase(value), intent)
    if intent == "count":
        return _AnswerResult(_people_phrase(snapshot), intent)
    if intent == "motion":
        motion = snapshot.get("motion_detected")
        if isinstance(motion, bool):
            answer = "There's movement in the room." if motion else "The room is still."
            return _AnswerResult(answer, intent)
    if intent == "anyone":
        return _AnswerResult(_presence_phrase(snapshot), intent)
    if intent == "distance":
        value = _num(snapshot, "target_distance_cm")
        if value is not None:
            return _AnswerResult(
                f"The nearest person is about {value:.0f} centimetres away.",
                intent,
            )
    if intent == "overview":
        return _AnswerResult(_room_overview(snapshot), intent)
    return _AnswerResult(_FALLBACK)


_FOLLOWUP_PREFIXES = ("what about ", "how about ", "and ")
_BARE_OK_FOLLOWUPS = (
    "is it ok", "is it okay", "is it alright", "is it all right",
    "is it comfortable",
)


def _explicit_followup_intent(q: str) -> str | None:
    if _mentions(
        q, "temperature", "warm", "hot", "cold", "chilly", "degree", "degrees",
        fuzzy=("temperature",),
    ):
        return "temperature"
    if _mentions(q, "humid", "humidity", "muggy", "dry", "damp", fuzzy=("humidity",)):
        return "humidity"
    if _mentions(q, "pressure", "barometer", fuzzy=("pressure",)):
        return "pressure"
    if _mentions(
        q, "air quality", "gas", "smell", "smelly", "voc", "stuffy", "fresh", "nappy",
        fuzzy=("quality",),
    ):
        return "air quality"
    if _mentions(q, "light", "lighting", "lit", "bright", "dark", "dim", "lux"):
        return "brightness"
    if _mentions(q, "how many", "number of people", "headcount", "count"):
        return "count"
    if _mentions(q, "moving", "movement", "motion", "still", "activity"):
        return "motion"
    if _mentions(
        q, "anyone", "anybody", "someone", "somebody", "everyone", "everybody",
        "nearby", "occupied", "empty", "who", "people", "person",
    ):
        return "anyone"
    if _mentions(q, "how far", "distance", "close"):
        return "distance"
    if _mentions(
        q, "how is the room", "room condition", "condition", "everything", "overview",
        "how are things", "status", "report", "summary", "rundown", "how is it",
        "in here", "in there", "the room", "room like", "what s it like",
        "comfortable", "cozy", "cosy", "nice",
    ):
        return "overview"
    return None


def _resolve_followup_intent(
    question: str,
    last_intent: str | None,
) -> str | None:
    q = normalize_transcript(question)
    if not q:
        return None

    explicit = _explicit_followup_intent(q)
    if explicit is not None and any(q.startswith(prefix) for prefix in _FOLLOWUP_PREFIXES):
        return explicit
    if explicit is not None and _mentions(q, "that", "this"):
        return explicit

    if not (
        _mentions(q, "that", "this")
        or q in _BARE_OK_FOLLOWUPS
    ):
        return None
    if last_intent in INTENT_KEYWORDS:
        return last_intent
    return None


def _remember_answer(
    memory: ConversationMemory | None,
    result: _AnswerResult,
) -> None:
    if memory is not None and result.answer != _FALLBACK:
        memory.last_intent = result.intent


def answer_question(
    question: str,
    snapshot: dict[str, object],
    llm_translator: object | None = None,
    ask_llm: AskLlm | None = None,
    *,
    memory: ConversationMemory | None = None,
) -> str:
    """Answer a plain-language question from the current sensor snapshot."""
    if memory is not None:
        followup_intent = _resolve_followup_intent(question, memory.last_intent)
        if followup_intent is not None:
            followup = _answer_intent_result(followup_intent, snapshot)
            _remember_answer(memory, followup)
            return followup.answer

    result = _deterministic_answer_result(question, snapshot)
    if result.answer != _FALLBACK:
        _remember_answer(memory, result)
        return result.answer
    if llm_translator is None or not getattr(llm_translator, "enabled", False):
        return result.answer

    intent = translate_intent(question, llm_translator, ask_llm=ask_llm)
    if intent not in INTENT_KEYWORDS:
        return result.answer

    translated = _answer_intent_result(intent, snapshot)
    if translated.answer != _FALLBACK:
        _remember_answer(memory, translated)
        return translated.answer
    return result.answer


def _deterministic_answer_question(question: str, snapshot: dict[str, object]) -> str:
    return _deterministic_answer_result(question, snapshot).answer


def _deterministic_answer_result(
    question: str,
    snapshot: dict[str, object],
) -> _AnswerResult:
    q = normalize_transcript(question)

    # Unsupported vitals first (oxygen, blood pressure, fever...): say we don't
    # measure them — routed before the room-pressure branch so "blood pressure"
    # never returns air pressure.
    if _mentions(q, *_UNSUPPORTED_VITALS):
        return _AnswerResult(_unsupported_vitals_phrase())

    # Supported vitals next: an explicit breathing/heart/pulse question is answered
    # from the radar's bench data, routed before any other branch can capture a
    # vitals-flavoured question (even one with an incidental "still"/"moving"/
    # "warm" in it). The answer never reassures and never claims wellbeing.
    if _mentions(q, *_VITALS_WORDS):
        return _AnswerResult(_vitals_phrase(snapshot))

    # Specific readings first, so "how warm is the room" routes to temperature
    # rather than the general overview.
    if _mentions(
        q, "temperature", "warm", "hot", "cold", "chilly", "degree", "degrees",
        fuzzy=("temperature",),
    ):
        result = _answer_intent_result("temperature", snapshot)
        if result.answer != _FALLBACK:
            return result

    if _mentions(q, "humid", "humidity", "muggy", "dry", "damp", fuzzy=("humidity",)):
        result = _answer_intent_result("humidity", snapshot)
        if result.answer != _FALLBACK:
            return result

    if _mentions(q, "pressure", "barometer", fuzzy=("pressure",)):
        result = _answer_intent_result("pressure", snapshot)
        if result.answer != _FALLBACK:
            return result

    if _mentions(
        q, "air quality", "gas", "smell", "smelly", "voc", "stuffy", "fresh", "nappy",
        fuzzy=("quality",),
    ):
        result = _answer_intent_result("air quality", snapshot)
        if result.answer != _FALLBACK:
            return result

    if _mentions(
        q, "light", "lighting", "lit", "bright", "dark", "dim", "lux",
        fuzzy=("brightness",),
    ):
        result = _answer_intent_result("brightness", snapshot)
        if result.answer != _FALLBACK:
            return result

    if _mentions(q, "how many", "number of people", "headcount", "count"):
        return _answer_intent_result("count", snapshot)

    # Motion before presence, so "is there any movement" reaches motion rather
    # than being captured by a generic presence phrase.
    if _mentions(q, "moving", "movement", "motion", "still", "activity"):
        result = _answer_intent_result("motion", snapshot)
        if result.answer != _FALLBACK:
            return result

    if _mentions(
        q, "anyone", "anybody", "someone", "somebody", "everyone", "everybody",
        "nearby", "occupied", "empty", "who", "people", "person",
    ):
        return _answer_intent_result("anyone", snapshot)

    if _mentions(q, "how far", "distance", "close"):
        result = _answer_intent_result("distance", snapshot)
        if result.answer != _FALLBACK:
            return result

    # A wellbeing check about the baby (not the room) surfaces the labelled radar
    # vitals, checked after the specific room/presence/motion branches so "is the
    # baby too warm" still answers temperature and "is the baby moving" still
    # answers motion. Narrow phrases only, so "is the baby asleep/crying/hungry"
    # fall through to the fallback rather than being answered with vitals numbers.
    if _mentions(q, *_BABY_VITALS_PHRASES):
        return _AnswerResult(_vitals_phrase(snapshot))

    # General "how is the room?" — a whole-room overview, checked last so specific
    # questions win.
    if _mentions(
        q, "how is the room", "room condition", "condition", "everything", "overview",
        "how are things", "status", "report", "summary", "rundown", "how is it",
        "in here", "in there", "the room", "room like", "what s it like",
        "comfortable", "cozy", "cosy", "nice",
    ):
        return _answer_intent_result("overview", snapshot)

    return _AnswerResult(_FALLBACK)
