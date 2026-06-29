from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
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
)

_TOKEN = re.compile(r"[a-z ]+")
_DIGIT = re.compile(r"\d")

AskLlm = Callable[[str, Any], str | None]


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


def _ask_ollama(prompt: str, config: Any) -> str | None:
    payload = {
        "model": str(getattr(config, "model")),
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": int(getattr(config, "intent_num_predict", 8)),
            "temperature": float(getattr(config, "intent_temperature", 0.0)),
        },
    }
    endpoint = str(getattr(config, "host")).rstrip("/") + "/api/generate"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "beddington/0.1"},
        method="POST",
    )
    timeout = float(getattr(config, "intent_timeout", 8.0))
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
