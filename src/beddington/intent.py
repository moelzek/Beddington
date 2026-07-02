from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

INTENT_KEYWORDS = (
    "temperature",
    "humidity",
    "pressure",
    "air quality",
    "brightness",
    "count",
    "motion",
    "anyone",
    "distance",
    "overview",
    "scene",
)

_INTENT_HINTS = (
    ("temperature", "room warmth or coolness"),
    ("humidity", "dry, damp, muggy, or humid air"),
    ("pressure", "air pressure or barometer"),
    ("air quality", "stuffy air, smell, gas, VOC, or nappy smell"),
    ("brightness", "light, lighting, dark, dim, or bright"),
    ("count", "number of people"),
    ("motion", "movement, activity, or stillness in the room"),
    ("anyone", "whether someone is in the room"),
    ("distance", "how far away the nearest person is"),
    ("overview", "broad room condition or status"),
    ("scene", "what the local room readings suggest is visible"),
)

_TOKEN = re.compile(r"[a-z ]+")
_DIGIT = re.compile(r"\d")

AskLlm = Callable[[str, Any], str | None]

LLAMA_UNAVAILABLE = "Sorry, I can't reach my local Llama right now."
LLAMA_DECLINED = "Sorry, I can't answer that from here."

_LEAD_BANNED_WORDS = (
    "safe", "healthy", "asleep", "sleeping", "slept", "breathing", "heartbeat",
    "heart", "pulse", "fine", "normal", "stable", "medical", "diagnose",
    "fever", "apnoea", "apnea", "oxygen",
)
_LEAD_BANNED_PHRASES = (
    "don t worry", "nothing to worry", "all good", "doing well", "all is well",
    "sound asleep", "fast asleep",
)
_SOOTHE_ACTIONS = {
    "play", "play_best", "stop", "next", "volume", "autosoothe", "feedback",
}
_SOOTHE_CONTEXTS = {"sleep", "feeding", "nappy", "settling", "waking"}
_SOOTHE_CATEGORIES = {"music", "sounds"}
_SOOTHE_MOODS = {"relaxing"}


def translate_intent(
    question: str,
    config: Any,
    ask_llm: AskLlm | None = None,
) -> str | None:
    """Return one deterministic assistant keyword, or None on any failure."""
    if not getattr(config, "enabled", False):
        return None
    if getattr(config, "backend", "ollama") != "ollama":
        return None
    if not str(getattr(config, "model", "")).strip():
        return None
    if not str(getattr(config, "host", "")).strip():
        return None

    prompt = _build_prompt(question)
    caller = ask_llm or _ask_ollama
    try:
        response = caller(prompt, config)
    except Exception:
        return None
    if response is None:
        return None
    return _keyword_from_response(response)


def lead_response(
    question: str,
    config: Any,
    ask_llm: AskLlm | None = None,
) -> str:
    """Let local Llama lead non-sensor conversation, with product guardrails."""
    if not getattr(config, "enabled", False):
        return LLAMA_UNAVAILABLE
    if getattr(config, "backend", "ollama") != "ollama":
        return LLAMA_UNAVAILABLE
    if not str(getattr(config, "model", "")).strip():
        return LLAMA_UNAVAILABLE
    if not str(getattr(config, "host", "")).strip():
        return LLAMA_UNAVAILABLE

    prompt = _build_lead_prompt(question)
    caller = ask_llm or _ask_lead_ollama
    try:
        response = caller(prompt, config)
    except Exception:
        return LLAMA_UNAVAILABLE
    answer = _clean_lead_response(response or "")
    return answer if answer is not None else LLAMA_DECLINED


def translate_soothe_command(
    question: str,
    config: Any,
    presets: Mapping[str, object] | None = None,
    ask_llm: AskLlm | None = None,
) -> dict[str, object] | None:
    """Let local Llama classify a soothe/music request, then validate it."""
    if not getattr(config, "enabled", False):
        return None
    if getattr(config, "backend", "ollama") != "ollama":
        return None
    if not str(getattr(config, "model", "")).strip():
        return None
    if not str(getattr(config, "host", "")).strip():
        return None

    prompt = _build_soothe_prompt(question, presets)
    caller = ask_llm or _ask_soothe_ollama
    try:
        response = caller(prompt, config)
    except Exception:
        return None
    return _soothe_command_from_response(response or "", presets)


def _build_prompt(question: str) -> str:
    options = "\n".join(
        f"- {keyword}: {hint}" for keyword, hint in _INTENT_HINTS
    )
    return (
        "Classify the parent's question for Beddington's deterministic room "
        "assistant.\n"
        "Reply with exactly one keyword from the list, and nothing else. "
        "Do not answer the question. Do not include a reading, number, unit, "
        "advice, or explanation. If no keyword fits, reply none.\n\n"
        "Keywords:\n"
        f"{options}\n\n"
        f"Question: {question}\n"
        "Keyword:"
    )


def _build_lead_prompt(question: str) -> str:
    return (
        "You are Beddington, a warm, polite local baby-monitor companion with the "
        "gentle manner of Paddington Bear. The deterministic sensor layer has "
        "already handled room readings, presence, vitals, scene descriptions and "
        "soothe actions. You are now leading only the non-sensor conversation.\n"
        "Reply in one short sentence. Do not claim a room reading, camera view, "
        "sound, baby state, medical fact, safety reassurance, or soothe action. "
        "If the parent asks for a private fact you have not been told, say you "
        "do not know it yet.\n\n"
        f"Parent: {question}\n"
        "Beddington:"
    )


def _build_soothe_prompt(
    question: str,
    presets: Mapping[str, object] | None,
) -> str:
    preset_lines: list[str] = []
    for key, value in sorted((presets or {}).items()):
        label = getattr(value, "name", None)
        label_text = str(label or key).strip() or str(key)
        preset_lines.append(f"- {key}: {label_text}")
    if not preset_lines:
        preset_lines.append("- white_noise: white noise")
    return (
        "Classify the parent's local soothe/music command for Beddington. "
        "Reply with one compact JSON object only. Do not explain.\n"
        "Allowed actions:\n"
        '- {"action":"none"} when this is not a soothe/music command\n'
        '- {"action":"play","preset":"<preset_key>","context":"sleep|feeding|nappy|settling|waking"}\n'
        '- {"action":"play_best","category":"music|sounds","mood":"relaxing","context":"sleep|feeding|nappy|settling|waking"}\n'
        '- {"action":"stop"} or {"action":"next"}\n'
        '- {"action":"volume","dir":"up|down"}\n'
        '- {"action":"autosoothe","enabled":true|false}\n'
        '- {"action":"feedback","success":true|false,"context":"sleep|feeding|nappy|settling|waking"}\n'
        "Use only preset keys from this list:\n"
        + "\n".join(preset_lines)
        + "\nFor broad requests like 'play music for sleep', use play_best with "
        'category "music" and context "sleep". For "relaxing for feeding", use '
        'play_best with mood "relaxing" and context "feeding".\n\n'
        f"Parent: {question}\n"
        "JSON:"
    )


def _ask_ollama(prompt: str, config: Any) -> str | None:
    return _ask_ollama_with_options(
        prompt,
        config,
        num_predict=int(getattr(config, "intent_num_predict", 8)),
        temperature=float(getattr(config, "intent_temperature", 0.0)),
        timeout=float(getattr(config, "intent_timeout", 8.0)),
    )


def _ask_lead_ollama(prompt: str, config: Any) -> str | None:
    timeout = float(
        getattr(config, "lead_timeout", getattr(config, "persona_timeout", 12.0))
    )
    return _ask_ollama_with_options(
        prompt,
        config,
        num_predict=int(getattr(config, "lead_num_predict", 70)),
        temperature=float(getattr(config, "lead_temperature", 0.4)),
        timeout=timeout,
    )


def _ask_soothe_ollama(prompt: str, config: Any) -> str | None:
    timeout = float(
        getattr(
            config,
            "soothe_intent_timeout",
            getattr(config, "persona_timeout", 12.0),
        )
    )
    return _ask_ollama_with_options(
        prompt,
        config,
        num_predict=int(getattr(config, "soothe_intent_num_predict", 80)),
        temperature=float(getattr(config, "soothe_intent_temperature", 0.0)),
        timeout=timeout,
    )


def _ask_ollama_with_options(
    prompt: str,
    config: Any,
    *,
    num_predict: int,
    temperature: float,
    timeout: float,
) -> str | None:
    payload = {
        "model": str(getattr(config, "model")),
        "prompt": prompt,
        "stream": False,
        # Unload between the rare voice-intent calls so the model doesn't hold
        # RAM 24/7 on the 4GB Pi.
        "keep_alive": 0,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    endpoint = str(getattr(config, "host")).rstrip("/") + "/api/generate"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "beddington/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
        text = str(result.get("response", "")).strip()
    except Exception:
        return None
    return text or None


def _keyword_from_response(text: str) -> str | None:
    if _DIGIT.search(text):
        return None
    cleaned = text.strip().split("\n", 1)[0].strip().strip("`'\" .,;:")
    cleaned = cleaned.replace("_", " ").lower()
    cleaned = " ".join(_TOKEN.findall(cleaned)).strip()
    if cleaned == "none":
        return None
    if cleaned in INTENT_KEYWORDS:
        return cleaned
    return None


def _clean_lead_response(text: str) -> str | None:
    cleaned = text.strip().split("\n\n", 1)[0].split("\n", 1)[0].strip()
    cleaned = cleaned.strip("`'\" ")
    if not cleaned:
        return None
    if len(cleaned) > 220:
        return None
    if cleaned.count(".") + cleaned.count("!") + cleaned.count("?") > 2:
        return None
    norm = " " + re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip() + " "
    for word in _LEAD_BANNED_WORDS:
        if f" {word} " in norm:
            return None
    for phrase in _LEAD_BANNED_PHRASES:
        if f" {phrase} " in norm:
            return None
    if _DIGIT.search(cleaned):
        return None
    sensor_words = {
        "degrees", "celsius", "percent", "humidity", "temperature", "pressure",
        "illuminance", "lux", "centimetres", "centimetre", "detected", "reading",
    }
    if any(f" {word} " in norm for word in sensor_words):
        return None
    return cleaned


def _soothe_command_from_response(
    text: str,
    presets: Mapping[str, object] | None,
) -> dict[str, object] | None:
    parsed = _parse_json_object(text)
    if not isinstance(parsed, dict):
        return None
    action = str(parsed.get("action") or "").strip().lower()
    if action == "none":
        return None
    if action not in _SOOTHE_ACTIONS:
        return None

    command: dict[str, object] = {"action": action}
    context = _normalise_soothe_context(parsed.get("context"))
    if context:
        command["context"] = context

    if action == "play":
        allowed_presets = {str(key) for key in (presets or {})}
        preset = str(parsed.get("preset") or "").strip()
        if not preset or (allowed_presets and preset not in allowed_presets):
            return None
        command["preset"] = preset
        return command

    if action == "play_best":
        category = str(parsed.get("category") or "").strip().lower()
        mood = str(parsed.get("mood") or "").strip().lower()
        if category:
            if category not in _SOOTHE_CATEGORIES:
                return None
            command["category"] = category
        if mood:
            if mood not in _SOOTHE_MOODS:
                return None
            command["mood"] = mood
        if not any(key in command for key in ("category", "mood", "context")):
            return None
        return command

    if action == "volume":
        direction = str(parsed.get("dir") or "").strip().lower()
        if direction not in {"up", "down"}:
            return None
        command["dir"] = direction
        return command

    if action == "autosoothe":
        enabled = parsed.get("enabled")
        if not isinstance(enabled, bool):
            return None
        command["enabled"] = enabled
        preset = str(parsed.get("preset") or "").strip()
        allowed_presets = {str(key) for key in (presets or {})}
        if preset:
            if allowed_presets and preset not in allowed_presets:
                return None
            command["preset"] = preset
        return command

    if action == "feedback":
        success = parsed.get("success")
        if not isinstance(success, bool):
            return None
        command["success"] = success
        return command

    return command


def _parse_json_object(text: str) -> object | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _normalise_soothe_context(value: object) -> str:
    context = str(value or "").strip().lower()
    aliases = {
        "feed": "feeding",
        "feeds": "feeding",
        "meal": "feeding",
        "nap": "sleep",
        "night": "sleep",
        "bed": "sleep",
        "bedtime": "sleep",
        "diaper": "nappy",
        "change": "nappy",
        "wake": "waking",
    }
    context = aliases.get(context, context)
    return context if context in _SOOTHE_CONTEXTS else ""
